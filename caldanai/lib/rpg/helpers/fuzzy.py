"""Per-pair fuzzy-match primitives shared by lookup helpers.

Two callers compose these primitives differently:

- :meth:`Creature.find_parts` walks dot-separated segments
  positionally (``a.l`` → ``arm.left`` because segment 0 of the
  query matches segment 0 of the name, segment 1 matches
  segment 1).
- :meth:`MonsterPlugin.find_plugin_classes` walks whitespace-
  separated tokens unordered (``"flying math"`` matches the
  ``"math teacher"`` because every query token finds *some*
  name token to match against, regardless of position).

This module just provides the per-pair check. Outer-loop
strategy (zip vs any-to-any) lives at the call site where the
intent is clearest.

All comparisons are case-sensitive — callers normalize to
lowercase before passing in.
"""


def is_prefix(query: str, name: str) -> bool:
    """``True`` iff ``name`` starts with ``query``."""
    return name.startswith(query)


def is_substring(query: str, name: str) -> bool:
    """``True`` iff ``query`` appears anywhere inside ``name``."""
    return query in name


def is_within_one_edit(
    query: str, name: str, *, min_query_len: int = 3
) -> bool:
    """``True`` iff ``query`` is within Levenshtein distance 1 of
    some prefix of ``name`` whose length is ``len(query) - 1``,
    ``len(query)``, or ``len(query) + 1``.

    Catches single-character typos that the prefix and substring
    passes miss:

    - ``forl`` vs ``foreleg``: inserting one ``'e'`` into ``forl``
      produces ``forel``, a 5-char prefix of ``foreleg``.
    - ``hane`` vs ``hand``: substituting ``'e'`` → ``'d'`` produces
      ``hand``, the full name.
    - ``hands`` vs ``hand``: deleting the trailing ``'s'`` produces
      ``hand``, the full name.

    Bounded to ``len(query) >= min_query_len`` (default 3) — without
    a floor, a one-character query would be within edit-distance 1
    of nearly every name, drowning the pass in false matches.
    """
    if len(query) < min_query_len:
        return False
    for prefix_len in (len(query) - 1, len(query), len(query) + 1):
        if prefix_len < 0 or prefix_len > len(name):
            continue
        if _levenshtein_le_1(query, name[:prefix_len]):
            return True
    return False


def _levenshtein_le_1(a: str, b: str) -> bool:
    """Threshold-1 Levenshtein distance check. Returns ``True``
    iff the edit distance between ``a`` and ``b`` is at most 1.

    Optimized for the threshold-1 case rather than computing the
    full distance:

    - Length difference > 1 → distance is at minimum 2 (only
      insertions/deletions/substitutions count, no transpositions).
    - Equal length → walk and count substitutions; bail at 2.
    - Length differs by 1 → align until first mismatch, skip one
      char in the longer string, check the rest matches.
    """
    if abs(len(a) - len(b)) > 1:
        return False
    if a == b:
        return True
    if len(a) == len(b):
        diffs = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                diffs += 1
                if diffs > 1:
                    return False
        return True
    # Length differs by 1 — try inserting one char of the longer
    # into the shorter at the first mismatch and check the rest.
    if len(a) > len(b):
        a, b = b, a
    # b is now exactly one char longer than a.
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    return a[i:] == b[i + 1:]
