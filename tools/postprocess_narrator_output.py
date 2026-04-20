"""CLI wrapper around ``caldanai.lib.rpg.helpers.parser.lint_output``.

The lint logic itself lives in the parser module (single source of
truth for grammar topics — rules about well-formed narration
templates belong next to the rules that render them). This module
is just the operator-facing CLI for poking at JSON outputs before
commit / during prompt iteration, and a thin ``python -m`` entry
point.

Usage::

    python -m tools.postprocess_narrator_output < sonnet_output.json
    python -m tools.postprocess_narrator_output --input sonnet_output.json --output cleaned.json
    python -m tools.postprocess_narrator_output --quiet < sonnet_output.json

Auto-fixes and warning classes are documented in the lint section
of :mod:`caldanai.lib.rpg.helpers.parser` — see the module-level
comment block starting at "Narrator-output lint".
"""

from __future__ import annotations

import argparse
import json
import sys

from caldanai.lib.rpg.helpers.parser import lint_output


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
    )
    ap.add_argument(
        "--input",
        help="Path to JSON input (default: stdin)",
    )
    ap.add_argument(
        "--output",
        help="Path for cleaned JSON output (default: stdout)",
    )
    ap.add_argument(
        "--quiet", action="store_true",
        help="Suppress warnings on stderr.",
    )
    args = ap.parse_args(argv)

    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = json.load(sys.stdin)

    cleaned, warnings = lint_output(data)

    out_json = json.dumps(cleaned, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out_json + "\n")
    else:
        print(out_json)

    if warnings and not args.quiet:
        for w in warnings:
            print(f"WARN: {w}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
