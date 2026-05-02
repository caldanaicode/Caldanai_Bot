"""Snapshot bg Vael's memory directory and diff later snapshots
against earlier ones. Built so morning consolidation passes can
say "what did she write down between yesterday and today" without
hand-comparing every file in her memory tree.

Pairs with ``vael_thoughts.py``: that tool shows what she SAID
(in-conversation assistant text); this tool shows what she
deliberately MEMORIALIZED (curated memory writes). Together they
cover both the curated and the in-flight signal.

Usage
-----

::

    python -m tools.vael_memory_diff --snapshot
                                       # snapshot now, no diff
    python -m tools.vael_memory_diff --diff
                                       # diff current state vs latest snapshot
    python -m tools.vael_memory_diff --diff <timestamp>
                                       # diff vs a specific snapshot
    python -m tools.vael_memory_diff --list
                                       # list available snapshots
    python -m tools.vael_memory_diff
                                       # default: diff vs latest, then snapshot

The default behavior (no flag) is the morning-pass workflow:
diff current state against the most recent snapshot to see
what's changed, then take a fresh snapshot so the next call
diffs against this one.

Snapshot storage
----------------

Snapshots live under
``~/.claude/projects/E--dev-Caldanai-Bot/memory/_vael_snapshots/<iso-ts>/``,
each a recursive copy of bg Vael's memory directory at the
snapshot moment. Leading underscore on the dir keeps it out of
the normal ``<type>_<topic>.md`` memory-file conventions so
agent memory loaders skip it.

Snapshots accumulate — prune manually if disk gets tight.
Memory dirs are tiny (~30KB per session) so this is mostly
not a concern.

Diff output
-----------

Walks both trees, classifies each file as added / removed /
modified / unchanged. Emits a unified diff for modified files
(via ``difflib.unified_diff``). Suppresses unchanged files from
output by default — pass ``--show-unchanged`` for a complete
manifest.
"""

import argparse
import datetime
import difflib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

from dotenv import load_dotenv

# Load main-project .env so BG_VAEL_WORKSPACE resolves without
# pulling in caldanai.environment (which mandates DB_CONNECTION).
# Idempotent; safe under repeated tool invocations.
load_dotenv()


# Windows consoles default to cp1252 which mangles em-dashes and
# other non-latin1 glyphs when piping. Reconfigure where supported.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


_SNAPSHOT_ROOT = (
    Path.home()
    / ".claude"
    / "projects"
    / "E--dev-Caldanai-Bot"
    / "memory"
    / "_vael_snapshots"
)


def _default_source() -> Optional[str]:
    """Resolve the default source directory from ``BG_VAEL_DIR``
    env var (the bg-agent's root directory); the memory dir is
    the ``memory`` subdirectory of that root.

    Returns None when the env var is unset — the CLI then errors
    with a helpful message rather than reading from a baked-in
    operator-specific path. Keeps any drive-letter / project-tree
    layout out of source.
    """
    raw = os.environ.get("BG_VAEL_DIR")
    if not raw:
        return None
    return str(Path(raw) / "memory")


def _iso_timestamp(now: Optional[datetime.datetime] = None) -> str:
    """ISO-8601 with hyphens substituted for colons (filesystem-safe).

    ``2026-05-02T18-30-00`` instead of ``2026-05-02T18:30:00``. Sorts
    correctly as a string because the field widths are fixed.
    """
    dt = now or datetime.datetime.now()
    return dt.strftime("%Y-%m-%dT%H-%M-%S")


def _list_snapshots(snapshot_root: Path) -> List[Path]:
    """Return snapshot directories in chronological order
    (oldest → newest). ISO-style names sort lexicographically the
    same as chronologically, so sorted() suffices."""
    if not snapshot_root.exists():
        return []
    return sorted(
        p for p in snapshot_root.iterdir()
        if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}T", p.name)
    )


def _take_snapshot(source: Path, snapshot_root: Path) -> Path:
    """Copy ``source`` recursively into a fresh timestamped subdir of
    ``snapshot_root``. Returns the snapshot path."""
    if not source.exists():
        raise SystemExit(
            f"Source memory dir does not exist: {source}. "
            "Has bg Vael ever run a session?"
        )
    snapshot_root.mkdir(parents=True, exist_ok=True)
    dest = snapshot_root / _iso_timestamp()
    # If two snapshots are taken in the same second, append a -2
    # suffix so the second one doesn't fail on existing-dir.
    candidate = dest
    n = 2
    while candidate.exists():
        candidate = snapshot_root / f"{dest.name}-{n}"
        n += 1
    shutil.copytree(source, candidate)
    return candidate


def _resolve_snapshot(
    snapshot_root: Path, name: Optional[str]
) -> Optional[Path]:
    """Resolve a user-supplied snapshot name (or None for latest).

    Returns None when no snapshots exist; raises SystemExit when
    a specific name was requested and not found."""
    if name is None:
        snapshots = _list_snapshots(snapshot_root)
        return snapshots[-1] if snapshots else None
    candidate = snapshot_root / name
    if not candidate.exists() or not candidate.is_dir():
        raise SystemExit(
            f"Snapshot not found: {candidate}. "
            f"Run with --list to see available names."
        )
    return candidate


def _walk_relative(root: Path) -> Iterator[Path]:
    """Yield file paths relative to ``root`` for every regular file
    in the tree, sorted for stable diff output."""
    if not root.exists():
        return
    for p in sorted(root.rglob("*")):
        if p.is_file():
            yield p.relative_to(root)


def _read_text(path: Path) -> List[str]:
    """Read a file as a list of lines (trailing newlines preserved).

    Returns ``[]`` for unreadable files rather than raising — diff
    output is nicer when one side of a comparison is missing or
    binary than when the tool aborts."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return text.splitlines(keepends=True)


def _classify_files(
    old_root: Path, new_root: Path
) -> "Tuple[List[Path], List[Path], List[Path], List[Path]]":
    """Classify every file in either tree by relation to the other.

    Returns ``(added, removed, modified, unchanged)`` — each a list
    of relative paths sorted alphabetically. ``modified`` includes
    both content-different and metadata-only-different files."""
    old_files = set(_walk_relative(old_root)) if old_root else set()
    new_files = set(_walk_relative(new_root)) if new_root else set()
    added = sorted(new_files - old_files)
    removed = sorted(old_files - new_files)
    common = new_files & old_files
    modified: List[Path] = []
    unchanged: List[Path] = []
    for rel in sorted(common):
        if (old_root / rel).read_bytes() != (new_root / rel).read_bytes():
            modified.append(rel)
        else:
            unchanged.append(rel)
    return added, removed, modified, unchanged


def _format_diff(
    old_root: Path, new_root: Path, rel_paths: List[Path],
    *, context_lines: int = 2,
) -> str:
    """Build a unified diff for every file in ``rel_paths``."""
    chunks: List[str] = []
    for rel in rel_paths:
        old_lines = _read_text(old_root / rel)
        new_lines = _read_text(new_root / rel)
        diff = list(
            difflib.unified_diff(
                old_lines,
                new_lines,
                fromfile=f"old/{rel.as_posix()}",
                tofile=f"new/{rel.as_posix()}",
                n=context_lines,
            )
        )
        if diff:
            chunks.append("".join(diff))
    return "\n".join(chunks)


def _print_summary(
    old: Optional[Path], new: Path,
    added: List[Path], removed: List[Path],
    modified: List[Path], unchanged: List[Path],
    *, show_unchanged: bool,
) -> None:
    if old is None:
        print("# bg Vael memory snapshot — first capture")
        print(f"snapshot: {new}")
        print(f"files captured: {len(added)}")
        return
    print(f"# bg Vael memory diff")
    print(f"  old: {old.name}")
    print(f"  new: {new}")
    print()
    print(
        f"summary: {len(added)} added · {len(removed)} removed · "
        f"{len(modified)} modified · {len(unchanged)} unchanged"
    )
    print()
    if added:
        print("## Added")
        for rel in added:
            print(f"  + {rel.as_posix()}")
        print()
    if removed:
        print("## Removed")
        for rel in removed:
            print(f"  - {rel.as_posix()}")
        print()
    if modified:
        print("## Modified")
        for rel in modified:
            print(f"  ~ {rel.as_posix()}")
        print()
    if show_unchanged and unchanged:
        print("## Unchanged")
        for rel in unchanged:
            print(f"  = {rel.as_posix()}")
        print()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--source",
        default=None,
        help=(
            "Memory directory to snapshot. Defaults to "
            "``$BG_VAEL_DIR/memory`` when that env var is set; "
            "otherwise must be supplied explicitly. Keeps "
            "operator-specific path layout out of source."
        ),
    )
    ap.add_argument(
        "--snapshot-root",
        default=str(_SNAPSHOT_ROOT),
        help=(
            "Root directory under which snapshots are stored. "
            "Default: ``~/.claude/projects/E--dev-Caldanai-Bot/"
            "memory/_vael_snapshots``."
        ),
    )
    ap.add_argument(
        "--snapshot",
        action="store_true",
        help="Take a snapshot now and exit. No diff.",
    )
    ap.add_argument(
        "--diff",
        nargs="?",
        const="__latest__",
        default=None,
        metavar="TIMESTAMP",
        help=(
            "Diff bg Vael's current memory dir against a snapshot. "
            "With no value, diffs against the latest snapshot. "
            "With a value, looks up the snapshot by timestamp name."
        ),
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="List available snapshots, oldest first.",
    )
    ap.add_argument(
        "--show-unchanged",
        action="store_true",
        help="Include unchanged files in the diff manifest.",
    )
    ap.add_argument(
        "--no-snapshot-after",
        action="store_true",
        help=(
            "Default-mode behavior takes a fresh snapshot after "
            "diffing so the next run diffs against this point. "
            "Pass this to skip that — useful when you're "
            "investigating a specific change without polluting "
            "the snapshot timeline."
        ),
    )
    args = ap.parse_args(argv)

    source_str = args.source or _default_source()
    if not source_str:
        ap.error(
            "No source directory: pass --source <path> or set "
            "BG_VAEL_DIR in the environment so the default "
            "(``$BG_VAEL_DIR/memory``) resolves."
        )
    source = Path(source_str)
    snapshot_root = Path(args.snapshot_root)

    if args.list:
        snapshots = _list_snapshots(snapshot_root)
        if not snapshots:
            print(f"No snapshots in {snapshot_root}", file=sys.stderr)
            return 1
        for p in snapshots:
            stat = p.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            file_count = sum(1 for _ in _walk_relative(p))
            print(f"{p.name}  {mtime}  {file_count} files")
        return 0

    if args.snapshot:
        new = _take_snapshot(source, snapshot_root)
        print(f"Snapshot taken: {new}")
        return 0

    # --diff or default mode: classify + summarize.
    if args.diff is not None:
        target = None if args.diff == "__latest__" else args.diff
        old = _resolve_snapshot(snapshot_root, target)
    else:
        # Default mode: diff vs latest then snapshot.
        old = _resolve_snapshot(snapshot_root, None)

    added, removed, modified, unchanged = _classify_files(
        old if old else None, source,
    )
    _print_summary(
        old, source, added, removed, modified, unchanged,
        show_unchanged=args.show_unchanged,
    )
    if old is not None and modified:
        print()
        print("## Diffs")
        print()
        diff_text = _format_diff(old, source, modified)
        if diff_text:
            print(diff_text)

    # Default mode also takes a snapshot after diffing, unless
    # --no-snapshot-after was passed. --diff alone (explicit) does
    # not take a snapshot — it's purely an inspection.
    if args.diff is None and not args.no_snapshot_after:
        new = _take_snapshot(source, snapshot_root)
        print()
        print(f"# Fresh snapshot taken: {new.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
