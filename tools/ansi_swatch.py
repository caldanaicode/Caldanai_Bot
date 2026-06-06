"""Generate a copy-pasteable Discord ```ansi color swatch for palette tuning.

Exists because tuning the ANSI palette (inventory quality colors, the
combat/health tables) is an iterative eyes-on-Discord task, and the only
reliable way to hand a human *real* SGR escape bytes to paste into a
Discord ``ansi`` code-fence is to emit them from Python source — where
``\\x1b`` is unambiguous — rather than hand-typing control characters or
hoping a literal survives a copy chain.

Replaces ad-hoc ``python -c "print('\\x1b[...m')"`` snippets: one approved
``python -m tools.ansi_swatch`` that writes a labeled swatch file you open
and copy into Discord.

It answers the three questions Discord's ``ansi`` renderer raises:
  * which base-16 code reads as a legible gray on Solarized-dark — plain
    and dim ``30`` sink to near-black, bold-black is the usual gray, and
    dim-white is the other candidate;
  * whether Discord honors 256-color (``38;5;N``);
  * whether Discord honors truecolor (``38;2;R;G;B``) — which, if so,
    unlocks a true orange the base palette lacks.

Lines whose codes Discord does NOT support render in the default fg (or
show the raw code), so the swatch is self-diagnosing: if the 256/true
rows look like the plain rows, that mode isn't supported.

Usage::

    python -m tools.ansi_swatch                  # print to stdout
    python -m tools.ansi_swatch --out swatch.txt # also write a file to copy
"""
from __future__ import annotations

import argparse

ESC = "\x1b"
SAMPLE = "a masterwork bandanna"
BLACK_BG = "40"  # forced background — the cross-theme-legibility lever

# (label, sgr-params) — ``sgr`` is the part between ``ESC[`` and ``m``.
SWATCHES = [
    ("base16  0;30  plain black", "0;30"),
    ("base16  1;30  bold black", "1;30"),
    ("base16  2;30  dim black", "2;30"),
    ("base16  0;37  plain white", "0;37"),
    ("base16  1;37  bold white", "1;37"),
    ("base16  2;37  dim white", "2;37"),
    ("256     38;5;240 dark gray", "38;5;240"),
    ("256     38;5;245 mid gray", "38;5;245"),
    ("256     38;5;250 light gray", "38;5;250"),
    ("256     38;5;208 orange", "38;5;208"),
    ("true    38;2;128;128;128 gray", "38;2;128;128;128"),
    ("true    38;2;255;165;0 orange", "38;2;255;165;0"),
]


def build_block(swatches=SWATCHES) -> str:
    """Return a ready-to-paste ```ansi fenced block of labeled swatches.

    A falsy ``sgr`` (None / empty string) renders the sample in the
    default foreground with no escape — the "uncolored" candidate.
    """
    lines = ["```ansi"]
    for label, sgr in swatches:
        if sgr:
            lines.append(f"{label:34} {ESC}[{sgr}m{SAMPLE}{ESC}[0m")
        else:
            lines.append(f"{label:34} {SAMPLE}")
    lines.append("```")
    return "\n".join(lines)


def parse_codes(spec: str):
    """Parse a ``--codes`` spec into ``[(label, sgr-or-None), ...]``.

    Pairs are comma-separated; label and sgr split on the first ``=``.
    An empty sgr (nothing after ``=``) means "uncolored". The sgr may
    itself contain ``;`` (e.g. ``1;33``), which is why ``,`` separates
    pairs rather than ``;``.
    """
    out = []
    for pair in spec.split(","):
        if not pair.strip():
            continue
        label, _, sgr = pair.partition("=")
        out.append((label.strip(), sgr.strip() or None))
    return out


def parse_lines(spec):
    """Parse a ``--lines`` spec into ``[(text, sgr-or-None), ...]``.

    Same ``text=sgr`` grammar as :func:`parse_codes`, but the TEXT
    itself is the colored content (no label column) — so varying-length
    text exposes whether a forced background goes ragged at the right
    edge or fills the fence.
    """
    out = []
    for pair in spec.split(","):
        if not pair.strip():
            continue
        text, _, sgr = pair.partition("=")
        out.append((text, sgr.strip() or None))
    return out


def build_lines_block(lines, bg=BLACK_BG, pad=False) -> str:
    """Render each ``(text, sgr)`` as a full background-painted line.

    With ``pad=True`` every line is space-padded to the longest text so
    the background forms a uniform rectangle instead of a ragged edge —
    the only way to get a clean panel, since Discord's ansi bg paints
    behind characters and never auto-fills to the fence width.
    """
    width = max((len(t) for t, _ in lines), default=0) if pad else 0
    out = ["```ansi"]
    for text, sgr in lines:
        body = text.ljust(width) if pad else text
        prefix = f"{bg};{sgr}" if sgr else bg
        out.append(f"{ESC}[{prefix}m{body}{ESC}[0m")
    out.append("```")
    return "\n".join(out)


def build_lines_block_once(lines, bg=BLACK_BG) -> str:
    """Set the background ONCE at the top and reset ONCE at the bottom.

    Each line only switches foreground (an fg SGR leaves bg untouched),
    with no per-line reset — so this tests whether Discord carries the
    background across newlines and fills the fence on its own, instead
    of re-painting (and space-padding) every row. The hoped-for clean
    panel with zero padding. If Discord resets SGR at each newline, only
    the first line will show the background and this approach is dead.
    """
    out = ["```ansi"]
    body = []
    for i, (text, sgr) in enumerate(lines):
        open_bg = f"{ESC}[{bg}m" if i == 0 else ""
        fg = f"{ESC}[{sgr}m" if sgr else ""
        body.append(f"{open_bg}{fg}{text}")
    out.append("\n".join(body) + f"{ESC}[0m")
    out.append("```")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Emit a copy-pasteable Discord ansi color swatch."
    )
    ap.add_argument("--out", help="Also write the swatch to this file (UTF-8).")
    ap.add_argument(
        "--codes",
        help="Custom swatches as comma-separated 'label=sgr' pairs; empty "
             "sgr = uncolored. e.g. \"junk plain=,junk red=0;31,fine=0;32\".",
    )
    ap.add_argument(
        "--lines",
        help="Varying-length test: comma-separated 'text=sgr' pairs, each "
             "painted on the background with NO label column. Exposes "
             "whether a forced bg goes ragged at the right edge.",
    )
    ap.add_argument(
        "--pad", action="store_true",
        help="With --lines, pad every line to the longest so the background "
             "forms a clean rectangle instead of a ragged edge.",
    )
    ap.add_argument(
        "--once", action="store_true",
        help="With --lines, set the background once at the top and reset once "
             "at the bottom (fg-only per line) — tests whether Discord carries "
             "the bg across newlines without per-row painting or padding.",
    )
    args = ap.parse_args()

    if args.lines and args.once:
        block = build_lines_block_once(parse_lines(args.lines))
    elif args.lines:
        block = build_lines_block(parse_lines(args.lines), pad=args.pad)
    elif args.codes:
        block = build_block(parse_codes(args.codes))
    else:
        block = build_block()
    print(block)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(block + "\n")
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
