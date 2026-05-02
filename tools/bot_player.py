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

    Queries ``TEST_DB_NAME``'s ``games`` collection. Most test
    setups have exactly one game; when multiple exist the caller
    narrows with ``guild_filter``. Raises ``SystemExit`` when no
    matching game is found — usually means the bot has never
    been run in the test channel yet, so no game doc has been
    persisted.
    """
    use_db_env_var("TEST_DB_NAME")
    query: dict = {"channel_id": {"$exists": True}}
    if guild_filter is not None:
        query["guild_id"] = guild_filter
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
            f"Pass --guild <id> to disambiguate."
        )
    return int(docs[0]["channel_id"])


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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

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

    args = ap.parse_args(argv)

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
    return 1


if __name__ == "__main__":
    sys.exit(main())
