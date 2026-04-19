"""Fetch new messages from each guild's registered ``ideas``
channel (set via ``$config ideas_channel <#mention>``) since the
last successful run, and print them in a markdown format
optimized for paste-back into a planning conversation.

Cursor state is per-guild in
``tools/.ideas_cursor.<DB_ENV_VAR>.json`` (gitignored, one file
per database env so a LIVE check and a TEST check for the same
guild can never share cursor state — they reference different
Discord channels via different DB-stored config). First run
for a guild has no cursor, so it pulls the most recent
``--limit`` messages and seeds the cursor; later runs pull only
what's new.

Usage::

    python -m tools.check_ideas TEST_DB_NAME             # incremental
    python -m tools.check_ideas TEST_DB_NAME --limit 100 # first-run window
    python -m tools.check_ideas TEST_DB_NAME --reset     # clear cursor; next run re-seeds
    python -m tools.check_ideas TEST_DB_NAME --guild 123 # restrict to one guild

The output is plain markdown — header per guild, sub-header per
message with timestamp + author, body quoted verbatim. Designed
so a follow-up planning conversation can be primed by pasting
the output without needing summarization.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from tools._common import (
    DiscordRestClient,
    get_auth,
    live_db,
    load_state_file,
    save_state_file,
    state_file_path,
    use_db_env_var,
)


_CURSOR_BASE = "ideas_cursor"
_DEFAULT_FIRST_RUN_LIMIT = 50


def _cursor_path(db_env_var: str) -> Path:
    """Thin shim over :func:`tools._common.state_file_path`
    pinning the ``ideas_cursor`` base name. Kept as a local
    function so call sites and tests don't have to repeat the
    base-name string."""
    return state_file_path(_CURSOR_BASE, db_env_var)


def _load_cursor(db_env_var: str) -> dict:
    """Per-env cursor read. Delegates to the shared state-file
    helper; returns empty dict on missing / malformed file
    (helper logs the warning)."""
    return load_state_file(_CURSOR_BASE, db_env_var)


def _save_cursor(db_env_var: str, cursor: dict) -> None:
    save_state_file(_CURSOR_BASE, db_env_var, cursor)


def _find_ideas_targets(guild_filter: int | None) -> list[dict]:
    """Return per-guild target dicts for guilds with an ideas
    channel configured. Same shape as the updates-channel
    targeting in :mod:`post_patch_notes`."""
    query: dict = {"channels.ideas": {"$exists": True}}
    if guild_filter is not None:
        query["guild_id"] = guild_filter
    targets = []
    for doc in live_db().servers.find(query):
        targets.append({
            "guild_id": doc["guild_id"],
            "name": doc.get("name") or f"<unnamed guild {doc['guild_id']}>",
            "channel_id": int(doc["channels"]["ideas"]),
        })
    return targets


def _format_messages(target: dict, messages: list[dict]) -> str:
    """Render a guild's batch of new messages as planning-ready
    markdown. Newest-first from Discord is reversed to
    chronological so a reader follows the conversation in order.

    Empty content (embeds-only, attachments-only) renders with a
    placeholder so the message isn't silently dropped — the
    operator can investigate in Discord if needed.
    """
    lines = [f"# Ideas channel — {target['name']} (guild {target['guild_id']})"]
    if not messages:
        lines.append("")
        lines.append("*No new messages since last check.*")
        return "\n".join(lines)

    lines.append(f"*{len(messages)} new message(s).*")
    lines.append("")

    # Discord returns newest-first; reverse for chronological reading.
    for msg in reversed(messages):
        author = msg.get("author") or {}
        # Prefer global_name (Discord's modern display name) then
        # username; fall back to "<unknown>" so a malformed payload
        # doesn't crash the formatter.
        author_name = (
            author.get("global_name")
            or author.get("username")
            or "<unknown>"
        )
        timestamp = msg.get("timestamp", "<no timestamp>")
        content = (msg.get("content") or "").strip()
        lines.append(f"## {timestamp} — @{author_name}")
        if content:
            for body_line in content.splitlines():
                lines.append(f"> {body_line}")
        else:
            lines.append("> *(no text content — likely an embed or attachment; check Discord)*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


async def _fetch_for_target(
    client: DiscordRestClient,
    target: dict,
    cursor_entry: dict | None,
    first_run_limit: int,
) -> tuple[list[dict], int | None]:
    """Pull new messages for a single target. Returns
    ``(messages, new_last_id)``. Discord caps ``limit`` at 100
    per request; we don't paginate further today (a 100-message
    backlog between checks already means the operator should
    just go look in Discord)."""
    after = cursor_entry.get("last_message_id") if cursor_entry else None
    limit = 100 if after is not None else first_run_limit
    messages = await client.get_messages(
        target["channel_id"], after=after, limit=limit,
    )
    if not messages:
        return [], None
    # Discord returns newest-first; the new cursor is the newest id.
    newest_id = max(int(m["id"]) for m in messages)
    return messages, newest_id


async def _run(targets: list[dict], cursor: dict, first_run_limit: int, token: str) -> tuple[list[str], dict]:
    """Run the fetch loop. Returns the formatted output blocks
    (one per target) and the updated cursor dict."""
    blocks: list[str] = []
    new_cursor = dict(cursor)
    async with DiscordRestClient(token) as client:
        for target in targets:
            guild_key = str(target["guild_id"])
            cursor_entry = cursor.get(guild_key)
            try:
                messages, newest_id = await _fetch_for_target(
                    client, target, cursor_entry, first_run_limit,
                )
            except Exception as e:
                print(
                    f"Failed to fetch from {target['name']} "
                    f"(guild_id={target['guild_id']}): {e}",
                    file=sys.stderr,
                )
                continue
            blocks.append(_format_messages(target, messages))
            if newest_id is not None:
                new_cursor[guild_key] = {
                    "channel_id": target["channel_id"],
                    "last_message_id": newest_id,
                }
    return blocks, new_cursor


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "db_env_var",
        nargs="?",
        default="LIVE_DB_NAME",
        help=(
            "Name of the env var holding the Mongo DB name to target "
            "(default: LIVE_DB_NAME). Use TEST_DB_NAME to point at a "
            "local test setup."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear cursor before running. Next run will seed from --limit.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=_DEFAULT_FIRST_RUN_LIMIT,
        help=(
            f"Message count for first-run / post-reset seeding "
            f"(default: {_DEFAULT_FIRST_RUN_LIMIT}). Capped at 100 by Discord."
        ),
    )
    parser.add_argument(
        "--guild",
        type=int,
        default=None,
        help="Restrict to one guild id (default: every guild with an ideas channel).",
    )
    args = parser.parse_args()

    use_db_env_var(args.db_env_var)

    if args.reset:
        path = _cursor_path(args.db_env_var)
        if path.is_file():
            path.unlink()
            print(f"Cleared cursor at {path}.", file=sys.stderr)

    targets = _find_ideas_targets(args.guild)
    if not targets:
        scope = f" matching guild_id={args.guild}" if args.guild is not None else ""
        print(
            f"No guilds with an ideas channel configured{scope}. "
            "Set one via Discord: $config ideas_channel <#mention>",
            file=sys.stderr,
        )
        return 1

    auth = get_auth()
    token = auth.get("TOKEN")
    if not token:
        print(
            "Auth document on the live DB has no TOKEN field — "
            "tools can't authenticate to Discord.",
            file=sys.stderr,
        )
        return 1

    cursor = _load_cursor(args.db_env_var)
    blocks, new_cursor = asyncio.run(_run(targets, cursor, args.limit, token))

    for block in blocks:
        print(block)

    _save_cursor(args.db_env_var, new_cursor)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
