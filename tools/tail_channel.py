"""Fetch the last N messages from a game's channel, and optionally
keep tailing new ones until the operator stops with Ctrl-C.

Channel discovery is game-centric because a guild can host many
concurrent games (one per channel / thread). The tool queries the
``games`` collection for live games in the selected DB, resolves
each game's ``channel_id`` to a channel name via Discord REST for
a friendly picker, and fetches from whichever the operator picks.
``--channel-id`` bypasses the picker entirely — useful for
automation or when the game's channel id is already known.

Usage::

    python -m tools.tail_channel LIVE                          # pick game interactively
    python -m tools.tail_channel TEST                          # same, against TEST DB
    python -m tools.tail_channel LIVE --limit 20               # last 20 messages
    python -m tools.tail_channel LIVE --follow                 # tail new messages (poll)
    python -m tools.tail_channel LIVE --channel-id 999         # skip picker
    python -m tools.tail_channel LIVE --guild 123              # narrow picker to one guild

The ``LIVE`` / ``TEST`` positional is mandatory and maps to the
matching ``LIVE_DB_NAME`` / ``TEST_DB_NAME`` env var internally.
It's also the authoritative "which environment is this process
tailing?" tag — visible in ``ps`` / ``tasklist`` without any
lookup — so the reader tools (``tail_peek``, ``tail_watch``,
``tail_balance``) accept the same shortname and connect to the
matching default port (LIVE=8765, TEST=8766).

Output is plain markdown — header with channel context, one
sub-header per message with timestamp + author, body quoted
verbatim. Designed so a follow-up planning conversation can
consume the log without reformatting.

Why polling, not Gateway: the live bot owns the Gateway
connection for its token. Opening a second Gateway from this tool
would trip Discord's one-session-per-shard rule. REST
``GET /channels/{id}/messages?after=<id>`` is the standard
workaround and what ``check_ideas`` already does for its
ideas-channel cursor.

Inspection HTTP endpoint (``--follow`` only)
============================================

When ``--follow`` is on, the tool also starts a tiny localhost
HTTP server so an on-demand inspector can peek at the last N
messages without grepping stdout. GET ``/tail`` returns JSON::

    {
      "messages": [{"id": "...", "timestamp": "...",
                    "author": "...", "content": "..."}],
      "dropped_count": 0,
      "buffer_size": 12,
      "buffer_max": <``--buffer-size``, default per ``_DEFAULT_BUFFER_SIZE``>
    }

``?since=<message_id>`` filters to messages strictly newer than
the given snowflake — callers persist their own cursor between
polls. ``dropped_count`` increments whenever the ring buffer
evicts an old entry so a caller can tell when they missed a
window rather than silently losing events. Loopback-bound
(``127.0.0.1``); no auth required.
"""

import argparse
import asyncio
import collections
import re
import sys
from typing import Optional

import aiohttp
from aiohttp import web

from tools._common import (
    DiscordRestClient,
    get_auth,
    live_db,
    resolve_tail_env,
    TAIL_ENVS,
    use_db_env_var,
)


_DEFAULT_LIMIT = 10
_DEFAULT_POLL_SECONDS = 5
_DEFAULT_BUFFER_SIZE = 5000
_DEFAULT_HTTP_PORT = 8765

# Discord channel type ids — see
# https://discord.com/developers/docs/resources/channel#channel-object-channel-types
_THREAD_TYPES = {10, 11, 12}  # news thread, public thread, private thread

# Matches Discord's SGR ANSI color escapes as they appear in message
# content — both the full ``\x1b[...m`` form and the bare ``[...m``
# fallback (some consumers strip the ESC before we see it). Used to
# scrub color noise out of ``$health`` / body-parts output so the
# buffer reads cleanly in text views.
_ANSI_RE = re.compile(r"\x1b?\[\d[\d;]*m")

# Zero-width / invisible unicode that Discord embeds sometimes use as
# a vertical spacer field (``​: ​`` after flattening). Treat these as
# "empty" when deciding whether to include a field in the text render.
_ZERO_WIDTH = {"\u200b", "\u200c", "\u200d", "\ufeff"}

# Discord user mentions — legacy ``<@!id>`` (nickname) and modern
# ``<@id>``. Role (``<@&id>``) and channel (``<#id>``) mentions are
# deliberately left unresolved today: the game's embeds rarely use
# role mentions for names, and channel mentions aren't relevant to
# player-name display.
_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")


class TailBuffer:
    """In-memory ring buffer of recent messages for the HTTP inspector.

    ``deque(maxlen=N)`` silently drops old entries when full; we
    track that explicitly in ``dropped_count`` so a caller can tell
    when they missed a window rather than silently losing events.
    """

    def __init__(self, maxsize: int):
        self._buffer: collections.deque[dict] = collections.deque(maxlen=maxsize)
        self._dropped = 0

    def append(self, entry: dict) -> None:
        if len(self._buffer) == self._buffer.maxlen:
            self._dropped += 1
        self._buffer.append(entry)

    def snapshot(self, since_id: Optional[int] = None) -> dict:
        """Return a JSON-ready snapshot. ``since_id`` filters to
        messages with a numeric id strictly greater than the given
        value; entries without an id are always included (should be
        rare but we don't want to silently drop them)."""
        messages = list(self._buffer)
        if since_id is not None:
            def _keep(m: dict) -> bool:
                mid = m.get("id")
                if not mid:
                    return True
                try:
                    return int(mid) > since_id
                except (TypeError, ValueError):
                    return True
            messages = [m for m in messages if _keep(m)]
        return {
            "messages": messages,
            "dropped_count": self._dropped,
            "buffer_size": len(self._buffer),
            "buffer_max": self._buffer.maxlen,
        }


def _strip_ansi(text: str) -> str:
    """Remove SGR ANSI color escapes from message content.

    The game's ``$health`` and body-parts panels are rendered
    inside an ``ansi`` code block so Discord colorizes injury
    states; in plain-text views (buffer, peek output), the escape
    sequences are just noise.
    """
    return _ANSI_RE.sub("", text) if text else text


def _is_visually_empty(s: str) -> bool:
    """True if the string is empty, whitespace, or composed only
    of zero-width / invisible unicode — used to skip Discord's
    vertical-spacer embed fields (``​: ​``) that flatten to noise."""
    if not s:
        return True
    return all(c.isspace() or c in _ZERO_WIDTH for c in s)


def _render_embeds(embeds: list) -> str:
    """Flatten a list of Discord embed objects into plain text.

    Embeds are how the game renders monster spawn cards, ``$stats``,
    ``$inventory``, and similar structured panels — invisible if we
    only look at ``content``. We surface: author name, title,
    description, each field's ``name: value`` pair, and the footer,
    in the order Discord renders them. Missing or visually-empty
    pieces are skipped (Discord's zero-width-spacer fields don't
    survive flattening, so they would otherwise render as ``​: ​``).
    """
    if not embeds:
        return ""
    rendered: list[str] = []
    for emb in embeds:
        parts: list[str] = []
        author = (emb.get("author") or {}).get("name")
        if author and not _is_visually_empty(author):
            parts.append(f"_{author}_")
        title = emb.get("title")
        if title and not _is_visually_empty(title):
            parts.append(f"**{title}**")
        description = emb.get("description")
        if description and not _is_visually_empty(description):
            parts.append(description)
        for field in emb.get("fields") or []:
            name = (field.get("name") or "").strip()
            value = (field.get("value") or "").strip()
            name_empty = _is_visually_empty(name)
            value_empty = _is_visually_empty(value)
            if name_empty and value_empty:
                continue  # spacer field, drop entirely
            if not name_empty and not value_empty:
                parts.append(f"{name}: {value}")
            elif not name_empty:
                parts.append(name)
            elif not value_empty:
                parts.append(value)
        footer = (emb.get("footer") or {}).get("text")
        if footer and not _is_visually_empty(footer):
            parts.append(f"— {footer}")
        if parts:
            rendered.append("\n".join(parts))
    return "\n\n".join(rendered)


def _build_mention_map(guild_id: int, channel_id: int) -> dict:
    """Look up the game's players and return ``{user_id: name}``
    for mention resolution. Returns an empty dict when the game's
    guild / channel isn't set (``--channel-id`` with no ``--guild``)
    or when no players have joined yet."""
    if not guild_id or not channel_id:
        return {}
    try:
        docs = live_db().players.find({
            "guild_id": guild_id,
            "channel_id": channel_id,
        })
    except Exception:
        return {}
    return {
        int(d["user_id"]): d["name"]
        for d in docs
        if d.get("user_id") is not None and d.get("name")
    }


def _resolve_mentions(text: str, mention_map: dict) -> str:
    """Replace ``<@id>`` / ``<@!id>`` user mentions with
    ``@<player_name>`` using the game's mention map. Unknown ids
    (non-player Discord users) are left as the raw mention so the
    reader can still look them up manually."""
    if not text or not mention_map:
        return text
    def _sub(m: re.Match) -> str:
        uid = int(m.group(1))
        name = mention_map.get(uid)
        return f"@{name}" if name else m.group(0)
    return _USER_MENTION_RE.sub(_sub, text)


def _message_content(msg: dict, mention_map: Optional[dict] = None) -> str:
    """Return the message's display text, folding in any embed content.

    Text content and embed content can both be present (rare but
    possible); we concatenate with a blank line so the reader can
    tell them apart. Embed-only messages (spawn cards, ``$stats``)
    render the embed's title/description/fields in lieu of an empty
    string so the inspector isn't blind to them.

    Polishes applied once here so both the buffer and the stdout
    renderer see the same text: strip SGR ANSI color escapes, and
    resolve ``<@id>`` user mentions via the supplied mention map.
    """
    content = (msg.get("content") or "").strip()
    embed_text = _render_embeds(msg.get("embeds") or [])
    if embed_text and content:
        combined = f"{content}\n\n{embed_text}"
    else:
        combined = content or embed_text
    combined = _strip_ansi(combined)
    if mention_map:
        combined = _resolve_mentions(combined, mention_map)
    return combined


def _make_buffer_entry(msg: dict, mention_map: Optional[dict] = None) -> dict:
    """Reduce a Discord message payload to the compact buffer record.

    The full payload has ~30 fields we don't need; the inspector
    only ever consumes ``id`` (cursor), ``timestamp``, ``author``,
    and ``content`` (including folded-in embed content). Keeps
    buffer memory tiny and snapshots cheap to serialize.
    """
    author = msg.get("author") or {}
    return {
        "id": msg.get("id"),
        "timestamp": msg.get("timestamp"),
        "author": (
            author.get("global_name")
            or author.get("username")
            or "<unknown>"
        ),
        "content": _message_content(msg, mention_map=mention_map),
    }


def _find_games(guild_filter: Optional[int]) -> list[dict]:
    """Return per-game dicts from the ``games`` collection.

    Each dict has ``guild_id`` and ``channel_id``. Optional
    ``guild_filter`` narrows to one guild. Channel names are not
    in the DB; the caller resolves them via Discord REST.
    """
    query: dict = {"guild_id": {"$exists": True}, "channel_id": {"$exists": True}}
    if guild_filter is not None:
        query["guild_id"] = guild_filter
    games: list[dict] = []
    for doc in live_db().games.find(query):
        games.append({
            "guild_id": int(doc["guild_id"]),
            "channel_id": int(doc["channel_id"]),
        })
    return games


def _guild_name_lookup(guild_ids: set[int]) -> dict[int, str]:
    """Return a ``{guild_id: display_name}`` map from the
    ``servers`` collection. Missing names fall back to
    ``"<unnamed guild {id}>"`` so the picker is never blank."""
    if not guild_ids:
        return {}
    names: dict[int, str] = {}
    for doc in live_db().servers.find({"guild_id": {"$in": list(guild_ids)}}):
        names[int(doc["guild_id"])] = (
            doc.get("name") or f"<unnamed guild {doc['guild_id']}>"
        )
    for gid in guild_ids:
        names.setdefault(gid, f"<unnamed guild {gid}>")
    return names


async def _resolve_channel(
    client: DiscordRestClient, channel_id: int,
) -> dict:
    """Fetch a channel object from Discord. Returns a compact dict
    with ``name``, ``type``, and ``parent_id`` — enough for the
    picker to distinguish threads from parent channels.

    On error (deleted / unreachable / permissions), returns a
    placeholder so the picker still renders a line instead of
    exploding on the first broken game."""
    try:
        data = await client.get_channel(channel_id)
    except aiohttp.ClientError as e:
        return {"name": f"<unavailable: {e}>", "type": None, "parent_id": None}
    return {
        "name": data.get("name") or "<no-name>",
        "type": data.get("type"),
        "parent_id": data.get("parent_id"),
    }


async def _hydrate_games(
    client: DiscordRestClient, games: list[dict],
) -> list[dict]:
    """Add channel-name context + parent-channel names (for threads)
    to each game. Runs resolutions concurrently because N is small
    and operator waiting scales linearly otherwise."""
    channel_infos = await asyncio.gather(
        *(_resolve_channel(client, g["channel_id"]) for g in games)
    )
    # Collect parent ids up front so threads can show "(thread of #main)".
    parent_ids = {
        info["parent_id"]
        for info in channel_infos
        if info["type"] in _THREAD_TYPES and info.get("parent_id")
    }
    parent_infos: dict[int, dict] = {}
    if parent_ids:
        resolved = await asyncio.gather(
            *(_resolve_channel(client, int(pid)) for pid in parent_ids)
        )
        parent_infos = dict(zip((int(pid) for pid in parent_ids), resolved))

    hydrated = []
    for game, info in zip(games, channel_infos):
        parent_name = None
        if info["type"] in _THREAD_TYPES and info.get("parent_id"):
            parent = parent_infos.get(int(info["parent_id"]))
            if parent:
                parent_name = parent["name"]
        hydrated.append({
            **game,
            "channel_name": info["name"],
            "channel_type": info["type"],
            "parent_name": parent_name,
        })
    return hydrated


def _format_game_choice(game: dict, guild_names: dict[int, str]) -> str:
    """One-line description for the interactive picker."""
    label = f"#{game['channel_name']}"
    if game["channel_type"] in _THREAD_TYPES and game["parent_name"]:
        label += f" (thread of #{game['parent_name']})"
    guild_label = guild_names.get(game["guild_id"], str(game["guild_id"]))
    return f"guild '{guild_label}' ({game['guild_id']}) — {label} ({game['channel_id']})"


def _pick_game(games: list[dict], guild_names: dict[int, str]) -> Optional[dict]:
    """Interactively pick one game. Auto-returns if there's only
    one candidate — no reason to prompt the operator to confirm
    the only option."""
    if len(games) == 1:
        return games[0]

    print("Multiple games found:", file=sys.stderr)
    for idx, game in enumerate(games, start=1):
        print(
            f"  [{idx}] {_format_game_choice(game, guild_names)}",
            file=sys.stderr,
        )
    while True:
        try:
            raw = input(f"Pick a game (1-{len(games)}, or q to quit): ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if raw.lower() in {"q", "quit", "exit"}:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(games):
            return games[int(raw) - 1]
        print(f"Invalid choice {raw!r}; try again.", file=sys.stderr)


def _format_message(msg: dict, mention_map: Optional[dict] = None) -> list[str]:
    """Render a single Discord message object as markdown lines
    (matches the ``check_ideas`` sub-header format so pasted
    transcripts look consistent across tools)."""
    author = msg.get("author") or {}
    author_name = (
        author.get("global_name")
        or author.get("username")
        or "<unknown>"
    )
    timestamp = msg.get("timestamp", "<no timestamp>")
    content = _message_content(msg, mention_map=mention_map)

    lines = [f"## {timestamp} — @{author_name}"]
    if content:
        for body_line in content.splitlines():
            lines.append(f"> {body_line}")
    else:
        lines.append("> *(no text or embed content — likely an attachment; check Discord)*")
    lines.append("")
    return lines


def _format_header(game: dict, guild_names: dict[int, str]) -> str:
    """One-off top header for the initial fetch block.

    When the caller bypassed game lookup via ``--channel-id`` and
    didn't supply ``--guild``, guild context is omitted rather
    than rendering a placeholder ``guild '0' (0)`` line.
    """
    channel_label = f"#{game['channel_name']}"
    if game["channel_type"] in _THREAD_TYPES and game["parent_name"]:
        channel_label += f" (thread of #{game['parent_name']})"
    pieces = [f"# Channel tail — {channel_label}"]
    if game.get("guild_id"):
        guild_label = guild_names.get(game["guild_id"], str(game["guild_id"]))
        pieces.append(f"guild '{guild_label}' ({game['guild_id']})")
    pieces.append(f"channel_id {game['channel_id']}")
    return ", ".join(pieces)


def _format_initial(
    game: dict, guild_names: dict[int, str], messages: list[dict],
    mention_map: Optional[dict] = None,
) -> str:
    """Render the initial fetch (header + N most recent messages,
    chronological)."""
    lines = [_format_header(game, guild_names)]
    if not messages:
        lines.append("")
        lines.append("*Channel has no messages (or none visible to the bot).*")
        return "\n".join(lines) + "\n"

    lines.append(f"*Last {len(messages)} message(s), chronological.*")
    lines.append("")
    for msg in reversed(messages):  # Discord returns newest-first
        lines.extend(_format_message(msg, mention_map=mention_map))
    return "\n".join(lines).rstrip() + "\n"


async def _tail_loop(
    client: DiscordRestClient,
    channel_id: int,
    last_seen_id: int,
    poll_seconds: int,
    buffer: Optional[TailBuffer] = None,
    mention_map: Optional[dict] = None,
) -> None:
    """Poll for new messages after ``last_seen_id`` until the
    operator stops with Ctrl-C. Appends each new message to the
    shared ring buffer (when provided) so the HTTP inspector can
    surface backlog on demand. No state persistence — a fresh
    ``--follow`` invocation starts from its own initial fetch."""
    print(
        f"[tailing channel {channel_id} — Ctrl-C to stop]",
        file=sys.stderr,
    )
    while True:
        try:
            await asyncio.sleep(poll_seconds)
            new_messages = await client.get_messages(
                channel_id, after=last_seen_id, limit=100,
            )
        except aiohttp.ClientError as e:
            print(f"Fetch failed: {e}. Retrying on next tick.", file=sys.stderr)
            continue
        except KeyboardInterrupt:
            return

        if not new_messages:
            continue

        # Chronological order into both the buffer and stdout.
        for msg in reversed(new_messages):
            if buffer is not None:
                buffer.append(_make_buffer_entry(msg, mention_map=mention_map))
            for line in _format_message(msg, mention_map=mention_map):
                print(line)
        sys.stdout.flush()
        last_seen_id = max(int(m["id"]) for m in new_messages)


def _make_tail_handler(buffer: TailBuffer):
    """Build the aiohttp handler closure bound to a specific buffer."""
    async def _handler(request: web.Request) -> web.Response:
        raw_since = request.query.get("since")
        since_id: Optional[int] = None
        if raw_since:
            try:
                since_id = int(raw_since)
            except ValueError:
                return web.json_response(
                    {"error": f"invalid since={raw_since!r}; expected integer"},
                    status=400,
                )
        return web.json_response(buffer.snapshot(since_id=since_id))
    return _handler


async def _start_http_server(
    buffer: TailBuffer, port: int,
) -> web.AppRunner:
    """Bring up the localhost inspector. Returns the runner so the
    caller can ``await runner.cleanup()`` on shutdown."""
    app = web.Application()
    app.router.add_get("/tail", _make_tail_handler(buffer))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    print(
        f"[inspector on http://127.0.0.1:{port}/tail "
        f"(buffer={buffer._buffer.maxlen})]",
        file=sys.stderr,
    )
    return runner


async def _run(args: argparse.Namespace, token: str) -> int:
    async with DiscordRestClient(token) as client:
        if args.channel_id is not None:
            # Operator supplied the channel id directly — skip all
            # Mongo / picker work and fetch straight away.
            channel_info = await _resolve_channel(client, args.channel_id)
            game = {
                "guild_id": args.guild if args.guild is not None else 0,
                "channel_id": args.channel_id,
                "channel_name": channel_info["name"],
                "channel_type": channel_info["type"],
                "parent_name": None,
            }
            if channel_info["type"] in _THREAD_TYPES and channel_info.get("parent_id"):
                parent = await _resolve_channel(client, int(channel_info["parent_id"]))
                game["parent_name"] = parent["name"]
            guild_names = _guild_name_lookup({game["guild_id"]}) if game["guild_id"] else {}
        else:
            games = _find_games(args.guild)
            if not games:
                scope = f" for guild {args.guild}" if args.guild is not None else ""
                print(
                    f"No games found in the DB{scope}. Spawn one with "
                    "``$spawn monster <name>`` in Discord, or pass "
                    "``--channel-id <id>`` to bypass game lookup.",
                    file=sys.stderr,
                )
                return 1
            guild_names = _guild_name_lookup({g["guild_id"] for g in games})
            hydrated = await _hydrate_games(client, games)
            picked = _pick_game(hydrated, guild_names)
            if picked is None:
                print("Aborted.", file=sys.stderr)
                return 1
            game = picked

        # Mention map: user_id → player name for the game's channel.
        # Built once at startup; players who join mid-session won't
        # resolve until a restart. Acceptable for now (rare during a
        # single playtest), cheap to revisit later.
        mention_map = _build_mention_map(
            game.get("guild_id") or 0, game["channel_id"],
        )

        messages = await client.get_messages(
            game["channel_id"], limit=args.limit,
        )
        print(_format_initial(game, guild_names, messages, mention_map=mention_map))

        if args.follow:
            if messages:
                last_seen_id = max(int(m["id"]) for m in messages)
            else:
                # Empty channel — seed with a current-time snowflake so
                # we don't re-fetch historical messages when they land
                # on a cleared channel. Discord snowflakes are ms since
                # 2015-01-01; using 0 would refetch everything. Using
                # ``None`` would mean "most recent" which returns old
                # messages. A high sentinel works: grab the channel's
                # own latest-so-far by asking for the last message.
                last_seen_id = 0

            # Seed the ring buffer with the initial-fetch block so an
            # inspector hitting ``/tail`` immediately after startup
            # gets the same context that was printed to stdout.
            buffer = TailBuffer(maxsize=args.buffer_size)
            for msg in reversed(messages):
                buffer.append(_make_buffer_entry(msg, mention_map=mention_map))

            runner = await _start_http_server(buffer, args.port)
            try:
                await _tail_loop(
                    client, game["channel_id"], last_seen_id,
                    args.poll_seconds, buffer=buffer,
                    mention_map=mention_map,
                )
            finally:
                await runner.cleanup()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        usage="python -m tools.tail_channel {LIVE|TEST} [options]",
        description=(
            "Tail a game's Discord channel. The FIRST ARGUMENT is "
            "required and picks the environment: LIVE or TEST. That "
            "shortname maps to the corresponding DB env var AND to a "
            "default inspector port (LIVE=8765, TEST=8766), so the "
            "running process tag in ``ps`` / ``tasklist`` answers "
            "'which env is this tailing?' without any lookup."
        ),
        epilog=(
            "Examples:\n"
            "  python -m tools.tail_channel LIVE --follow\n"
            "  python -m tools.tail_channel TEST --limit 20\n"
            "  python -m tools.tail_channel LIVE --channel-id 123 --follow\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "env",
        choices=list(TAIL_ENVS.keys()),
        metavar="ENV",
        help=(
            "REQUIRED. LIVE or TEST. Picks the DB env var "
            "(LIVE_DB_NAME / TEST_DB_NAME) and the default inspector "
            "port (LIVE=8765, TEST=8766)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_LIMIT,
        help=f"Initial message count (default: {_DEFAULT_LIMIT}; Discord caps at 100).",
    )
    parser.add_argument(
        "--guild",
        type=int,
        default=None,
        help="Restrict game lookup to one guild id.",
    )
    parser.add_argument(
        "--channel-id",
        type=int,
        default=None,
        help="Fetch from this channel id directly; skips game picker.",
    )
    parser.add_argument(
        "--follow", "-f",
        action="store_true",
        help="After the initial fetch, poll for new messages until Ctrl-C.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=int,
        default=_DEFAULT_POLL_SECONDS,
        help=(
            f"Poll interval for --follow (default: {_DEFAULT_POLL_SECONDS} "
            "seconds). REST-only; no Gateway."
        ),
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=_DEFAULT_BUFFER_SIZE,
        help=(
            f"Max messages held in the --follow inspector ring buffer "
            f"(default: {_DEFAULT_BUFFER_SIZE}). Older messages roll off "
            "once full; `dropped_count` in the snapshot tells you when."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Localhost inspector port override. When omitted, the "
            "port is chosen by env (LIVE=8765, TEST=8766). 127.0.0.1-"
            "bound only."
        ),
    )
    args = parser.parse_args()

    env_var, default_port = resolve_tail_env(args.env)
    effective_port = args.port if args.port is not None else default_port
    args.port = effective_port
    use_db_env_var(env_var)

    auth = get_auth()
    token = auth.get("TOKEN")
    if not token:
        print(
            "Auth document has no TOKEN field — tools can't authenticate "
            "to Discord.",
            file=sys.stderr,
        )
        return 1

    try:
        return asyncio.run(_run(args, token))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
