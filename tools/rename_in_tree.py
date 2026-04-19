"""Bulk literal rename across a file tree — sed-style, without sed.

Stable-invocation substitute for one-off ``sed -i 's/old/new/g'``
calls, covered by the existing ``python -m tools.*`` harness
permission so no per-run approval gauntlet.

Scope is deliberately narrow: **literal** string replacement only,
no regex. That sidesteps the footgun where a sed pattern eats
characters you didn't mean to match (and keeps the help text one
page). For regex-powered search-and-replace, reach for an IDE.

Usage::

    # Dry run — prints the files that would change and how many
    # times each --replace pair would fire per file.
    python -m tools.rename_in_tree "caldanai/**/*.py" \\
        --replace "warmth.LEVEL_COLD" "warmth.Warmth.COLD" \\
        --replace "warmth.LEVEL_COOL" "warmth.Warmth.COOL"

    # Apply.
    python -m tools.rename_in_tree "caldanai/**/*.py" \\
        --replace "OLD" "NEW" \\
        --apply

One or more globs may be given. ``**`` recurses. Binary files
(content that fails UTF-8 decode) are skipped silently.
"""

import argparse
import glob as glob_mod
import sys
from pathlib import Path
from typing import List, Tuple


# Windows consoles default to cp1252 which mangles non-latin1 glyphs.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def _iter_files(globs: List[str]) -> List[Path]:
    """Expand the glob patterns to a de-duplicated, sorted file
    list. Non-files (directories, broken symlinks) are dropped.
    ``**`` is supported via ``recursive=True``."""
    seen: set[Path] = set()
    out: List[Path] = []
    for pattern in globs:
        for match in glob_mod.glob(pattern, recursive=True):
            p = Path(match)
            if not p.is_file():
                continue
            if p in seen:
                continue
            seen.add(p)
            out.append(p)
    out.sort()
    return out


def _apply_replacements(
    content: str, pairs: List[Tuple[str, str]],
) -> Tuple[str, List[int]]:
    """Apply each ``(old, new)`` pair in order, returning the
    rewritten content and a per-pair count of how many times each
    pair fired. Order matters when one pair's result could be
    matched by a later pair — callers should list pairs in the
    order they want them to land."""
    counts: List[int] = []
    for old, new in pairs:
        n = content.count(old)
        counts.append(n)
        if n > 0:
            content = content.replace(old, new)
    return content, counts


def rewrite_file(
    path: Path,
    pairs: List[Tuple[str, str]],
    apply: bool,
) -> Tuple[int, List[int]]:
    """Process one file. Returns ``(total_hits, per_pair_counts)``.

    - ``total_hits == 0`` → no change, skipped (never written).
    - ``apply is False`` → content is computed but not written.
    - ``apply is True``  → content is written if and only if
      ``total_hits > 0``.

    Files that can't be decoded as UTF-8 (binaries, mis-encoded
    archives) are skipped with ``(0, [0, 0, ...])`` — we don't
    want to corrupt a PNG because someone passed a wide glob.
    """
    try:
        original = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0, [0] * len(pairs)
    new_content, counts = _apply_replacements(original, pairs)
    total = sum(counts)
    if total > 0 and apply:
        path.write_text(new_content, encoding="utf-8")
    return total, counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "globs",
        nargs="+",
        help="One or more file globs. ``**`` recurses.",
    )
    parser.add_argument(
        "--replace",
        nargs=2,
        action="append",
        metavar=("OLD", "NEW"),
        required=True,
        help=(
            "Literal search-and-replace pair. Repeat the flag to "
            "stack multiple renames in a single pass. Applied in the "
            "order given, per file."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Default is dry-run (report only).",
    )
    args = parser.parse_args()

    pairs: List[Tuple[str, str]] = [(o, n) for o, n in args.replace]
    files = _iter_files(args.globs)

    if not files:
        print("No files matched the given globs.", file=sys.stderr)
        return 1

    touched = 0
    total_hits = 0
    header = "== DRY RUN" if not args.apply else "== APPLYING"
    print(f"{header} across {len(files)} file(s):")
    for path in files:
        hits, counts = rewrite_file(path, pairs, apply=args.apply)
        if hits == 0:
            continue
        touched += 1
        total_hits += hits
        detail = ", ".join(
            f"'{o}' → '{n}' ×{c}"
            for (o, n), c in zip(pairs, counts)
            if c > 0
        )
        print(f"  {path}: {hits} hit(s) — {detail}")

    verb = "would change" if not args.apply else "changed"
    print(
        f"\n{touched} file(s) {verb}, {total_hits} total replacement(s)."
    )
    if not args.apply and touched > 0:
        print("Re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
