"""Edit a previously-posted patch notes message in place.

Reads the new content from a markdown file (default
``.patch-notes-scratch.md``, same as ``post_patch_notes``) and
``PATCH``-es each guild's most recent post made via
``post_patch_notes`` to that content. The "most recent post per
guild" is tracked in ``tools/.last_posted.json`` (gitignored)
written by ``post_patch_notes`` after every successful post.

Defaults to dry-run: prints a side-by-side of the existing
message content and the new content per target, doesn't fire.
``--post`` actually applies the edit.

Usage::

    python -m tools.edit_patch_notes TEST_DB_NAME            # dry-run
    python -m tools.edit_patch_notes TEST_DB_NAME --post     # actually edit
    python -m tools.edit_patch_notes TEST_DB_NAME --file fix.md
    python -m tools.edit_patch_notes TEST_DB_NAME --message-id 12345 --guild 678

``--message-id`` overrides the last-posted lookup (requires
``--guild`` so we know which channel to look in via the per-guild
config). Useful when editing a post made from a different machine
or before the last-posted log existed.

Bots can only edit messages they authored, so a 403 from Discord
on edit means the target message wasn't posted by this bot —
typically benign (someone deleted and reposted manually) but
worth noticing.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from tools import _post_log
from tools._common import DiscordRestClient, get_auth, live_db, use_db_env_var


_DEFAULT_FILE = Path(".patch-notes-scratch.md")
_DISCORD_MESSAGE_LIMIT = 2000


def _read_blurb(path: Path) -> str:
    """Same validation as ``post_patch_notes._read_blurb`` — kept
    duplicated rather than imported to keep the tools loosely
    coupled (each can be invoked / understood standalone)."""
    if not path.is_file():
        raise SystemExit(f"Patch-notes file not found: {path}")
    content = path.read_text(encoding="utf-8").strip()
    if not content:
        raise SystemExit(f"Patch-notes file is empty: {path}")
    if len(content) > _DISCORD_MESSAGE_LIMIT:
        raise SystemExit(
            f"Patch-notes content is {len(content)} chars; Discord's "
            f"per-message limit is {_DISCORD_MESSAGE_LIMIT}. Tighten "
            f"the blurb or split it across multiple posts manually."
        )
    return content


def _resolve_guild_meta(guild_id: int) -> dict | None:
    """Look up a guild's display name + updates channel id
    from the live ``servers`` collection. Returns ``None`` when
    the guild isn't configured for updates (the operator is
    trying to edit somewhere we can't post in the first
    place)."""
    doc = live_db().servers.find_one({"guild_id": guild_id})
    if not doc or "channels" not in doc:
        return None
    updates = doc["channels"].get("updates")
    if updates is None:
        return None
    return {
        "guild_id": guild_id,
        "name": doc.get("name") or f"<unnamed guild {guild_id}>",
        "channel_id": int(updates),
    }


def _resolve_targets(
    db_env_var: str,
    guild_filter: int | None,
    message_id_override: int | None,
) -> list[dict]:
    """Build the per-guild edit-target list. Two modes:

    1. **Default (no override):** read every entry from the
       per-env last-posted log (``db_env_var`` selects the
       file), filter to ``guild_filter`` if supplied. Each
       target carries the channel + message id we recorded at
       post time, plus the guild's display name.
    2. **Explicit ``--message-id`` (requires ``--guild``):**
       single target built from the override; channel id pulled
       from the live config so the operator only has to know
       the message id, not which channel it lived in.

    Per-env-key file isolation prevents cross-database
    contamination (a record from a ``LIVE_DB_NAME`` post is in
    a different file than ``TEST_DB_NAME``, so the wrong
    invocation can't pick it up).
    """
    if message_id_override is not None:
        if guild_filter is None:
            raise SystemExit(
                "--message-id requires --guild so we know which channel to "
                "edit in (per-guild config holds the channel id)."
            )
        meta = _resolve_guild_meta(guild_filter)
        if meta is None:
            raise SystemExit(
                f"Guild {guild_filter} has no updates channel "
                "configured; nothing to edit there."
            )
        meta["message_id"] = int(message_id_override)
        return [meta]

    targets = []
    for guild_id_str, entry in _post_log.get_all_last_posted(db_env_var).items():
        guild_id = int(guild_id_str)
        if guild_filter is not None and guild_id != guild_filter:
            continue
        meta = _resolve_guild_meta(guild_id)
        if meta is None:
            # Guild had a recorded post but its updates channel
            # was unset since — skip rather than crash.
            print(
                f"Skipping guild {guild_id}: no updates channel "
                "configured anymore. Re-run $config channel updates "
                "to restore.",
                file=sys.stderr,
            )
            continue
        meta["channel_id"] = int(entry["channel_id"])
        meta["message_id"] = int(entry["message_id"])
        targets.append(meta)
    return targets


async def _show_dry_run(targets: list[dict], new_content: str, token: str) -> int:
    """Fetch the existing content of each target message and
    print it alongside the new content. Same exit-code 0 as
    post's dry-run — caller decides whether to re-run with
    ``--post``."""
    print(f"== DRY RUN — would edit {len(targets)} message(s):\n")
    async with DiscordRestClient(token) as client:
        for t in targets:
            print(f"  • {t['name']} (guild_id={t['guild_id']})")
            print(f"    → channel_id={t['channel_id']} message_id={t['message_id']}")
            try:
                existing = await client.get_message(
                    t["channel_id"], t["message_id"],
                )
            except Exception as e:
                print(f"    (could not fetch existing content: {e})", file=sys.stderr)
                continue
            print()
            print("    Current content:")
            print("    " + "─" * 56)
            for line in (existing.get("content") or "").splitlines() or [""]:
                print(f"    {line}")
            print("    " + "─" * 56)
    print()
    print("== New content (verbatim):")
    print("─" * 60)
    print(new_content)
    print("─" * 60)
    print()
    print("Re-run with --post to apply the edit.")
    return 0


async def _edit_targets(targets: list[dict], new_content: str, token: str) -> int:
    """Apply the edit to each target. Per-target failures are
    logged but don't abort the rest (mirrors post's resilience).
    Returns the number of successful edits."""
    succeeded = 0
    async with DiscordRestClient(token) as client:
        for t in targets:
            try:
                await client.edit_message(
                    t["channel_id"], t["message_id"], new_content,
                )
            except Exception as e:
                print(f"  ✗ {t['name']} (guild_id={t['guild_id']}): {e}", file=sys.stderr)
                continue
            print(
                f"  ✓ {t['name']} (guild_id={t['guild_id']}) → "
                f"edited message_id={t['message_id']}"
            )
            succeeded += 1
    return succeeded


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
        "--post",
        action="store_true",
        help="Actually apply the edit. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=_DEFAULT_FILE,
        help=f"Path to the new patch-notes content (default: {_DEFAULT_FILE}).",
    )
    parser.add_argument(
        "--guild",
        type=int,
        default=None,
        help=(
            "Restrict editing to a single guild id (default: every guild "
            "with a recorded post in .last_posted.json). Required when "
            "--message-id is supplied."
        ),
    )
    parser.add_argument(
        "--message-id",
        type=int,
        default=None,
        help=(
            "Edit a specific message id instead of the last-posted one. "
            "Requires --guild. Useful when editing a post made from a "
            "different machine or before the last-posted log existed."
        ),
    )
    args = parser.parse_args()

    use_db_env_var(args.db_env_var)
    new_content = _read_blurb(args.file)
    targets = _resolve_targets(args.db_env_var, args.guild, args.message_id)

    if not targets:
        if args.guild is not None:
            print(
                f"No recorded post for guild {args.guild} (and no "
                "--message-id supplied). Either post first via "
                "tools.post_patch_notes, or pass --message-id <id>.",
                file=sys.stderr,
            )
        else:
            print(
                "No recorded posts to edit. Run tools.post_patch_notes "
                "first (its successful posts populate .last_posted.json), "
                "or pass --guild <id> --message-id <id> to target a "
                "specific message.",
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

    if not args.post:
        return asyncio.run(_show_dry_run(targets, new_content, token))

    print(f"== Editing {len(targets)} message(s):")
    succeeded = asyncio.run(_edit_targets(targets, new_content, token))
    print(f"\nDone — {succeeded}/{len(targets)} successful.")
    return 0 if succeeded == len(targets) else 2


if __name__ == "__main__":
    raise SystemExit(main())
