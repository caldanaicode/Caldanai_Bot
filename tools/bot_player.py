"""Claude-driven tester-bot player for the TEST guild's combat
channel. Sends commands via Discord REST (no Gateway session);
replies are read back via :mod:`tools.tail_peek`.

Why this tool exists
--------------------

To let an out-of-band driver (Claude, a scripted sweep, a
playtest automation) interact with the game like a real player
— enroll in combat, attack with specific targets, run
inspections — without spinning up a full discord.py client or
borrowing credentials from the live Caldanai bot. A dedicated
tester bot, scoped to the TEST guild only, keeps all activity
contained and fully revocable by removing the bot from the
guild or rotating the token.

Setup (one-time)
----------------

1. Register a second Discord application in the Developer Portal
   (name it something obvious like "Caldanai Tester"). Generate
   a bot token.
2. Invite that bot to the TEST guild only — ``Send Messages`` +
   ``Read Message History`` permissions are sufficient for combat
   commands.
3. Run normal onboarding for it in the TEST channel (``$join``
   etc.) so it has a Player character the game recognizes.
4. Drop the token in ``.env``::

       CLAUDE_TESTER_TOKEN=<bot-token-here>

   The file is already gitignored; don't commit.

Usage
-----

::

    python -m tools.bot_player send "$rip&tear leg.r"
    python -m tools.bot_player send "$look dragon"
    python -m tools.bot_player send "$pray"

Higher-level orchestration (fight-to-the-death loops, bestiary
sweeps) composes around ``send`` from a shell script, pairing
each send with a ``tail_peek TEST`` read to surface the bot's
response. Combat rounds are paced at ~60s on the live bot, so a
15-round fight takes ~15 minutes of real time regardless of how
fast this tool posts.

Scoping
-------

- ``CLAUDE_TESTER_TOKEN`` is the tester bot's token, not the
  live Caldanai bot's. The live bot's auth stays in MongoDB
  where the main app expects it.
- Target channel is resolved from ``TEST_DB_NAME``'s ``games``
  collection — whichever channel the test bot has been
  initialized in. If you run multiple test channels, use
  ``--guild <id>`` to narrow.
- No Gateway connection. One HTTP POST per send; clean exit.
  Safe to call repeatedly from scripts without bot lifecycle
  management.
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

from tools._common import DiscordRestClient, live_db, use_db_env_var


def _resolve_test_channel_id(guild_filter: Optional[int] = None) -> int:
    """Look up the TEST game's channel id from the test DB.

    Resolution order:

    1. ``BOT_PLAYER_CHANNEL_ID`` env var — when set, returned
       directly (skips DB lookup entirely). Workspace-pinning
       mode: bg Vael's launcher sets this so every no-flag
       ``bot_player send`` lands on her one-true channel without
       discovering the OOC engineering channel that shares her
       guild. Main-project workflows leave this unset and fall
       through to the DB lookup below.
    2. DB lookup against ``TEST_DB_NAME``'s ``games`` collection,
       filtered to exclude ``OOC_CHANNEL_ID`` when that env var is
       set. Most test setups have exactly one game; when multiple
       remain after the OOC exclusion the caller narrows with
       ``guild_filter``.

    Raises ``SystemExit`` when the env var is unset AND no
    matching game is found — usually means the bot has never
    been run in the test channel yet, so no game doc has been
    persisted.

    The OOC channel is reachable explicitly via the ``--ooc``
    flag or ``--channel-id``.
    """
    pinned = os.environ.get("BOT_PLAYER_CHANNEL_ID")
    if pinned:
        try:
            return int(pinned)
        except ValueError as e:
            raise SystemExit(
                f"BOT_PLAYER_CHANNEL_ID is not a valid integer: {pinned!r}"
            ) from e
    use_db_env_var("TEST_DB_NAME")
    query: dict = {"channel_id": {"$exists": True}}
    if guild_filter is not None:
        query["guild_id"] = guild_filter
    ooc_id_str = os.environ.get("OOC_CHANNEL_ID")
    if ooc_id_str:
        try:
            query["channel_id"] = {"$ne": int(ooc_id_str), "$exists": True}
        except ValueError:
            pass
    docs = list(live_db().games.find(query, {"channel_id": 1, "guild_id": 1}))
    if not docs:
        raise SystemExit(
            "No game found in TEST_DB_NAME.games. "
            "Run the bot once in the test channel to initialize a game doc."
        )
    if len(docs) > 1 and guild_filter is None:
        guilds = ", ".join(str(d.get("guild_id")) for d in docs)
        raise SystemExit(
            f"Multiple games found in TEST_DB_NAME.games ({guilds}). "
            f"Pass --guild <id> or --channel-id <id> to target a "
            f"specific channel, or set BOT_PLAYER_CHANNEL_ID in "
            f"the env to pin a default."
        )
    return int(docs[0]["channel_id"])


def _resolve_ooc_channel_id() -> int:
    """Return the OOC engineering channel id from ``OOC_CHANNEL_ID`` env."""
    raw = os.environ.get("OOC_CHANNEL_ID")
    if not raw:
        raise SystemExit(
            "OOC_CHANNEL_ID env var not set. Add the engineering "
            "playtest channel snowflake to .env as OOC_CHANNEL_ID "
            "before using --ooc."
        )
    try:
        return int(raw)
    except ValueError as e:
        raise SystemExit(
            f"OOC_CHANNEL_ID is not a valid integer: {raw!r}"
        ) from e


def _resolve_observations_channel_id() -> int:
    """Return the bg-Vael observations channel id from
    ``OBSERVATIONS_CHANNEL_ID`` env."""
    raw = os.environ.get("OBSERVATIONS_CHANNEL_ID")
    if not raw:
        raise SystemExit(
            "OBSERVATIONS_CHANNEL_ID env var not set. Add the "
            "observations channel snowflake to .env as "
            "OBSERVATIONS_CHANNEL_ID before using --obs."
        )
    try:
        return int(raw)
    except ValueError as e:
        raise SystemExit(
            f"OBSERVATIONS_CHANNEL_ID is not a valid integer: {raw!r}"
        ) from e


async def _post(
    content: str,
    guild_filter: Optional[int],
    channel_id_override: Optional[int] = None,
) -> dict:
    token = os.environ.get("CLAUDE_TESTER_TOKEN")
    if not token:
        raise SystemExit(
            "CLAUDE_TESTER_TOKEN env var not set. Drop the tester-bot "
            "token in .env under that name and try again."
        )
    if channel_id_override is not None:
        channel_id = channel_id_override
    else:
        channel_id = _resolve_test_channel_id(guild_filter)
    async with DiscordRestClient(token) as client:
        return await client.post_message(channel_id, content)


async def _react(
    message_id: int,
    emoji: str,
    guild_filter: Optional[int],
    channel_id_override: Optional[int] = None,
) -> str:
    """Toggle the tester bot's reaction on a message.

    Mirrors Discord's UI: if the bot already has this reaction on
    the message, it gets removed; otherwise it gets added. The
    caller doesn't need to track add-vs-remove state — useful for
    paging UIs ($help page-flip, $loadout selectors) where each
    interaction toggles the previous page's reaction off and adds
    the new page's reaction on.

    :return: ``"added"`` or ``"removed"`` describing the action.
    """
    token = os.environ.get("CLAUDE_TESTER_TOKEN")
    if not token:
        raise SystemExit(
            "CLAUDE_TESTER_TOKEN env var not set. Drop the tester-bot "
            "token in .env under that name and try again."
        )
    if channel_id_override is not None:
        channel_id = channel_id_override
    else:
        channel_id = _resolve_test_channel_id(guild_filter)
    async with DiscordRestClient(token) as client:
        return await client.toggle_reaction(channel_id, message_id, emoji)


_THREAD_SEPARATOR_RE = __import__("re").compile(r"^---\s*$", __import__("re").MULTILINE)


def _split_thread_file(text: str) -> "list[str]":
    """Split a thread file into messages on lines containing only
    ``---``. Strips surrounding whitespace from each chunk; drops
    empty chunks so a leading or trailing separator doesn't produce
    a phantom empty post.

    The separator must be a full line (``^---$``) — inline
    ``---`` inside a section (e.g. inside a Markdown horizontal
    rule embedded in a code block) is preserved.
    """
    chunks = _THREAD_SEPARATOR_RE.split(text)
    return [c.strip() for c in chunks if c.strip()]


async def _post_thread(
    messages: "list[str]",
    guild_filter: Optional[int],
    channel_id_override: Optional[int] = None,
    pacing_seconds: float = 0.6,
) -> "list[dict]":
    """Post a sequence of messages to the same channel with a brief
    inter-message pause so they land in order on Discord's side.

    Returns the list of posted message dicts (one per send) so the
    caller can echo IDs.
    """
    import asyncio as _asyncio
    posted: "list[dict]" = []
    for i, content in enumerate(messages):
        msg = await _post(content, guild_filter, channel_id_override)
        posted.append(msg)
        if i < len(messages) - 1:
            await _asyncio.sleep(pacing_seconds)
    return posted


async def _edit(
    message_id: int,
    content: str,
    guild_filter: Optional[int],
    channel_id_override: Optional[int] = None,
) -> dict:
    """PATCH the content of a previously-posted tester-bot message.

    Recovery path for posts mangled by shell-quoting (an
    unescaped ``$kill`` inside double-quotes evaporates before
    the tool sees it). Bots can only edit messages they
    authored, so this only works for tester-bot posts.
    """
    token = os.environ.get("CLAUDE_TESTER_TOKEN")
    if not token:
        raise SystemExit(
            "CLAUDE_TESTER_TOKEN env var not set. Drop the tester-bot "
            "token in .env under that name and try again."
        )
    if channel_id_override is not None:
        channel_id = channel_id_override
    else:
        channel_id = _resolve_test_channel_id(guild_filter)
    async with DiscordRestClient(token) as client:
        return await client.edit_message(channel_id, message_id, content)


def _is_workspace_mode() -> bool:
    """True when the running process is in a channel-pinned
    workspace (``BOT_PLAYER_CHANNEL_ID`` set in env). Triggers
    a minimal CLI surface: ``--ooc`` / ``--obs`` flags and the
    ``thread`` subcommand are not registered, so they don't
    appear in ``--help`` and can't be invoked. Keeps tester-bot
    operators inside their pinned channel without exposing
    engineering-side surfaces in their tool view.
    """
    return bool(os.environ.get("BOT_PLAYER_CHANNEL_ID"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    minimal = _is_workspace_mode()

    send_p = sub.add_parser(
        "send",
        help="Post a message to the TEST channel as the tester bot.",
    )
    send_p.add_argument(
        "content",
        help="Message content, e.g. '$rip&tear leg.r' or '$look dragon'.",
    )
    send_p.add_argument(
        "--guild", type=int, default=None,
        help="Restrict channel lookup to one guild id when "
             "multiple test guilds exist. Usually unnecessary.",
    )
    send_p.add_argument(
        "--channel-id", type=int, default=None,
        help="Post to a specific channel id, skipping the DB-based "
             "test-channel lookup. For posting to non-combat channels "
             "(e.g. a journal channel) the tester bot has access to.",
    )
    if not minimal:
        send_p.add_argument(
            "--ooc", action="store_true",
            help="Target the OOC engineering channel from the "
                 "OOC_CHANNEL_ID env var. Shortcut for "
                 "``--channel-id $OOC_CHANNEL_ID``.",
        )
        send_p.add_argument(
            "--obs", action="store_true",
            help="Target the observations channel from the "
                 "OBSERVATIONS_CHANNEL_ID env var. Shortcut for "
                 "``--channel-id $OBSERVATIONS_CHANNEL_ID``.",
        )

    react_p = sub.add_parser(
        "react",
        help="Toggle a reaction on a message in the TEST channel.",
    )
    react_p.add_argument(
        "message_id", type=int,
        help="Discord snowflake of the message to react to. Toggles "
             "the bot's reaction — calling twice with the same emoji "
             "removes the reaction. Mirrors Discord's UI behavior.",
    )
    react_p.add_argument(
        "emoji",
        help="Emoji to toggle. Single Unicode char (e.g. ❤️, 🔥, 💀) or "
             "custom-emoji name:id form (e.g. sword:12345).",
    )
    react_p.add_argument(
        "--guild", type=int, default=None,
        help="Restrict channel lookup to one guild id when "
             "multiple test guilds exist. Usually unnecessary.",
    )
    react_p.add_argument(
        "--channel-id", type=int, default=None,
        help="React in a specific channel id, skipping "
             "the DB-based test-channel lookup.",
    )
    if not minimal:
        react_p.add_argument(
            "--ooc", action="store_true",
            help="Target the OOC engineering channel from the "
                 "OOC_CHANNEL_ID env var.",
        )
        react_p.add_argument(
            "--obs", action="store_true",
            help="Target the observations channel from the "
                 "OBSERVATIONS_CHANNEL_ID env var.",
        )

    edit_p = sub.add_parser(
        "edit",
        help="Edit a previously-posted tester-bot message in place.",
    )
    edit_p.add_argument(
        "message_id", type=int,
        help="Discord snowflake of the message to edit. Bots can "
             "only edit messages they authored — passing another "
             "user's message id will yield a 403.",
    )
    edit_p.add_argument(
        "content",
        help="Replacement message content. Replaces the entire "
             "body — there's no diff/append mode.",
    )
    edit_p.add_argument(
        "--guild", type=int, default=None,
        help="Restrict channel lookup to one guild id when "
             "multiple test guilds exist. Usually unnecessary.",
    )
    edit_p.add_argument(
        "--channel-id", type=int, default=None,
        help="Edit a message in a specific channel id, skipping "
             "the DB-based test-channel lookup. Required when "
             "editing messages outside the test-combat channel.",
    )
    if not minimal:
        edit_p.add_argument(
            "--ooc", action="store_true",
            help="Target the OOC engineering channel from the "
                 "OOC_CHANNEL_ID env var.",
        )
        edit_p.add_argument(
            "--obs", action="store_true",
            help="Target the observations channel from the "
                 "OBSERVATIONS_CHANNEL_ID env var.",
        )

    if not minimal:
        thread_p = sub.add_parser(
            "thread",
            help=(
                "Post a sequence of messages from a markdown file, "
                "split on ``---`` separator lines. Each chunk becomes "
                "a separate Discord message with a small inter-message "
                "pause so they land in order."
            ),
        )
        thread_p.add_argument(
            "file",
            help=(
                "Path to a markdown file. Sections are separated by "
                "lines containing only ``---`` (line-anchored, so "
                "horizontal rules inside content are preserved). "
                "Empty leading/trailing chunks are dropped."
            ),
        )
        thread_p.add_argument(
            "--guild", type=int, default=None,
            help="Restrict channel lookup to one guild id when "
                 "multiple test guilds exist.",
        )
        thread_p.add_argument(
            "--channel-id", type=int, default=None,
            help="Post to a specific channel id, skipping the DB-based "
                 "test-channel lookup.",
        )
        thread_p.add_argument(
            "--ooc", action="store_true",
            help="Target the OOC engineering channel from "
                 "OOC_CHANNEL_ID env var.",
        )
        thread_p.add_argument(
            "--obs", action="store_true",
            help="Target the observations channel from "
                 "OBSERVATIONS_CHANNEL_ID env var.",
        )
        thread_p.add_argument(
            "--pacing-seconds", type=float, default=0.6,
            help=(
                "Sleep between messages so they land in order on "
                "Discord. Default: 0.6s. Set to 0 for no pacing."
            ),
        )
        thread_p.add_argument(
            "--dry-run", action="store_true",
            help=(
                "Print the resolved chunks (with separator markers) "
                "and exit without sending. Useful for verifying the "
                "split."
            ),
        )
        thread_p.add_argument(
            "--cleanup", action="store_true",
            help=(
                "Delete the source file after a successful post. "
                "Useful for unattended cron flows that build a "
                "temp markdown, post it, and shouldn't leave the "
                "scratch behind. No-op on dry-run."
            ),
        )

    args = ap.parse_args(argv)

    # Resolve --ooc / --obs shortcuts into channel_id BEFORE
    # dispatch so all three subcommands share the same logic.
    # Explicit --channel-id wins if it's also passed (last-write
    # semantics). --ooc and --obs are mutually exclusive — pick one.
    ooc = getattr(args, "ooc", False)
    obs = getattr(args, "obs", False)
    if ooc and obs:
        ap.error("--ooc and --obs are mutually exclusive")
    if args.channel_id is None:
        if ooc:
            args.channel_id = _resolve_ooc_channel_id()
        elif obs:
            args.channel_id = _resolve_observations_channel_id()

    if args.cmd == "send":
        msg = asyncio.run(_post(args.content, args.guild, args.channel_id))
        author = (msg.get("author") or {}).get("username", "?")
        print(
            f"posted id={msg['id']} as {author} "
            f"(channel={msg.get('channel_id')})"
        )
        return 0
    if args.cmd == "edit":
        msg = asyncio.run(
            _edit(args.message_id, args.content, args.guild, args.channel_id)
        )
        author = (msg.get("author") or {}).get("username", "?")
        print(
            f"edited id={msg['id']} as {author} "
            f"(channel={msg.get('channel_id')})"
        )
        return 0
    if args.cmd == "react":
        action = asyncio.run(
            _react(args.message_id, args.emoji, args.guild, args.channel_id)
        )
        print(
            f"{action} reaction {args.emoji} on id={args.message_id}"
        )
        return 0
    if args.cmd == "thread":
        from pathlib import Path as _Path
        text = _Path(args.file).read_text(encoding="utf-8")
        chunks = _split_thread_file(text)
        if not chunks:
            print(
                f"No messages parsed from {args.file} — file is "
                "empty or every chunk was whitespace.",
                file=sys.stderr,
            )
            return 1
        if args.dry_run:
            for i, c in enumerate(chunks, 1):
                print(f"--- chunk {i}/{len(chunks)} ({len(c)} chars) ---")
                print(c)
                print()
            return 0
        posted = asyncio.run(
            _post_thread(
                chunks, args.guild, args.channel_id,
                pacing_seconds=args.pacing_seconds,
            )
        )
        for i, msg in enumerate(posted, 1):
            print(
                f"posted {i}/{len(posted)} id={msg['id']} "
                f"(channel={msg.get('channel_id')})"
            )
        if getattr(args, "cleanup", False):
            try:
                _Path(args.file).unlink()
                print(f"cleaned up {args.file}")
            except OSError as e:
                print(
                    f"warning: cleanup of {args.file} failed: {e}",
                    file=sys.stderr,
                )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
