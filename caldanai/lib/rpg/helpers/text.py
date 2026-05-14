"""Free-standing text helpers shared across cogs and creature
plugins. Lives under ``helpers/`` so any consumer can import
without crossing into a cog's namespace.

Currently houses the Oxford-comma list joiner — previously
duplicated on ``BodyPart.gear_drop_flavor`` and
``Doppelganger._oxford_join``. The two copies had drifted into
identical shape; consolidating here keeps the comma + "and"
voice consistent across every narration pipeline that emits a
"slipped from / engulfs / aches" list.
"""

from typing import Iterable, Sequence


def oxford_join(items: Iterable[str]) -> str:
    """Join ``items`` into an Oxford-comma'd English list.

    Examples:

    - ``[]`` → ``""``
    - ``["a"]`` → ``"a"``
    - ``["a", "b"]`` → ``"a and b"`` (no comma — Oxford style
      reserves the comma for 3+)
    - ``["a", "b", "c"]`` → ``"a, b, and c"``
    - ``["a", "b", "c", "d"]`` → ``"a, b, c, and d"``
    """
    seq: Sequence[str] = list(items)
    if not seq:
        return ""
    if len(seq) == 1:
        return seq[0]
    if len(seq) == 2:
        return f"{seq[0]} and {seq[1]}"
    return ", ".join(seq[:-1]) + f", and {seq[-1]}"
