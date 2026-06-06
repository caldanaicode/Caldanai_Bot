"""Shared ANSI escape constants for Discord ``ansi`` code-fence output.

Discord renders SGR sequences (``\\x1b[N;Mm...\\x1b[0m``) inside an
``\\`\\`\\`ansi`` block using its Solarized-Dark palette. This module
centralizes the named color codes, intensity modifiers, and a wrap()
helper so combat-table rendering and body-part injury displays draw
from one palette instead of duplicating literals.

Usage::

    from caldanai.lib.rpg.helpers import ansi

    ansi.wrap("HIT", ansi.GREEN)                       # normal green
    ansi.wrap("CRIT", ansi.YELLOW, intensity=ansi.BOLD)  # bold yellow
    ansi.wrap("destroyed", ansi.GRAY, intensity=ansi.DIM)  # dim gray

The color and intensity values are deliberately the bare SGR digit
strings so they compose with ``INJURY_LEVEL_DISPLAY`` (which stores
the same raw codes) without translation.
"""

# Foreground color codes — the digit portion of an SGR sequence.
# Discord's ``ansi`` fence renders these against its Solarized-Dark
# theme, so the visual hue differs slightly from a terminal but the
# semantics (red=danger, green=success, etc.) carry through.
GRAY = "30"
RED = "31"
GREEN = "32"
YELLOW = "33"
BLUE = "34"
PINK = "35"
CYAN = "36"
WHITE = "37"

# Background color codes are the fg digits + 10 (40–47). Pass one as the
# ``bg`` kwarg of :func:`wrap` for a per-token highlight/badge — used
# sparingly (e.g. the masterwork "gold badge" in the inventory), since a
# full-row background can't be filled cleanly inside a Discord ansi fence
# (it only paints behind characters, so a row-wide panel goes ragged).

# Intensity modifiers — prefix to a color code via the ``intensity``
# kwarg on :func:`wrap`. ``DIM`` (``2;``) was the existing convention
# for body-part injury coloring; combat-table reactive flavors use
# ``BOLD`` (``1;``) to make crits / fumbles pop against the row.
NORMAL = "0"
BOLD = "1"
DIM = "2"
UNDERLINE = "4"

# Reset sequence — closes any open SGR run. Wrapped automatically by
# :func:`wrap` but exposed for callers that need to compose multiple
# colored runs inside one f-string.
RESET = "\x1b[0m"


def wrap(text: str, color: str, *, intensity: str = NORMAL, bg: str = None) -> str:
    """Wrap ``text`` in an ANSI color escape, with optional intensity/bg.

    ``color`` is a foreground digit (e.g. :data:`GREEN`); ``intensity``
    is one of :data:`NORMAL` / :data:`BOLD` / :data:`DIM` /
    :data:`UNDERLINE`; ``bg`` is an optional background digit (40–47)
    for a per-token highlight/badge. Empty ``text`` is returned as-is —
    avoids stray reset codes leaking into output when a caller has
    nothing to color.
    """
    if not text:
        return text
    sgr = f"{intensity};{bg};{color}" if bg else f"{intensity};{color}"
    return f"\x1b[{sgr}m{text}{RESET}"
