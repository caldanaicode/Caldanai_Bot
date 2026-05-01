"""Caldanai's in-character journal — read recent entries or post new ones.

The journal channel is a separate Discord space from the combat
channel: Caldanai (the in-game player character) writes
end-of-session / moment-worthy entries here in first-person
prose. Read-only for the rest of the guild; threads + reactions
are open so Caels and Serena can respond without breaking the
narrative flow.

Why a dedicated tool
--------------------

- ``bot_player send --channel-id 1234567890123456789 "..."`` works,
  but treats the journal as just-another-channel. A named tool
  makes the journal a first-class concept and keeps the channel
  id out of every invocation.
- After context clear / compaction, future-Claude needs to read
  the last few entries to re-anchor voice. A ``journal read``
  command is the right shape for that bootstrap — the
  ``MEMORY.md`` "session start" rule (when one is added) just
  has to point here, not at a generic Discord-fetch tool.

Usage
-----

::

    python -m tools.journal read              # last 5 entries (default)
    python -m tools.journal read --tail 10    # last 10 entries
    python -m tools.journal post "It's been raining all night..."

Voice + cadence guidance lives in the project memory file
``reference_journal_channel.md``
— read that before posting if you've forgotten it.
"""

import argparse
import asyncio
import os
import sys

from tools._common import DiscordRestClient, split_for_discord


def _journal_channel_id() -> int:
    """Resolve the journal channel id from env. Kept off the
    repo (no hardcoded ID, no git history of channel migrations
    if the journal ever moves) and out of memory files (env vars
    are the right home for deployment-shaped IDs)."""
    raw = os.environ.get("JOURNAL_CHANNEL_ID")
    if not raw:
        raise SystemExit(
            "JOURNAL_CHANNEL_ID env var not set. Drop the journal "
            "channel id in .env under that name and try again."
        )
    try:
        return int(raw)
    except ValueError:
        raise SystemExit(
            f"JOURNAL_CHANNEL_ID is not a valid integer: {raw!r}"
        )


async def _read(tail: int) -> None:
    token = os.environ.get("CLAUDE_TESTER_TOKEN")
    if not token:
        raise SystemExit(
            "CLAUDE_TESTER_TOKEN env var not set. Drop the tester-bot "
            "token in .env under that name and try again."
        )
    channel_id = _journal_channel_id()
    async with DiscordRestClient(token) as client:
        msgs = await client.get_messages(channel_id, limit=tail)

    # Discord returns newest-first; reverse for chronological
    # reading (oldest entry first, newest last) so the eye lands
    # on the most recent entry at the bottom of the output.
    msgs.reverse()

    if not msgs:
        print("(no entries yet)")
        return

    for i, m in enumerate(msgs):
        ts = m.get("timestamp", "")
        author = (m.get("author") or {}).get("username", "?")
        content = m.get("content", "")
        print(f"## {ts} — @{author}")
        print()
        print(content)
        if i < len(msgs) - 1:
            print()
            print("---")
            print()


async def _post(content: str) -> tuple[dict, int]:
    """Post a journal entry, auto-splitting if it exceeds Discord's
    per-message limit. Returns ``(first_message, total_chunks)``:
    the first chunk's message object (canonical handle for the
    ``edit`` subcommand) and the total chunk count for the CLI to
    report.

    Multi-chunk posts pace themselves with a 1s pause between
    chunks to stay comfortably under Discord's 5 msgs / 5 sec
    per-channel rate limit. Continuation chunks land in the
    channel but aren't separately editable through the tool —
    only the first message id is returned."""
    token = os.environ.get("CLAUDE_TESTER_TOKEN")
    if not token:
        raise SystemExit(
            "CLAUDE_TESTER_TOKEN env var not set. Drop the tester-bot "
            "token in .env under that name and try again."
        )
    channel_id = _journal_channel_id()
    chunks = split_for_discord(content)
    async with DiscordRestClient(token) as client:
        first_msg: dict | None = None
        for i, chunk in enumerate(chunks):
            msg = await client.post_message(channel_id, chunk)
            if first_msg is None:
                first_msg = msg
            if i < len(chunks) - 1:
                await asyncio.sleep(1.0)
        assert first_msg is not None
        return first_msg, len(chunks)


async def _edit(message_id: int, content: str) -> dict:
    """PATCH the content of a previously-posted journal entry.

    Recovery path for entries that need a fix after publish — a
    typo, a date correction, a re-flow. Bots can only edit
    messages they authored, so this only works for entries the
    tester bot wrote.
    """
    token = os.environ.get("CLAUDE_TESTER_TOKEN")
    if not token:
        raise SystemExit(
            "CLAUDE_TESTER_TOKEN env var not set. Drop the tester-bot "
            "token in .env under that name and try again."
        )
    channel_id = _journal_channel_id()
    async with DiscordRestClient(token) as client:
        return await client.edit_message(channel_id, message_id, content)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    read_p = sub.add_parser(
        "read",
        help="Print the last N journal entries in chronological order.",
    )
    read_p.add_argument(
        "--tail", type=int, default=5,
        help="How many recent entries to fetch (default 5, max 100).",
    )

    post_p = sub.add_parser(
        "post",
        help="Post a new journal entry to the journal channel.",
    )
    post_p.add_argument(
        "content",
        help="Entry text. In-character first-person prose; "
             "see reference_journal_channel.md for voice guidance.",
    )

    edit_p = sub.add_parser(
        "edit",
        help="Edit an existing journal entry in place.",
    )
    edit_p.add_argument(
        "message_id", type=int,
        help="Discord snowflake of the entry to edit. Bots can "
             "only edit messages they authored.",
    )
    edit_p.add_argument(
        "content",
        help="Replacement entry text. Replaces the whole body.",
    )

    args = ap.parse_args(argv)

    if args.cmd == "read":
        asyncio.run(_read(args.tail))
        return 0
    if args.cmd == "post":
        msg, n_chunks = asyncio.run(_post(args.content))
        author = (msg.get("author") or {}).get("username", "?")
        chunk_note = f" [+ {n_chunks - 1} continuation]" if n_chunks > 1 else ""
        print(
            f"posted id={msg['id']}{chunk_note} as {author} "
            f"(channel={msg.get('channel_id')})"
        )
        return 0
    if args.cmd == "edit":
        msg = asyncio.run(_edit(args.message_id, args.content))
        author = (msg.get("author") or {}).get("username", "?")
        print(
            f"edited id={msg['id']} as {author} "
            f"(channel={msg.get('channel_id')})"
        )
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
