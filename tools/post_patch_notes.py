"""Post the contents of a patch-notes markdown file to every
guild that has registered an ``updates`` channel via
``$config channel updates <#mention>``.

Defaults to ``--dry-run`` — prints what *would* be posted and to
which channels, without actually firing. Re-run with ``--post``
to actually publish.

Usage::

    python tools/post_patch_notes.py                 # dry-run, default file
    python tools/post_patch_notes.py --post          # actually post
    python tools/post_patch_notes.py --file path.md  # custom source file
    python tools/post_patch_notes.py --guild 123     # restrict to one guild

Source file defaults to ``.patch-notes-scratch.md`` in the
current working directory — the same file the pre-commit ritual
writes to.
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
    """Read and lightly validate the blurb file. Refuses an empty
    file (almost certainly a mistake) and warns when the content
    exceeds Discord's per-message character limit — splitting is
    out of scope for this tool today; the operator should tighten
    the blurb or split manually."""
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


def _find_announcement_targets(guild_filter: int | None) -> list[dict]:
    """Return the list of guilds to post to. Each entry is a dict
    with ``guild_id``, ``name``, and ``channel_id``. A guild is a
    target iff it has ``channels.updates`` configured —
    that's the opt-in. ``guild_filter``, when supplied, narrows
    the result to a single guild id."""
    query: dict = {"channels.updates": {"$exists": True}}
    if guild_filter is not None:
        query["guild_id"] = guild_filter
    targets = []
    for doc in live_db().servers.find(query):
        targets.append({
            "guild_id": doc["guild_id"],
            "name": doc.get("name") or f"<unnamed guild {doc['guild_id']}>",
            "channel_id": int(doc["channels"]["updates"]),
        })
    return targets


def _print_dry_run(content: str, targets: list[dict]) -> None:
    print(f"== DRY RUN — would post to {len(targets)} guild(s):\n")
    for t in targets:
        print(f"  • {t['name']} (guild_id={t['guild_id']})")
        print(f"    → channel_id={t['channel_id']}")
    print()
    print("== Content (verbatim):")
    print("─" * 60)
    print(content)
    print("─" * 60)
    print()
    print("Re-run with --post to actually publish.")


async def _post_to_targets(
    content: str, targets: list[dict], token: str, db_env_var: str,
) -> int:
    """Post ``content`` to each target's updates channel.
    Returns the number of successful posts. Prints per-target
    success/failure inline so a partial failure is visible
    immediately. One failed guild doesn't abort the rest.

    Each successful post is recorded via :mod:`_post_log` keyed
    by ``db_env_var`` so ``edit_patch_notes`` can find the
    message id later without needing to scan the channel — and
    can't accidentally pick up a record posted via a different
    database (live vs. test isolation)."""
    succeeded = 0
    async with DiscordRestClient(token) as client:
        for t in targets:
            try:
                msg = await client.post_message(t["channel_id"], content)
            except Exception as e:
                print(f"  ✗ {t['name']} (guild_id={t['guild_id']}): {e}", file=sys.stderr)
                continue
            message_id = msg.get("id")
            _post_log.record_post(
                db_env_var, t["guild_id"], t["channel_id"], int(message_id),
            )
            print(f"  ✓ {t['name']} (guild_id={t['guild_id']}) → message_id={message_id}")
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
        help="Actually post to Discord. Without this flag, runs in dry-run mode.",
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=_DEFAULT_FILE,
        help=f"Path to the patch-notes file (default: {_DEFAULT_FILE}).",
    )
    parser.add_argument(
        "--guild",
        type=int,
        default=None,
        help="Restrict posting to a single guild id (default: every opted-in guild).",
    )
    args = parser.parse_args()

    use_db_env_var(args.db_env_var)
    content = _read_blurb(args.file)
    targets = _find_announcement_targets(args.guild)

    if not targets:
        scope = f" matching guild_id={args.guild}" if args.guild is not None else ""
        print(
            f"No guilds with an updates channel configured{scope}. "
            "Set one via Discord: $config channel updates <#mention>",
            file=sys.stderr,
        )
        return 1

    if not args.post:
        _print_dry_run(content, targets)
        return 0

    auth = get_auth()
    token = auth.get("TOKEN")
    if not token:
        print(
            "Auth document on the live DB has no TOKEN field — "
            "tools can't authenticate to Discord.",
            file=sys.stderr,
        )
        return 1

    print(f"== Posting to {len(targets)} guild(s):")
    succeeded = asyncio.run(
        _post_to_targets(content, targets, token, args.db_env_var),
    )
    print(f"\nDone — {succeeded}/{len(targets)} successful.")
    return 0 if succeeded == len(targets) else 2


if __name__ == "__main__":
    raise SystemExit(main())
