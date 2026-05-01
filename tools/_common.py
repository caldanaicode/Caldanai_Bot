"""Shared helpers for the ``tools/`` standalone scripts.

The Mongo database the tools target is selected per-invocation
by passing an env-var *name* as the first positional CLI
argument (default ``LIVE_DB_NAME``). The tool resolves that env
var to the actual DB name and the helpers below talk to it.
Tools always run locally, but the operator can freely point a
local invocation at the live DB for production tasks or at the
test DB for local-testing tasks — independent of whatever
``STAGE`` happens to be set to for the bot's local run.

Examples::

    python tools/post_patch_notes.py                  # live
    python tools/post_patch_notes.py LIVE_DB_NAME     # explicit, same as above
    python tools/post_patch_notes.py TEST_DB_NAME     # against local test DB

The bot token is pulled from whichever DB the operator
selected, mirroring how the bot itself reads it. No extra env
vars are required beyond what the bot already needs.

Tools should boot fast and stay independent of the bot's full
runtime — keep imports here narrow, no cog/asyncio-heavy
dependencies. Discord interactions are REST-only via the
:class:`DiscordRestClient` wrapper; the live bot's Gateway
connection is unaffected because Gateway and REST are
independent (REST has no single-connection restriction).
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

# Windows consoles default to a legacy codepage (cp1252) which
# mangles em-dashes and other non-latin1 glyphs in tool output.
# Python 3.7+ supports ``reconfigure(encoding=...)`` on the std
# streams; wrapped in a ``try/except`` because some runtimes
# (e.g. certain CI/container stdout streams) don't support it.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


# --------------------------------------------------------------------
# Per-env tooling state files
# --------------------------------------------------------------------
#
# Two tools persist local working state across runs: ``_post_log``
# (records each successful post so the edit tool can find it
# again) and ``check_ideas`` (cursor of last seen message id per
# guild). Both store one JSON file per DB-env-key — ``base_name``
# is the kind ("last_posted", "ideas_cursor"), ``db_env_var`` is
# the env-var name the operator passed at invocation. Filename
# scheme: ``tools/.<base_name>.<db_env_var>.json``.
#
# Filesystem-level isolation per env so cross-database
# contamination is structurally impossible (a ``LIVE_DB_NAME``
# record can't be picked up by a ``TEST_DB_NAME`` invocation —
# they live in different files).
#
# Gitignored via the glob ``tools/.<base_name>.*.json`` for each
# new ``base_name`` we add.

_STATE_DIR = Path(__file__).parent


# Shared ``tail_*`` environment shortnames. Operators pass ``LIVE``
# / ``TEST`` on the command line; tools map that to (env-var-name,
# default-inspector-port). The default ports are convention-only —
# overridable via ``--port`` on each tool — but sticking to them
# keeps "which env is this process tailing?" readable from
# ``ps``/``tasklist`` alone, because the positional arg is the
# authoritative tag.
TAIL_ENVS: "Dict[str, Tuple[str, int]]" = {
    "LIVE": ("LIVE_DB_NAME", 8765),
    "TEST": ("TEST_DB_NAME", 8766),
}


def resolve_tail_env(shortname: str) -> "Tuple[str, int]":
    """Map a ``LIVE`` / ``TEST`` shortname to ``(env_var, port)``.

    Case-insensitive. Raises :class:`SystemExit` with a clear
    message on an unknown shortname — better than a KeyError
    deep in a tool when the operator typos.
    """
    key = shortname.upper()
    if key not in TAIL_ENVS:
        raise SystemExit(
            f"Unknown tail env {shortname!r}. Valid: "
            f"{', '.join(TAIL_ENVS)}."
        )
    return TAIL_ENVS[key]


def state_file_path(base_name: str, db_env_var: str) -> Path:
    """Compute the per-env state-file path for ``base_name``."""
    return _STATE_DIR / f".{base_name}.{db_env_var}.json"


def load_state_file(base_name: str, db_env_var: str) -> dict:
    """Read a per-env JSON state file. Returns empty dict on
    missing or malformed file — degrade gracefully so partial
    state can't take down a tool run. Prints a stderr warning
    on malformed JSON so the operator at least knows it
    happened."""
    path = state_file_path(base_name, db_env_var)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(
            f"State file at {path} is malformed; treating as empty. "
            "Delete it manually if needed.",
            file=sys.stderr,
        )
        return {}


def save_state_file(base_name: str, db_env_var: str, data: dict) -> None:
    """Write a per-env JSON state file. Indented for human
    readability — operators occasionally poke at these files
    directly."""
    path = state_file_path(base_name, db_env_var)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")

import aiohttp
from pymongo import MongoClient
from pymongo.database import Database

from caldanai.environment import DB_CONNECTION, LIVE_DB_NAME


_DISCORD_API_BASE = "https://discord.com/api/v10"

# Discord caps a single message at 2000 characters. Tools that
# post user-authored prose (patch notes, journal entries) need a
# splitter for anything longer; see :func:`split_for_discord`.
DISCORD_MESSAGE_LIMIT = 2000


def split_for_discord(
    content: str,
    max_chars: int = DISCORD_MESSAGE_LIMIT,
    reserve_header: bool = False,
) -> list[str]:
    """Split ``content`` into Discord-sized chunks at line boundaries.

    Aims for roughly even chunk sizes (target = total / n where
    n = ceil(total / max_chars)) and snaps each chunk boundary
    to the nearest line ending so list/bullet structure is
    preserved across chunks.

    Single-message content (under ``max_chars``) returns a list of
    length 1, so callers can iterate uniformly.

    With ``reserve_header=True``, the lines from line 0 up to and
    including the first blank line are treated as a header that
    lands exclusively in chunk 1 — chunk 1's body budget is
    reduced accordingly. Used by ``post_patch_notes`` where the
    timestamp header must not repeat across continuation chunks.
    Defaults to False — the general case (e.g. journal entries)
    treats the whole input as body.

    Raises :class:`SystemExit` when a single chunk would still
    exceed ``max_chars`` after splitting at line boundaries (i.e.
    one line is longer than the limit on its own); the operator
    must shorten the offending line rather than silently posting
    a truncated message.
    """
    if len(content) <= max_chars:
        return [content]

    lines = content.split("\n")
    if reserve_header:
        try:
            blank_idx = next(i for i, line in enumerate(lines) if line == "")
            header_lines = lines[: blank_idx + 1]
            body_lines = lines[blank_idx + 1:]
        except StopIteration:
            # No blank-line separator found — treat all content as
            # body. Shouldn't happen with the standard timestamp
            # header but the splitter stays robust.
            header_lines = []
            body_lines = lines
    else:
        header_lines = []
        body_lines = lines

    header_block = "\n".join(header_lines)
    header_size = len(header_block) + (1 if header_block else 0)
    body_block = "\n".join(body_lines)
    body_size = len(body_block)

    # Pick n so that:
    #   - chunk 1 (header + body_target) fits in max_chars
    #   - chunks 2..n (body_target only) fit in max_chars
    # body_target = body_size / n. The two constraints reduce to
    # taking the larger of two ceil-divisions.
    by_total = (header_size + body_size + max_chars - 1) // max_chars
    body_room_first = max(max_chars - header_size, 1)
    by_first = (body_size + body_room_first - 1) // body_room_first
    n = max(by_total, by_first, 2)

    # Optimal-cut algorithm: precompute cumulative body-size at
    # every line boundary, then for each chunk boundary k in
    # 1..n-1, pick the line index whose cumulative size is closest
    # to k * body_size / n. This produces a globally balanced
    # split at line boundaries — flush-on-walk approaches drift
    # because they decide each cut locally and can't see ahead to
    # whether a future bullet will overshoot the target.
    cumulative: list[int] = [0]
    for line in body_lines:
        cumulative.append(cumulative[-1] + len(line) + 1)

    cuts: list[int] = []
    for k in range(1, n):
        ideal = k * body_size / n
        prev_cut = cuts[-1] if cuts else 0
        best_i = min(
            range(prev_cut + 1, len(cumulative)),
            key=lambda i: abs(cumulative[i] - ideal),
        )
        cuts.append(best_i)
    cuts.append(len(body_lines))

    chunks: list[str] = []
    start = 0
    for end in cuts:
        chunk_body = "\n".join(body_lines[start:end]).rstrip()
        if not chunks and header_block:
            chunks.append(f"{header_block}\n{chunk_body}")
        else:
            chunks.append(chunk_body)
        start = end

    for i, chunk in enumerate(chunks):
        if len(chunk) > max_chars:
            raise SystemExit(
                f"Discord-split chunk {i + 1}/{len(chunks)} is "
                f"{len(chunk)} chars after splitting at line "
                f"boundaries — still over the {max_chars}-char "
                f"limit. A single line exceeds the limit on its "
                f"own; tighten that line."
            )
    return chunks


_client: Optional[MongoClient] = None
_active_db_name: Optional[str] = None


def use_db_env_var(env_var_name: str) -> None:
    """Resolve ``env_var_name`` (e.g. ``"LIVE_DB_NAME"`` or
    ``"TEST_DB_NAME"``) and set it as the database the tools
    will talk to. Tools call this once at startup with whatever
    positional argument the operator passed.

    Raises ``SystemExit`` (with operator-friendly guidance) when
    the named env var isn't set — silent fallback would risk
    posting to the wrong place.

    Idempotent and safe to call after :func:`live_db` has
    already opened a client: the lazy client is closed and
    re-opened on the next call so the new name takes effect.
    """
    db_name = os.getenv(env_var_name)
    if not db_name:
        print(
            f"Env var {env_var_name!r} is not set. "
            f"Add it to your .env (e.g. {env_var_name}=caldanaiDB) "
            "before running this tool.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    global _active_db_name, _client
    _active_db_name = db_name
    if _client is not None:
        _client.close()
        _client = None


def live_db() -> Database:
    """Return the Mongo database the tools should talk to.
    Lazily opens a single ``MongoClient`` per process (PyMongo's
    recommended pattern) and reuses it across helper calls.

    Selection comes from the most recent :func:`use_db_env_var`
    call; if a tool didn't call it (e.g. an interactive REPL
    session), falls back to :data:`LIVE_DB_NAME` from the env
    so direct usage still works without ceremony.

    Tools that want to reach into collections beyond what
    ``get_auth`` / ``get_guild_channels`` cover can use this
    directly — e.g. ``live_db().games.find_one(...)`` for a
    one-off lookup.
    """
    global _client
    if _client is None:
        _client = MongoClient(DB_CONNECTION)
    return _client[_active_db_name or LIVE_DB_NAME]


def get_auth() -> dict:
    """Return the auth document from the live DB. Includes the bot
    ``TOKEN`` that tools use to call the Discord API. Raises
    ``RuntimeError`` when no auth doc exists, since every tool
    needs the token to function and silently returning ``None``
    would surface as a confusing AttributeError downstream."""
    auth = live_db().auth.find_one()
    if auth is None:
        raise RuntimeError(
            f"No auth document found in live database {LIVE_DB_NAME!r}. "
            "Tools require the bot token to authenticate to Discord."
        )
    return auth


def get_guild_channels(guild_id: int) -> dict:
    """Return the per-guild channel registry from the live
    ``servers`` collection (e.g. ``{"updates": 123,
    "ideas": 456}``). Empty dict when the guild isn't configured
    or no server document exists yet — callers can ``.get(key)``
    without pre-checking."""
    server = live_db().servers.find_one({"guild_id": guild_id})
    if not server:
        return {}
    return dict(server.get("channels") or {})


def resolve_channel_id(guild_id: int, key: str) -> int:
    """Look up a single channel id by key (e.g. ``"updates"``
    or ``"ideas"``) for ``guild_id``. Raises ``RuntimeError``
    with a guidance message when the channel isn't configured —
    tools want to fail fast and tell the operator how to fix it
    rather than silently no-op."""
    channels = get_guild_channels(guild_id)
    channel_id = channels.get(key)
    if channel_id is None:
        raise RuntimeError(
            f"Guild {guild_id} has no {key!r} channel configured. "
            f"Set it via Discord: ``$config {key}_channel <#mention>``."
        )
    return int(channel_id)


class DiscordRestClient:
    """Minimal Discord REST client for the tools.

    Just enough for the two operations we need today: posting a
    message into a channel, and fetching recent messages from a
    channel for the cursor-based ideas-channel read. Both are
    plain HTTP calls against the v10 API with the bot token in
    the ``Authorization`` header.

    Doesn't open a Gateway connection. Multiple instances of
    this client (running concurrently with the live bot's
    Gateway) coexist without conflict — Discord's
    one-connection-per-shard rule applies to Gateway only;
    REST has no such restriction.

    Usage::

        async with DiscordRestClient(token) as client:
            await client.post_message(channel_id, "hello")
            messages = await client.get_messages(channel_id, after=cursor)
    """

    def __init__(self, token: str):
        self._token = token
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "DiscordRestClient":
        self._session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bot {self._token}",
                "User-Agent": "CaldanaiTools (tools/, +https://github.com/caldanaicode/Caldanai_Bot)",
            },
        )
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def post_message(self, channel_id: int, content: str) -> dict:
        """POST ``content`` to a channel. Returns the created
        message object as Discord renders it (id, timestamp,
        content, etc.). Raises on non-2xx via ``raise_for_status``
        — the caller decides whether to retry; rate-limit
        handling is intentionally absent because tool volumes
        are low (1–2 calls per invocation typically)."""
        url = f"{_DISCORD_API_BASE}/channels/{channel_id}/messages"
        async with self._session.post(url, json={"content": content}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def edit_message(
        self,
        channel_id: int,
        message_id: int,
        content: str,
    ) -> dict:
        """PATCH the content of a message we previously posted.
        Bots can only edit their own messages — Discord rejects
        edits of other authors' content with a 403.

        Returns the updated message object."""
        url = f"{_DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        async with self._session.patch(url, json={"content": content}) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_message(self, channel_id: int, message_id: int) -> dict:
        """GET a single message by id from a channel. Used by the
        edit tool's dry-run to show the operator what content
        will be replaced."""
        url = f"{_DISCORD_API_BASE}/channels/{channel_id}/messages/{message_id}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_channel(self, channel_id: int) -> dict:
        """GET a channel object by id. Returns the raw Discord
        channel payload — ``name``, ``type``, ``parent_id`` for
        threads, etc. Used by the tail tool to render a friendly
        picker of live games."""
        url = f"{_DISCORD_API_BASE}/channels/{channel_id}"
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_messages(
        self,
        channel_id: int,
        after: Optional[int] = None,
        before: Optional[int] = None,
        limit: int = 50,
    ) -> list:
        """GET recent messages from a channel.

        :param after: Discord message snowflake — only messages
            newer than this id are returned. ``None`` (the
            default) returns the most recent ``limit`` messages
            (when ``before`` is also ``None``).
        :param before: Discord message snowflake — only messages
            older than this id are returned. Used by callers
            paginating backwards through history (combine with
            ``limit=100`` and feed the oldest-id-of-batch back as
            ``before`` for the next call).
        :param limit: 1–100 per page. Single-page only; callers
            paginate manually if they need more.

        Returns the raw Discord message-object list. Discord
        returns messages newest-first within the page; callers
        usually want to reverse for chronological output.
        """
        url = f"{_DISCORD_API_BASE}/channels/{channel_id}/messages"
        params: dict = {"limit": min(max(limit, 1), 100)}
        if after is not None:
            params["after"] = str(after)
        if before is not None:
            params["before"] = str(before)
        async with self._session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json()
