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
    python -m tools.tail_channel LIVE --since-time 9h          # everything from 9h ago to now
    python -m tools.tail_channel LIVE --since-time 9h --duration 1h
                                                               # 1h window starting 9h ago (i.e. 9h–8h ago)
    python -m tools.tail_channel LIVE --since-time 2026-04-25T16:00Z --until-time 2026-04-25T17:00Z
                                                               # absolute ISO range

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
from datetime import datetime, timedelta, timezone
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


# Discord epoch in ms (2015-01-01T00:00:00Z). Snowflakes are
# ``(ms_since_epoch << 22) | <internal bits>``; the high 42 bits
# are the time component, monotonically increasing.
_DISCORD_EPOCH_MS = 1420070400000

# Relative time spec: integer + unit suffix. ``9h`` = 9 hours
# ago from "now" at parse time. Units are second / minute / hour
# / day / week. Any other format falls through to ISO parsing.
_RELATIVE_TIME_RE = re.compile(r"^(\d+)([smhdw])$", re.IGNORECASE)
_RELATIVE_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}

# Safety cap on backward-paginated fetches. 50 batches × 100 msgs =
# 5000 messages, comfortably more than a busy day on TEST or LIVE.
# Surfaced via stderr if hit so the operator knows the window was
# truncated rather than the channel quietly being that empty.
_MAX_BACKFILL_BATCHES = 50


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


async def _gateway_loop(
    token: str,
    channel_id: int,
    buffer: Optional["TailBuffer"] = None,
    mention_map: Optional[dict] = None,
) -> None:
    """Stream message + edit + reaction events from the channel via
    a Discord Gateway WebSocket using a tester-bot token.

    Replaces ``_tail_loop``'s REST poll. Same buffer-and-stdout
    contract — every event is appended to ``buffer`` and printed
    using the same per-message format — but adds two event types
    REST polling can't observe:

    - **Edits.** ``MESSAGE_UPDATE`` events emit a fresh entry tagged
      ``[edited]``. The buffer keeps both the original and the
      edited version (no in-place mutation), so an inspector
      reader sees the timeline as it actually played out.
    - **Reactions.** ``MESSAGE_REACTION_ADD`` events emit a one-line
      ``@user reacted with <emoji> to <id>`` entry, useful for
      reading approval / acknowledgement signals that REST polling
      strips entirely.

    Requires the ``CLAUDE_TESTER_TOKEN`` bot's ``MESSAGE_CONTENT``
    privileged intent enabled in the Discord developer portal —
    without it, ``MESSAGE_CREATE`` / ``MESSAGE_UPDATE`` events
    arrive with empty content fields. ``GUILD_MESSAGE_REACTIONS``
    is non-privileged and works either way.
    """
    import discord  # type: ignore

    intents = discord.Intents.none()
    intents.guilds = True
    intents.guild_messages = True
    intents.guild_reactions = True
    intents.message_content = True

    client = discord.Client(intents=intents)

    print(
        f"[gateway streaming channel {channel_id} — Ctrl-C to stop]",
        file=sys.stderr,
    )

    @client.event
    async def on_ready() -> None:
        print(
            f"[gateway connected as {client.user}]",
            file=sys.stderr,
        )

    @client.event
    async def on_message(msg: "discord.Message") -> None:
        if msg.channel.id != channel_id:
            return
        # Build a Discord-REST-compatible dict so the existing
        # ``_make_buffer_entry`` and ``_format_message`` paths
        # don't have to learn discord.py's object model.
        raw = _discord_message_to_raw(msg)
        if buffer is not None:
            buffer.append(_make_buffer_entry(raw, mention_map=mention_map))
        for line in _format_message(raw, mention_map=mention_map):
            print(line)

    @client.event
    async def on_message_edit(
        before: "discord.Message", after: "discord.Message",
    ) -> None:
        if after.channel.id != channel_id:
            return
        raw = _discord_message_to_raw(after)
        # Tag the author so the reader can distinguish a new
        # message from an edit landing chronologically later.
        edited_author = f"{(raw.get('author') or {}).get('username', '?')} [edited]"
        raw = dict(raw)
        raw["author"] = {"username": edited_author}
        if buffer is not None:
            buffer.append(_make_buffer_entry(raw, mention_map=mention_map))
        for line in _format_message(raw, mention_map=mention_map):
            print(line)

    @client.event
    async def on_raw_reaction_add(
        payload: "discord.RawReactionActionEvent",
    ) -> None:
        if payload.channel_id != channel_id:
            return
        # Resolve the user — payload.member is set when the
        # event fires from a guild we share. Fall back to the
        # bare user id when it isn't.
        actor = (
            payload.member.display_name
            if payload.member is not None
            else f"user:{payload.user_id}"
        )
        emoji = str(payload.emoji)
        line = (
            f"## {datetime.now(timezone.utc).isoformat()} — "
            f"@{actor} reacted with {emoji} to msg {payload.message_id}"
        )
        if buffer is not None:
            buffer.append({
                "id": str(payload.message_id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "author": actor,
                "content": f"reacted with {emoji} to {payload.message_id}",
            })
        print(line)

    try:
        await client.start(token)
    except KeyboardInterrupt:
        await client.close()
        return


def _discord_message_to_raw(msg) -> dict:
    """Adapt a discord.py ``Message`` into the raw dict shape the
    REST helpers in this module already understand.

    Only the fields the formatters and buffer consumers actually
    read are populated. Embeds and attachments are passed through
    via the discord.py serializer so embed-rendering paths still
    work for bot replies that arrive over Gateway.
    """
    return {
        "id": str(msg.id),
        "timestamp": msg.created_at.isoformat() if msg.created_at else "",
        "author": {
            "username": msg.author.display_name or msg.author.name,
            "id": str(msg.author.id),
        },
        "content": msg.content or "",
        "embeds": [e.to_dict() for e in (msg.embeds or [])],
        "attachments": [
            {"url": a.url, "filename": a.filename}
            for a in (msg.attachments or [])
        ],
    }


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


def _parse_relative_delta(spec: str) -> timedelta:
    """Parse a ``\\d+[smhdw]`` spec into a positive ``timedelta``.

    Used for both ``--since-time``/``--until-time`` (subtract from
    ``now``) and ``--duration`` (length of a window). Case-insensitive
    on the unit letter. Raises ``ValueError`` if the spec doesn't
    match the relative format — callers can fall back to ISO parsing
    if they accept absolute timestamps too.
    """
    if not spec:
        raise ValueError("empty time spec")
    rel = _RELATIVE_TIME_RE.match(spec.strip())
    if not rel:
        raise ValueError(
            f"{spec!r} is not a relative time spec (``\\d+[smhdw]``)"
        )
    n, unit_letter = rel.groups()
    unit = _RELATIVE_UNITS[unit_letter.lower()]
    return timedelta(**{unit: int(n)})


def _parse_time_spec(spec: str, now: Optional[datetime] = None) -> datetime:
    """Parse a time spec into a UTC ``datetime``.

    Accepts:

    - **Relative**: ``\\d+[smhdw]`` (e.g. ``30m``, ``9h``, ``2d``,
      ``1w``) — subtracted from ``now`` (default ``datetime.now(tz=UTC)``).
      Case-insensitive.
    - **ISO 8601**: anything ``datetime.fromisoformat`` accepts,
      with ``Z`` suffix tolerated. Naive timestamps are interpreted
      as UTC (the bot's canonical time zone).

    Raises ``ValueError`` with a helpful message on garbage input
    so the CLI can surface a clear error.
    """
    if not spec:
        raise ValueError("empty time spec")
    now = now or datetime.now(tz=timezone.utc)

    try:
        return now - _parse_relative_delta(spec)
    except ValueError:
        pass  # fall through to ISO parsing

    # ISO 8601. Strip a trailing 'Z' (Python <3.11 fromisoformat
    # didn't accept it; we normalize for safety).
    iso = spec.strip()
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as e:
        raise ValueError(
            f"could not parse {spec!r} as a relative spec "
            f"(``\\d+[smhdw]``) or ISO 8601 timestamp: {e}"
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _datetime_to_snowflake(dt: datetime) -> int:
    """Convert a UTC datetime to a Discord snowflake (left-shifted
    millisecond timestamp). Used to synthesize ``before`` / ``after``
    bounds for time-range queries — the result is a synthetic
    snowflake (no internal bits), which Discord still accepts as a
    pivot for its ID-based filters.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ms = int(dt.timestamp() * 1000)
    return max(0, (ms - _DISCORD_EPOCH_MS) << 22)


async def _backfill_messages(
    client: DiscordRestClient,
    channel_id: int,
    since_dt: datetime,
    until_dt: Optional[datetime] = None,
) -> list[dict]:
    """Page backwards through a channel until we cover the full
    ``[since_dt, until_dt]`` window.

    Each call to ``get_messages`` returns up to 100 messages
    newest-first; we feed the oldest id of each batch back as
    ``before`` and stop when the oldest message in a batch is
    earlier than ``since_dt`` (the rest of that batch is still
    included; messages older than ``since_dt`` are filtered after).

    Returns chronological order (oldest → newest), filtered to the
    requested window. Capped at ``_MAX_BACKFILL_BATCHES`` pages —
    if the cap hits, prints a warning to stderr so the operator
    knows to narrow the window or expect a partial view.
    """
    until_snowflake = (
        _datetime_to_snowflake(until_dt) if until_dt is not None else None
    )
    collected: list[dict] = []
    before: Optional[int] = until_snowflake
    for batch_idx in range(_MAX_BACKFILL_BATCHES):
        batch = await client.get_messages(
            channel_id, before=before, limit=100,
        )
        if not batch:
            break
        collected.extend(batch)
        # Discord returns newest-first; the LAST entry is the oldest.
        oldest_in_batch = batch[-1]
        oldest_ts_str = oldest_in_batch.get("timestamp")
        if not oldest_ts_str:
            break
        try:
            oldest_dt = datetime.fromisoformat(oldest_ts_str.replace("Z", "+00:00"))
        except ValueError:
            break
        if oldest_dt <= since_dt:
            break
        before = int(oldest_in_batch["id"])
    else:
        print(
            f"[hit backfill cap of {_MAX_BACKFILL_BATCHES} batches "
            f"({_MAX_BACKFILL_BATCHES * 100} messages) — window may "
            f"be truncated; narrow --since-time/--until-time]",
            file=sys.stderr,
        )

    # Filter to the requested window and reverse to chronological.
    in_window: list[dict] = []
    for msg in collected:
        ts = msg.get("timestamp")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        if dt < since_dt:
            continue
        if until_dt is not None and dt > until_dt:
            continue
        in_window.append(msg)
    in_window.reverse()
    return in_window


def _format_range_header(
    game: dict, guild_names: dict[int, str],
    messages: list[dict], since_dt: datetime, until_dt: Optional[datetime],
) -> str:
    """Header for the time-range fetch — distinguishes from the
    standard ``--limit N`` initial fetch by surfacing the window."""
    lines = [_format_header(game, guild_names)]
    until_label = (
        until_dt.isoformat(timespec="seconds")
        if until_dt is not None else "now"
    )
    lines.append(
        f"*Range: {since_dt.isoformat(timespec='seconds')} → "
        f"{until_label} — {len(messages)} message(s), chronological.*"
    )
    lines.append("")
    return "\n".join(lines)


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

        # Range mode: ``--since-time`` (with an optional upper bound
        # via ``--until-time`` OR ``--duration``) paginates back
        # through history until the window is covered. Mutually
        # exclusive with ``--follow`` — the range query is a one-shot
        # historical scan, not a live tail.
        if args.since_time is not None:
            since_dt = _parse_time_spec(args.since_time)
            if args.until_time is not None:
                until_dt = _parse_time_spec(args.until_time)
            elif args.duration is not None:
                until_dt = since_dt + _parse_relative_delta(args.duration)
            else:
                until_dt = None
            messages = await _backfill_messages(
                client, game["channel_id"], since_dt, until_dt,
            )
            print(_format_range_header(
                game, guild_names, messages, since_dt, until_dt,
            ))
            for msg in messages:
                for line in _format_message(msg, mention_map=mention_map):
                    print(line)
            return 0

        messages = await client.get_messages(
            game["channel_id"], limit=args.limit,
        )
        print(_format_initial(game, guild_names, messages, mention_map=mention_map))

        if args.follow or args.gateway:
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
                if args.gateway:
                    # Gateway uses its own bot token (the tester
                    # bot's, same one ``bot_player`` uses) — distinct
                    # from the live bot whose token is in the DB.
                    # That separation is what lets us open a second
                    # Gateway alongside the live bot's session
                    # without tripping Discord's one-per-shard rule.
                    import os
                    gateway_token = os.environ.get("CLAUDE_TESTER_TOKEN")
                    if not gateway_token:
                        print(
                            "CLAUDE_TESTER_TOKEN env var not set. Set the tester-bot "
                            "token in .env under that name to use --gateway.",
                            file=sys.stderr,
                        )
                        return 1
                    await _gateway_loop(
                        gateway_token, game["channel_id"],
                        buffer=buffer, mention_map=mention_map,
                    )
                else:
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
        "--gateway",
        action="store_true",
        help=(
            "Stream events via Discord Gateway (WebSocket) instead of "
            "REST polling. Requires CLAUDE_TESTER_TOKEN env var (the "
            "tester bot's token, same one bot_player uses) and the "
            "MESSAGE_CONTENT privileged intent enabled in the dev "
            "portal. Adds visibility into edits and reactions that "
            "REST polling can't see. Implies --follow."
        ),
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
    parser.add_argument(
        "--since-time",
        type=str,
        default=None,
        metavar="TIME",
        help=(
            "Range fetch: paginate backwards through history until "
            "we cover everything from this time forward. Accepts "
            "relative ``\\d+[smhdw]`` (e.g. ``9h``, ``30m``, ``2d``) "
            "or ISO 8601 (``2026-04-25T16:00Z``). Mutually exclusive "
            "with ``--follow``; ignores ``--limit``."
        ),
    )
    parser.add_argument(
        "--until-time",
        type=str,
        default=None,
        metavar="TIME",
        help=(
            "Upper bound for ``--since-time`` window. Same format as "
            "``--since-time``. Useful for absolute ranges, e.g. "
            "``--since-time 2026-04-25T16:00Z --until-time 17:00Z``. "
            "Mutually exclusive with ``--duration``."
        ),
    )
    parser.add_argument(
        "--duration",
        type=str,
        default=None,
        metavar="LENGTH",
        help=(
            "Length of the ``--since-time`` window. Relative-format "
            "only (``\\d+[smhdw]``). Useful for relative windows, "
            "e.g. ``--since-time 9h --duration 1h`` for the hour "
            "between 9h and 8h ago. Mutually exclusive with "
            "``--until-time``."
        ),
    )
    args = parser.parse_args()

    if args.follow and args.since_time is not None:
        parser.error("--follow and --since-time are mutually exclusive.")
    if args.until_time is not None and args.since_time is None:
        parser.error("--until-time requires --since-time.")
    if args.duration is not None and args.since_time is None:
        parser.error("--duration requires --since-time.")
    if args.until_time is not None and args.duration is not None:
        parser.error("--until-time and --duration are mutually exclusive.")

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
