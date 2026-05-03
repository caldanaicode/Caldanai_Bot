"""Shared fuzzy-match resolver and per-pair primitives for lookup
helpers.

This module has two layers:

- **Per-pair primitives** (:func:`is_prefix`, :func:`is_substring`,
  :func:`is_within_one_edit`) — answer the question "does this query
  token relate to this name token in this way?" Pure string ops.

- **Resolver** (:func:`fuzzy_match`) — wraps the primitives in the
  standard pass chain (exact → prefix → substring → optional
  edit-distance) and a pluggable outer-loop strategy (positional zip
  vs unordered any-to-any). Callers supply a candidate iterable, a
  ``keys`` extractor (one or more searchable strings per candidate),
  and a tokenizer; the resolver returns deduped matches in iteration
  order.

Two outer strategies cover the existing call sites:

- :meth:`Creature.find_parts` walks dot-separated segments
  positionally (``a.l`` → ``arm.left`` because segment 0 of the
  query matches segment 0 of the name, segment 1 matches
  segment 1).
- :meth:`MonsterPlugin.find_plugin_classes` walks whitespace-
  separated tokens unordered (``"flying math"`` matches the
  ``"math teacher"`` because every query token finds *some*
  name token to match against, regardless of position).

Primitive comparisons are case-sensitive — :func:`fuzzy_match`
lowercases at its boundary so primitives never see mixed case.
"""

from typing import (
    Callable, Generic, Iterable, List, Literal, Optional, Sequence, TypeVar,
)

T = TypeVar("T")
Strategy = Literal["positional", "unordered"]


class FuzzyResult(Generic[T]):
    """Tiered match result from :func:`fuzzy_match`.

    Carries one list per pass-tier (exact / prefix / substring /
    edit_distance). Use :attr:`tightest` for strict prioritization
    (first non-empty tier wins — exact wins over prefix wins over
    substring; what most callers want), or :attr:`all` for the
    union of every tier in tier order.

    Direct tier access via :attr:`exact` / :attr:`prefix` /
    :attr:`substring` / :attr:`edit_distance` lets callers
    introspect *how* a query resolved — handy for "did you mean..."
    UX where an exact match should land silently but a fuzzy match
    might warrant a confirmation hint.

    List-compatible for ergonomics: iterating, sizing, truth-
    testing, indexing, and equality-checking against a list all
    proxy to :attr:`tightest`. Code that just wants the strict-
    prioritization view can treat the result as a list without
    knowing about the tiered structure.
    """

    def __init__(
        self,
        exact: Optional[List[T]] = None,
        prefix: Optional[List[T]] = None,
        substring: Optional[List[T]] = None,
        edit_distance: Optional[List[T]] = None,
    ) -> None:
        self.exact: List[T] = list(exact) if exact else []
        self.prefix: List[T] = list(prefix) if prefix else []
        self.substring: List[T] = list(substring) if substring else []
        self.edit_distance: List[T] = (
            list(edit_distance) if edit_distance else []
        )

    @property
    def tightest(self) -> List[T]:
        """First non-empty tier in exact → prefix → substring →
        edit-distance order.

        The strict-prioritization view: a literal ``wand`` exact-
        matches the inventory's ``wand`` and short-circuits past
        the substring matches that would also include
        ``magic_wand``. Same prefix-wins invariant we use for body
        parts (``leg`` → literal ``leg``, not via substring of
        ``foreleg``) and for monster names. Most callers want
        this view.
        """
        return (
            self.exact
            or self.prefix
            or self.substring
            or self.edit_distance
        )

    @property
    def all(self) -> List[T]:
        """Union across every tier, deduped, in tier order
        (exact → prefix → substring → edit_distance). For
        autocomplete-style "show me everything that could match"
        UX where the caller surfaces all candidates and lets the
        player pick rather than auto-resolving.
        """
        return _dedup_in_order(
            [
                *self.exact,
                *self.prefix,
                *self.substring,
                *self.edit_distance,
            ]
        )

    def __bool__(self) -> bool:
        return bool(self.tightest)

    def __iter__(self):
        return iter(self.tightest)

    def __len__(self) -> int:
        return len(self.tightest)

    def __getitem__(self, i):
        return self.tightest[i]

    def __contains__(self, item) -> bool:
        return item in self.tightest

    def __eq__(self, other) -> bool:
        # List equality compares against the tightest tier so the
        # ergonomic ``assert resolve_x(...) == [a, b]`` shape stays
        # valid even after the base function moved to FuzzyResult.
        if isinstance(other, list):
            return self.tightest == other
        if isinstance(other, FuzzyResult):
            return (
                self.exact == other.exact
                and self.prefix == other.prefix
                and self.substring == other.substring
                and self.edit_distance == other.edit_distance
            )
        return NotImplemented

    def __ne__(self, other) -> bool:
        result = self.__eq__(other)
        if result is NotImplemented:
            return result
        return not result

    __hash__ = None  # mutable list-bearing container

    def __repr__(self) -> str:
        return (
            f"FuzzyResult(exact={self.exact!r}, "
            f"prefix={self.prefix!r}, "
            f"substring={self.substring!r}, "
            f"edit_distance={self.edit_distance!r})"
        )


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


# ---------------------------------------------------------------------------
# Tokenizers — query/key splitters fed into :func:`fuzzy_match`.
# ---------------------------------------------------------------------------


def whitespace_tokens(s: str) -> List[str]:
    """Split on whitespace, underscores, and dots — the catch-all
    name-phrase tokenizer.

    ``"flying_math.teacher"`` → ``['flying', 'math', 'teacher']`` —
    same shape as ``"flying math teacher"`` so registry stems
    (``math_teacher``) and display aliases (``flying math teacher``)
    and dot-typed queries (``math.teacher``) all produce identical
    token streams.

    Returns ``[]`` for empty / whitespace-only input.
    """
    return s.replace("_", " ").replace(".", " ").split()


def dot_segments(s: str) -> List[str]:
    """Split on ``.`` only — strict positional path tokenizer.

    ``"leg.left"`` → ``['leg', 'left']``. Empty leading / trailing /
    middle segments survive (``"leg."`` → ``['leg', '']``) so the
    resolver can reject malformed paths rather than silently
    prefix-matching anything via the empty segment.

    Returns ``[]`` for empty / whitespace-only input.
    """
    if not s.strip():
        return []
    return s.split(".")


# ---------------------------------------------------------------------------
# Resolver — single fuzzy_match shared by every callsite.
# ---------------------------------------------------------------------------


def fuzzy_match(
    query: str,
    candidates: Iterable[T],
    *,
    keys: Callable[[T], Iterable[str]],
    tokenizer: Callable[[str], List[str]] = whitespace_tokens,
    strategy: Strategy = "unordered",
    edit_distance: bool = False,
) -> FuzzyResult[T]:
    """Resolve ``query`` against ``candidates`` and return a tiered
    :class:`FuzzyResult` carrying every match grouped by pass-tier.

    Each candidate exposes one or more searchable strings via
    ``keys``; a candidate appears in a tier when ANY of its keys
    matches under that tier's pass. Tiers are computed independently
    so callers can choose strict prioritization (``.tightest``,
    most-callers default) or full union (``.all``, autocomplete-
    style) — see :class:`FuzzyResult`.

    Tiers, in order of specificity:

    1. **exact** — whole-string equality of query against any key.
    2. **prefix** — every query token has a prefix-match counterpart
       on the key (relation governed by ``strategy``).
    3. **substring** — every query token has a substring-match
       counterpart.
    4. *(opt-in)* **edit_distance** — every query token is within
       one Levenshtein edit of a key token (or is a prefix of it).
       Disabled by default; enable for parts where typos are
       common. The "or-prefix" disjunction matters because edit-
       distance has a min-query-length floor — short tokens like
       ``r`` would otherwise not match anything in this pass.

    Tiers are *non-overlapping* — a candidate that exact-matches is
    only listed in ``exact``, never also in ``prefix`` / ``substring``.
    This preserves the strict-prioritization view via
    :attr:`FuzzyResult.tightest` (a literal ``wand`` doesn't smear
    into ``magic_wand`` via the substring tier when an exact match
    is already present).

    ``strategy`` selects the outer-loop shape:

    - ``"unordered"`` *(default)* — every query token must match
      SOME key token regardless of order. For whitespace name
      phrases where ``"flying math"`` and ``"math flying"`` should
      resolve identically.
    - ``"positional"`` — query and key tokens are zipped; the
      query cannot have more tokens than the key. For dot-
      separated structured paths (``leg.left``) where segment 0
      of the query must match segment 0 of the key.

    Within each tier, results preserve candidate iteration order
    and are deduped on object identity (so a candidate matched via
    multiple of its own keys appears once in the tier).

    Returns an empty :class:`FuzzyResult` for empty / whitespace-
    only query, queries that produce empty tokens (malformed
    paths), and queries that no tier matches.
    """
    if not query:
        return FuzzyResult()
    q = query.strip().lower()
    if not q:
        return FuzzyResult()

    q_tokens = tokenizer(q)
    if not q_tokens or any(not t for t in q_tokens):
        return FuzzyResult()

    # Materialize the candidate iterable once so we can re-scan it
    # across passes; pre-compute lowercased keys + their tokens so
    # tokenization happens once per candidate, not once per pass.
    pool: List[T] = list(candidates)
    key_data: List[Sequence[tuple]] = []
    for c in pool:
        rows = []
        for k in keys(c):
            # Skip empty / falsy keys so a candidate with a None
            # name (rare, but possible for partially-hydrated
            # fixtures) doesn't crash ``.lower()``. The candidate
            # remains in the pool with whatever non-empty keys it
            # does have.
            if not k:
                continue
            kl = k.lower()
            rows.append((kl, tokenizer(kl)))
        key_data.append(rows)

    # Tier 1 — exact whole-string equality against any key.
    exact_hits = _dedup_in_order(
        [
            c for c, rows in zip(pool, key_data)
            if any(kl == q for kl, _ in rows)
        ]
    )
    exact_set = {id(c) for c in exact_hits}

    if strategy == "unordered":
        def matches_under(primitive, k_tokens) -> bool:
            return all(
                any(primitive(qt, kt) for kt in k_tokens)
                for qt in q_tokens
            )
    else:  # positional
        def matches_under(primitive, k_tokens) -> bool:
            if len(q_tokens) > len(k_tokens):
                return False
            return all(primitive(qt, kt) for qt, kt in zip(q_tokens, k_tokens))

    def pass_for(primitive, exclude_ids: set) -> List[T]:
        return [
            c for c, rows in zip(pool, key_data)
            if id(c) not in exclude_ids
            and any(matches_under(primitive, kt) for _, kt in rows)
        ]

    # Tier 2 — prefix per token, excluding anything already in exact
    # so the tier-list invariant (non-overlapping) holds.
    prefix_hits = _dedup_in_order(pass_for(is_prefix, exact_set))
    prefix_set = exact_set | {id(c) for c in prefix_hits}

    # Tier 3 — substring, excluding everything stricter.
    substring_hits = _dedup_in_order(pass_for(is_substring, prefix_set))
    substring_set = prefix_set | {id(c) for c in substring_hits}

    # Tier 4 — opt-in edit-distance-or-prefix, excluding everything
    # stricter so a candidate that already qualified via prefix
    # doesn't double-count here.
    edit_hits: List[T] = []
    if edit_distance:
        def edit_or_prefix(qt: str, kt: str) -> bool:
            return is_prefix(qt, kt) or is_within_one_edit(qt, kt)
        edit_hits = _dedup_in_order(
            pass_for(edit_or_prefix, substring_set)
        )

    return FuzzyResult(
        exact=exact_hits,
        prefix=prefix_hits,
        substring=substring_hits,
        edit_distance=edit_hits,
    )


def _dedup_in_order(items: Iterable[T]) -> List[T]:
    """Order-preserving identity-based dedup. Used by
    :func:`fuzzy_match` so a candidate matched via multiple keys
    appears once in the result."""
    seen = set()
    out: List[T] = []
    for item in items:
        marker = id(item)
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out
