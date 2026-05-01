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
import datetime as _dt
import re
import sys
from pathlib import Path

from tools import _post_log
from tools._common import (
    DiscordRestClient,
    get_auth,
    live_db,
    split_for_discord,
    use_db_env_var,
)


_DEFAULT_FILE = Path(".patch-notes-scratch.md")

# Match a leading ``**Patch notes — YYYY-MM-DD HH:MM UTC**`` header
# (and trailing blank line) so a legacy scratch file with a stale
# timestamp gets its header replaced rather than stacked.
_LEGACY_HEADER_RE = re.compile(
    r"^\*\*Patch notes — \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\*\*\s*\n+",
)


def _prepend_current_timestamp(body: str) -> str:
    """Prepend a fresh ``**Patch notes — YYYY-MM-DD HH:MM UTC**``
    header to ``body``, stripping any pre-existing timestamp header
    so a re-read of a legacy file doesn't double-stamp.

    The timestamp is computed at read time (effectively the moment
    of the dry-run / post invocation) so the scratch file can be
    body-only and the operator never has to type the current UTC
    by hand. Drift between dry-run and the subsequent ``--post``
    is single-digit seconds in practice, fine for player-facing
    notes."""
    stripped = _LEGACY_HEADER_RE.sub("", body, count=1)
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"**Patch notes — {stamp}**\n\n{stripped}"


def _read_blurb(path: Path) -> str:
    """Read and lightly validate the blurb file. Refuses an empty
    file (almost certainly a mistake). Oversize content is no
    longer rejected here — :func:`_split_for_discord` chunks it
    into multiple Discord messages as needed.

    Auto-prepends a current-UTC ``**Patch notes — ... UTC**`` header
    via :func:`_prepend_current_timestamp` so the scratch file is
    body-only."""
    if not path.is_file():
        raise SystemExit(f"Patch-notes file not found: {path}")
    body = path.read_text(encoding="utf-8").strip()
    if not body:
        raise SystemExit(f"Patch-notes file is empty: {path}")
    return _prepend_current_timestamp(body)


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


def _print_dry_run(chunks: list[str], targets: list[dict]) -> None:
    n = len(chunks)
    plural = "s" if n > 1 else ""
    print(f"== DRY RUN — would post {n} message{plural} to {len(targets)} guild(s):\n")
    for t in targets:
        print(f"  • {t['name']} (guild_id={t['guild_id']})")
        print(f"    → channel_id={t['channel_id']}")
    print()
    if n > 1:
        total = sum(len(c) for c in chunks)
        print(
            f"== Content split into {n} messages "
            f"(total {total} chars across chunks):"
        )
    else:
        print("== Content (verbatim):")
    for i, chunk in enumerate(chunks, start=1):
        print("─" * 60)
        if n > 1:
            print(f"-- Chunk {i}/{n} ({len(chunk)} chars) --")
        print(chunk)
    print("─" * 60)
    print()
    print("Re-run with --post to actually publish.")


async def _post_to_targets(
    chunks: list[str], targets: list[dict], token: str, db_env_var: str,
) -> int:
    """Post ``chunks`` to each target's updates channel
    sequentially. Returns the number of guilds where at least one
    chunk landed. Prints per-target success/failure inline so a
    partial failure is visible immediately. One failed guild
    doesn't abort the rest.

    Multi-chunk posts: only the FIRST chunk's message id is
    recorded via :mod:`_post_log` (the canonical handle for
    ``edit_patch_notes`` lookups). Continuation chunks are visible
    in the channel but not separately editable through the tool.
    A 1-second pause between chunks keeps us comfortably under
    Discord's per-channel rate limit (5 msgs / 5 sec).

    Per-guild isolation: log records are keyed by ``db_env_var``
    so a TEST post never appears under a LIVE edit query and
    vice versa."""
    succeeded = 0
    multi = len(chunks) > 1
    async with DiscordRestClient(token) as client:
        for t in targets:
            posted_any = False
            for i, chunk in enumerate(chunks, start=1):
                try:
                    msg = await client.post_message(t["channel_id"], chunk)
                except Exception as e:
                    label = (
                        f"chunk {i}/{len(chunks)}: " if multi else ""
                    )
                    print(
                        f"  ✗ {t['name']} (guild_id={t['guild_id']}): "
                        f"{label}{e}",
                        file=sys.stderr,
                    )
                    continue
                message_id = msg.get("id")
                # Only record the first chunk — that's the
                # canonical handle ``edit_patch_notes`` looks up.
                if i == 1:
                    _post_log.record_post(
                        db_env_var, t["guild_id"], t["channel_id"],
                        int(message_id),
                    )
                if multi:
                    print(
                        f"  ✓ {t['name']} chunk {i}/{len(chunks)} → "
                        f"message_id={message_id}"
                    )
                else:
                    print(
                        f"  ✓ {t['name']} (guild_id={t['guild_id']}) → "
                        f"message_id={message_id}"
                    )
                posted_any = True
                # Rate-limit pacing: 1 second between chunks of
                # the same post. Discord allows 5 msgs / 5 sec
                # per channel; this keeps us well under the wire.
                if i < len(chunks):
                    await asyncio.sleep(1.0)
            if posted_any:
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
    chunks = split_for_discord(content, reserve_header=True)
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
        _print_dry_run(chunks, targets)
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

    n = len(chunks)
    msg_label = f"{n} message{'s' if n > 1 else ''}"
    print(f"== Posting {msg_label} to {len(targets)} guild(s):")
    succeeded = asyncio.run(
        _post_to_targets(chunks, targets, token, args.db_env_var),
    )
    print(f"\nDone — {succeeded}/{len(targets)} guild(s) successful.")
    return 0 if succeeded == len(targets) else 2


if __name__ == "__main__":
    raise SystemExit(main())
