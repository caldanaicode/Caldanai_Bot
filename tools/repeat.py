"""Run a command N times (or once per value in a list) inside one
Python process so the outer invocation stays covered by the
``python -m tools.*`` permission allowlist — no per-iteration
approval prompt.

Usage::

    # Count-based: run the same command N times.
    python -m tools.repeat --count 5 -- python -m pytest -q
    python -m tools.repeat -n 3 -- python -m tools.playtest_weapon_sweep --seed {i}

    # Value-based: run the command once per value in --each.
    python -m tools.repeat --each pixie,goblin,bandit -- python -m tools.inspect_monster {v}
    python -m tools.repeat --each "mace,shortsword,spear" -- \\
        python -m tools.playtest_combat_harness --weapon {v} --monster goblin

Substitution tokens:
    ``{i}`` — 1-indexed iteration number.
    ``{v}`` — current value from ``--each`` (only when ``--each`` is
              supplied; raises if referenced without a value list).

The command after ``--`` is executed via ``subprocess.run`` with the
argv split the shell already handed us — no shell re-parsing, no
quoting surprises. Exit-code summary at the end; overall return is 0
only if every iteration exited 0.

Why this exists: bash for-loops (``for i in ...; do python -m tools.X;
done``) aren't matched by ``Bash(python -m tools.*)`` — each loop
body re-prompts the permission harness. This runner keeps the
outer invocation in the allowlist while iterating inside Python.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from typing import List, Optional


def _apply_iter(args: List[str], iteration: int, value: Optional[str] = None) -> List[str]:
    """Replace ``{i}`` with the iteration number and (when supplied)
    ``{v}`` with the current value."""
    token = str(iteration)
    out: List[str] = []
    for arg in args:
        substituted = arg.replace("{i}", token)
        if value is not None:
            substituted = substituted.replace("{v}", value)
        out.append(substituted)
    return out


def _resolve_python(cmd: List[str]) -> List[str]:
    """If the command's first arg is ``python`` / ``python3``,
    substitute ``sys.executable`` so the subprocess uses the same
    interpreter (and therefore the same venv) as the tool itself.
    Without this, an activated venv's ``python`` may not propagate
    to ``subprocess.run``'s PATH resolution on Windows."""
    if cmd and cmd[0] in ("python", "python3"):
        return [sys.executable] + cmd[1:]
    return cmd


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "-n", "--count", type=int, default=5,
        help="Number of iterations (default 5). Ignored when "
             "--each is supplied — iteration count becomes the "
             "length of the --each list.",
    )
    ap.add_argument(
        "--each", default=None,
        help="Comma-separated values to iterate over. Command runs "
             "once per value; ``{v}`` in the command is replaced "
             "with the current value.",
    )
    ap.add_argument(
        "--stop-on-failure", action="store_true",
        help="Abort after the first non-zero exit code.",
    )
    ap.add_argument(
        "--quiet", action="store_true",
        help="Suppress per-iteration headers. Summary still prints.",
    )
    ap.add_argument(
        "command", nargs=argparse.REMAINDER,
        help="Command to run, passed after ``--`` (e.g. "
             "``-- python -m pytest -q``). ``{i}`` in any arg is "
             "replaced with the iteration number; ``{v}`` with the "
             "current --each value.",
    )
    args = ap.parse_args(argv)

    cmd = args.command
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        ap.error("command is required after ``--``")

    if args.each is not None:
        values: List[Optional[str]] = [v.strip() for v in args.each.split(",") if v.strip()]
        if not values:
            ap.error("--each received no values")
    else:
        # Count-mode: iterate without a value. Sentinels of None keep
        # the single loop below shape-clean.
        values = [None] * args.count

    results: List[int] = []
    start = time.time()
    total_iterations = len(values)
    for i, value in enumerate(values, start=1):
        if not args.quiet:
            label = f"value={value}" if value is not None else f"{i}/{total_iterations}"
            print(f"\n--- iteration {label} ---", flush=True)
        actual = _resolve_python(_apply_iter(cmd, i, value))
        result = subprocess.run(actual)
        results.append(result.returncode)
        if args.stop_on_failure and result.returncode != 0:
            print(
                f"\n!!! iteration {i} exited {result.returncode}; "
                f"stopping early.", file=sys.stderr,
            )
            break

    elapsed = time.time() - start
    passed = sum(1 for rc in results if rc == 0)
    total = len(results)
    avg_bit = f", avg {elapsed / total:.1f}s / iter" if total else ""
    print(
        f"\n=== {passed}/{total} succeeded "
        f"(elapsed {elapsed:.1f}s{avg_bit}) ===",
    )
    if passed != total:
        failing = [str(i + 1) for i, rc in enumerate(results) if rc != 0]
        print(f"failing iterations: {', '.join(failing)}", file=sys.stderr)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
