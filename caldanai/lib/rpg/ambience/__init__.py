import importlib
from typing import Iterable, List, Optional

from caldanai.logger import get_logger


_log = get_logger(__name__)


# Lines containing escaped double-quoted dialogue read awkwardly when
# spliced mid-sentence (the comma+lowercase glue eats into the dialogue
# integrity). Detect via the literal `\"` substring in the SOURCE
# string OR a literal `"` once Python has unescaped it.
_DIALOGUE_MARKER = '"'


def combine_ambience_lines(
    lines: Iterable[str],
    *,
    known_names: Optional[Iterable[str]] = None,
) -> str:
    """Combine multiple ambience emissions for a single tick into one
    dispatched message. Returns an empty string when no lines were
    provided so the caller can short-circuit dispatch.

    Heuristic:

    - **0 lines** → empty string
    - **1 line** → that line, unchanged
    - **2 lines** → ``"{A_no_period}, as {B_decapped}"`` if both
      combine cleanly; otherwise the two lines on separate sentences
      in a single dispatched message.
    - **3+ lines** → Oxford-comma chain
      (``"{A}, {B}, and {C}."``) when all combine cleanly; otherwise
      newline-joined.

    A line is treated as **uncombinable** when it contains a literal
    ``"`` (quoted dialogue) — splicing into mid-sentence breaks the
    dialogue's read. Mixed-combinability inputs fall back to
    newline-join for the whole batch (cleaner than half-merged
    output).

    Decapitalization: when the second-and-later lines are appended,
    their first character is lowercased UNLESS the first word is in
    ``known_names`` (player / NPC names that shouldn't decap). The
    name set is small in practice; pass the active player roster.
    """
    items = [ln for ln in lines if ln]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]

    # Mixed-combinability fallback: any line with embedded dialogue
    # forces newline-join for the whole batch. Half-merged lines
    # read worse than two cleanly-separated sentences.
    if any(_DIALOGUE_MARKER in ln for ln in items):
        return "\n".join(items)

    names_set = {n.lower() for n in (known_names or [])}

    def _decap(line: str) -> str:
        """Lowercase the first character unless the leading word is
        a known proper noun. Keeps name lines intact when spliced
        mid-sentence (e.g. 'Wren writes...' stays capitalized)."""
        if not line:
            return line
        first_word = line.split(maxsplit=1)[0].rstrip(",.;:!?'\"")
        if first_word.lower() in names_set:
            return line
        return line[0].lower() + line[1:]

    def _strip_trailing_period(line: str) -> str:
        return line[:-1] if line.endswith(".") else line

    if len(items) == 2:
        a = _strip_trailing_period(items[0])
        b = _decap(items[1])
        return f"{a}, as {b}"

    # 3+ lines — Oxford-comma chain. First line keeps trailing
    # period stripped; middle lines decapped + period-stripped;
    # last line decapped, period preserved (or appended if missing).
    parts = [_strip_trailing_period(items[0])]
    for mid in items[1:-1]:
        parts.append(_strip_trailing_period(_decap(mid)))
    last = _decap(items[-1])
    if not last.endswith((".", "!", "?")):
        last += "."
    parts.append(f"and {last}")
    return ", ".join(parts)


class Ambience:
    def __init__(
        self,
        min_duration: int = 10,
        max_duration: int = 60,
        frequency: int = 300,
        arrival_msg: str = "",
        departure_msg: str = "",
        sunrise_msg: str = "",
        sunset_msg: str = "",
    ):
        self.min_duration: int = max(1, max(min_duration, max_duration))
        self.max_duration: int = max(1, min(max_duration, min_duration))
        self.frequency: int = max(1, frequency)

        if self.min_duration > self.max_duration:
            tmp = self.min_duration
            self.min_duration = max_duration
            self.max_duration = tmp

    def get_ambience(self) -> str:
        return ""

    @classmethod
    def from_plugin(cls, plugin_name: str):
        """Creates a new weather pattern from a plugin."""

        try:
            weather = importlib.import_module(f"caldanai.lib.rpg.inventory.armor.{plugin_name}").WeatherPlugin()
            return weather

        except:
            _log.error(f"Unable to load WeatherPlugin: {plugin_name}")
            return None
