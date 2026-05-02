"""Periodic data collection of bg Vael's progress.

Designed for unattended invocation (Windows Task Scheduler) via
the ``tools/vael_collect.bat`` launcher (which resolves the
project's venv). Each run:

1. Snapshots her memory directory; diffs against the previous
   snapshot. Appends a section to the digest only if files
   changed.
2. Pulls thoughts since the last cursor (default mode — her
   internal log-stream). Appends if non-empty.
3. Pulls channel chat since the last cursor (in-character
   Discord posts). Appends if non-empty.
4. Updates the cursor to now.

The digest accumulates chronologically — empty sections are
skipped so the file stays signal-only. Manual prune as it
grows; tens of KB per day is the expected steady state.

State files live under
``~/.claude/projects/E--dev-Caldanai-Bot/memory/``:

- ``_vael_digest.md`` — the rolling digest.
- ``_vael_collect_cursor`` — last collection ISO timestamp.

Usage
-----

::

    tools\\vael_collect.bat              # one-shot collection
    python -m tools.vael_collect --show  # print recent digest
    python -m tools.vael_collect --reset-cursor  # bump cursor to now
"""

import argparse
import datetime
import os
import sys
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

# Reuse helpers from sibling tools rather than subprocessing them —
# faster, gives structured access for empty-section skipping.
from tools.vael_memory_diff import (
    _classify_files,
    _format_diff,
    _list_snapshots,
    _take_snapshot,
)
from tools.vael_thoughts import (
    _iter_assistant_thoughts,
    _resolve_session_path,
)


# Windows consoles default to cp1252 which mangles em-dashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


_STATE_ROOT = (
    Path.home()
    / ".claude"
    / "projects"
    / "E--dev-Caldanai-Bot"
    / "memory"
)
_DIGEST_PATH = _STATE_ROOT / "_vael_digest.md"
_CURSOR_PATH = _STATE_ROOT / "_vael_collect_cursor"
_SNAPSHOT_ROOT = _STATE_ROOT / "_vael_snapshots"

# How far back to look on first run (when there's no cursor file).
# 1 hour matches the typical scheduling cadence.
_DEFAULT_LOOKBACK = datetime.timedelta(hours=1)


def _now_iso() -> str:
    """Current time in ISO-8601, UTC. Used as both the digest
    section header and the cursor write."""
    return (
        datetime.datetime.now(datetime.timezone.utc)
        .strftime("%Y-%m-%dT%H:%M:%S")
    )


def _read_cursor() -> Optional[datetime.datetime]:
    """Read the last-collection cursor from disk. Returns None on
    first run (no file yet)."""
    if not _CURSOR_PATH.exists():
        return None
    raw = _CURSOR_PATH.read_text(encoding="utf-8").strip()
    if not raw:
        return None
    try:
        dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


def _write_cursor(when: datetime.datetime) -> None:
    """Persist the current collection time as the new cursor."""
    _CURSOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CURSOR_PATH.write_text(
        when.strftime("%Y-%m-%dT%H:%M:%S+00:00"),
        encoding="utf-8",
    )


def _append_digest(content: str) -> None:
    """Append a section to the digest. No-op when content is empty."""
    if not content.strip():
        return
    _DIGEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _DIGEST_PATH.open("a", encoding="utf-8") as f:
        if not content.endswith("\n"):
            content += "\n"
        f.write(content)


def _resolve_bg_vael_dir() -> Path:
    """Resolve bg Vael's root directory from BG_VAEL_DIR env var.

    Raises SystemExit when unset. Required for the collector to
    know where the memory/ and workspace/ subdirs live.
    """
    raw = os.environ.get("BG_VAEL_DIR")
    if not raw:
        raise SystemExit(
            "BG_VAEL_DIR env var not set. Add it to .env so the "
            "collector knows where bg Vael's directory tree lives."
        )
    return Path(raw)


def _collect_memory_diff(source: Path) -> List[str]:
    """Snapshot bg Vael's memory dir; diff vs the previous snapshot
    if any. Always takes a fresh snapshot so the next call sees
    *this* state as its baseline.

    Returns the list of digest-section lines (empty when nothing
    changed).
    """
    snapshots = _list_snapshots(_SNAPSHOT_ROOT)
    old = snapshots[-1] if snapshots else None
    new = _take_snapshot(source, _SNAPSHOT_ROOT)

    if old is None:
        # First run — nothing to diff against.
        return [
            "### Memory snapshot",
            f"First snapshot: {new.name} (no prior to diff against).",
        ]

    added, removed, modified, _ = _classify_files(old, new)
    if not (added or removed or modified):
        return []

    lines: List[str] = []
    lines.append(f"### Memory diff (vs {old.name})")
    if added:
        lines.append("**Added:**")
        for rel in added:
            lines.append(f"- `{rel.as_posix()}`")
    if removed:
        lines.append("**Removed:**")
        for rel in removed:
            lines.append(f"- `{rel.as_posix()}`")
    if modified:
        lines.append("**Modified:**")
        for rel in modified:
            lines.append(f"- `{rel.as_posix()}`")
        diff_text = _format_diff(old, new, modified)
        if diff_text:
            lines.append("")
            lines.append("```diff")
            lines.append(diff_text.rstrip())
            lines.append("```")
    return lines


def _collect_thoughts(
    workspace: Path, since: datetime.datetime, mode: str, label: str,
) -> List[str]:
    """Pull entries since cursor in the given mode. Returns digest
    lines when there's content; empty list when nothing matches."""
    try:
        session_path = _resolve_session_path(str(workspace), None)
    except SystemExit:
        # No session file yet — first-run / dormant agent.
        return []
    records = list(
        _iter_assistant_thoughts(session_path, since=since, mode=mode)
    )
    if not records:
        return []
    lines: List[str] = []
    lines.append(
        f"### {label} since {since.strftime('%Y-%m-%dT%H:%M:%S')} "
        f"({len(records)} entries)"
    )
    for rec in records:
        ts = rec.get("timestamp", "?")
        ts_short = ts[:19] if isinstance(ts, str) else "?"
        lines.append(f"- [{ts_short}] {rec['text']}")
    return lines


def _do_collect() -> int:
    """Single collection pass. Builds a digest section per data
    source, writes the consolidated section if anything happened,
    updates the cursor."""
    bg_dir = _resolve_bg_vael_dir()
    source = bg_dir / "memory"
    workspace = bg_dir / "workspace"

    cursor = _read_cursor()
    if cursor is None:
        cursor = (
            datetime.datetime.now(datetime.timezone.utc)
            - _DEFAULT_LOOKBACK
        )

    sections: List[str] = []

    memory_lines = _collect_memory_diff(source)
    if memory_lines:
        sections.append("\n".join(memory_lines))

    thought_lines = _collect_thoughts(
        workspace, cursor, mode="text", label="Thoughts",
    )
    if thought_lines:
        sections.append("\n".join(thought_lines))

    chat_lines = _collect_thoughts(
        workspace, cursor, mode="chat", label="Channel chat",
    )
    if chat_lines:
        sections.append("\n".join(chat_lines))

    if not sections:
        # Nothing happened since last collection — silent. Update
        # cursor anyway so next run's "since" stays sliding-window.
        _write_cursor(
            datetime.datetime.now(datetime.timezone.utc)
        )
        return 0

    header = f"\n## {_now_iso()}\n"
    body = "\n\n".join(sections)
    _append_digest(header + body + "\n")
    _write_cursor(datetime.datetime.now(datetime.timezone.utc))
    return 0


def _do_show(tail_chars: int) -> int:
    """Print the tail of the digest. Useful at session start to
    review what accumulated since last interaction."""
    if not _DIGEST_PATH.exists():
        print(
            f"No digest at {_DIGEST_PATH} — has the collector ever run?",
            file=sys.stderr,
        )
        return 1
    text = _DIGEST_PATH.read_text(encoding="utf-8")
    if len(text) > tail_chars:
        text = "...\n" + text[-tail_chars:]
    print(text)
    return 0


def _do_reset_cursor() -> int:
    """Bump the cursor to now without collecting. Useful when you
    want to start a fresh window without ingesting backlog."""
    when = datetime.datetime.now(datetime.timezone.utc)
    _write_cursor(when)
    print(f"Cursor reset to {when.strftime('%Y-%m-%dT%H:%M:%S+00:00')}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--show",
        action="store_true",
        help=(
            "Print the tail of the digest and exit. No collection "
            "performed."
        ),
    )
    ap.add_argument(
        "--show-tail-chars",
        type=int,
        default=20000,
        help=(
            "Max chars of digest to print under --show "
            "(default: 20000). Earlier content is elided."
        ),
    )
    ap.add_argument(
        "--reset-cursor",
        action="store_true",
        help=(
            "Bump the collection cursor to now without collecting. "
            "Use when you want to ignore a backlog and start a "
            "fresh sliding window."
        ),
    )
    args = ap.parse_args(argv)

    if args.show and args.reset_cursor:
        ap.error("--show and --reset-cursor are mutually exclusive")

    if args.show:
        return _do_show(args.show_tail_chars)
    if args.reset_cursor:
        return _do_reset_cursor()
    return _do_collect()


if __name__ == "__main__":
    sys.exit(main())
