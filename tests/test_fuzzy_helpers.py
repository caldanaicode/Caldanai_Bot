"""Unit tests for the per-pair fuzzy-match primitives in
:mod:`caldanai.lib.rpg.helpers.fuzzy`.

These primitives are case-sensitive — callers normalize before
calling — so tests pass lowercase strings throughout.
"""

import pytest

from caldanai.lib.rpg.helpers.fuzzy import (
    FuzzyResult,
    _levenshtein_le_1,
    dot_segments,
    fuzzy_match,
    is_prefix,
    is_substring,
    is_within_one_edit,
    whitespace_tokens,
)


class TestIsPrefix:
    @pytest.mark.parametrize("q,n,expected", [
        ("", "anything", True),     # empty prefix-matches everything
        ("h", "head", True),
        ("hand", "hand.left", True),  # primitive doesn't know about dots
        ("foreleg", "foreleg", True),
        ("foreleg", "fore", False),    # query longer than name
        ("z", "head", False),
    ])
    def test_basic(self, q, n, expected):
        assert is_prefix(q, n) is expected


class TestIsSubstring:
    @pytest.mark.parametrize("q,n,expected", [
        ("eye", "eye.left", True),
        ("leg", "foreleg", True),      # mid-string substring
        ("forl", "foreleg", False),    # not a contiguous substring
        ("xyz", "head", False),
        ("", "head", True),            # empty is in everything
    ])
    def test_basic(self, q, n, expected):
        assert is_substring(q, n) is expected


# ---------------------------------------------------------------------------
# Levenshtein-1 primitive — direct tests
# ---------------------------------------------------------------------------


class TestLevenshteinLE1:
    @pytest.mark.parametrize("a,b", [
        ("", ""),
        ("a", "a"),
        ("forel", "forel"),
    ])
    def test_equal_strings(self, a, b):
        assert _levenshtein_le_1(a, b) is True

    @pytest.mark.parametrize("a,b", [
        ("forl", "fore"),       # one substitution
        ("foreleg", "foreled"),  # one substitution at end
        ("apple", "appse"),      # one substitution mid
    ])
    def test_one_substitution(self, a, b):
        assert _levenshtein_le_1(a, b) is True

    @pytest.mark.parametrize("a,b", [
        ("forl", "forel"),  # one insertion
        ("apple", "aple"),   # one deletion
        ("hand", "hands"),   # trailing insertion
        ("hand", "ahand"),   # leading insertion
    ])
    def test_one_indel(self, a, b):
        assert _levenshtein_le_1(a, b) is True
        assert _levenshtein_le_1(b, a) is True  # symmetric

    @pytest.mark.parametrize("a,b", [
        ("apple", "epply"),   # two substitutions
        ("hand", "hxxxd"),    # multiple substitutions
        ("ab", "abcd"),       # length difference > 1
        ("xyz", "abc"),       # all different
    ])
    def test_distance_gt_1(self, a, b):
        assert _levenshtein_le_1(a, b) is False


# ---------------------------------------------------------------------------
# is_within_one_edit — public API
# ---------------------------------------------------------------------------


class TestIsWithinOneEdit:
    def test_typo_one_missing_char_in_query(self):
        # 'forl' is meant to be 'forel'/'foreleg' — query is one
        # char short of a valid prefix. Insertion-of-one fix.
        assert is_within_one_edit("forl", "foreleg") is True

    def test_typo_one_substituted_char(self):
        # 'fore' has 'r' substituted for the second char that would
        # match 'foeleg' — query within edit-distance 1 of name's
        # 4-char prefix 'foel'... actually 'fore' doesn't typo into
        # 'foreleg' badly — it's a real prefix. Skip and use a
        # different example: 'hane' for 'hand'.
        assert is_within_one_edit("hane", "hand") is True

    def test_typo_one_extra_char_in_query(self):
        # 'hands' targeting 'hand' — query has one extra char beyond
        # what would be a prefix.
        assert is_within_one_edit("hands", "hand") is True

    def test_min_query_length_blocks_short_queries(self):
        # 'a' is 1 char — under default min_query_len=3, can't fuzzy
        # match anything (would smear over too many parts).
        assert is_within_one_edit("a", "arm") is False
        assert is_within_one_edit("ab", "arm") is False

    def test_min_query_length_threshold_inclusive(self):
        # Exactly 3 chars passes the min.
        assert is_within_one_edit("foo", "foo") is True

    def test_distance_2_does_not_match(self):
        # Two missing chars — out of one-edit reach.
        assert is_within_one_edit("frl", "foreleg") is False

    def test_query_longer_than_name_plus_one_no_match(self):
        # 'foreleggi' is two chars beyond 'foreleg' — out of reach.
        assert is_within_one_edit("foreleggi", "foreleg") is False

    def test_exact_match(self):
        assert is_within_one_edit("foreleg", "foreleg") is True

    def test_completely_different(self):
        assert is_within_one_edit("torso", "foreleg") is False


# ---------------------------------------------------------------------------
# Tokenizers
# ---------------------------------------------------------------------------


class TestWhitespaceTokens:
    @pytest.mark.parametrize("s,expected", [
        ("flying math teacher", ["flying", "math", "teacher"]),
        ("flying_math_teacher", ["flying", "math", "teacher"]),
        ("flying.math.teacher", ["flying", "math", "teacher"]),
        ("flying_math.teacher", ["flying", "math", "teacher"]),
        ("  spaced  ", ["spaced"]),
        ("", []),
        ("   ", []),
        ("one", ["one"]),
    ])
    def test_basic(self, s, expected):
        assert whitespace_tokens(s) == expected


class TestDotSegments:
    @pytest.mark.parametrize("s,expected", [
        ("leg.left", ["leg", "left"]),
        ("head", ["head"]),
        ("eye.left.outer", ["eye", "left", "outer"]),
        # Empty segments survive so the resolver can reject malformed paths.
        ("leg.", ["leg", ""]),
        (".left", ["", "left"]),
        ("a..b", ["a", "", "b"]),
        ("", []),
        ("   ", []),
    ])
    def test_basic(self, s, expected):
        assert dot_segments(s) == expected


# ---------------------------------------------------------------------------
# fuzzy_match resolver
# ---------------------------------------------------------------------------


class _Named:
    """Minimal candidate fixture for the resolver tests — just a
    ``name`` attribute and an optional ``aliases`` list."""

    def __init__(self, name, aliases=()):
        self.name = name
        self.aliases = list(aliases)

    def __repr__(self):
        return f"_Named({self.name!r})"


def _name_only(c):
    return [c.name]


def _name_and_aliases(c):
    return [c.name, *c.aliases]


class TestFuzzyMatchEmptyAndDegenerate:
    def test_empty_query_returns_empty(self):
        assert fuzzy_match("", [_Named("head")], keys=_name_only) == []

    def test_whitespace_only_query_returns_empty(self):
        assert fuzzy_match("   ", [_Named("head")], keys=_name_only) == []

    def test_none_query_returns_empty(self):
        # ``None`` should be treated like an empty string by the
        # resolver, not raise.
        assert fuzzy_match(None, [_Named("head")], keys=_name_only) == []

    def test_empty_candidates_returns_empty(self):
        assert fuzzy_match("anything", [], keys=_name_only) == []

    def test_empty_token_in_query_returns_empty(self):
        # ``"leg."`` tokenizes to ``["leg", ""]`` under dot_segments;
        # the empty middle segment must short-circuit to empty rather
        # than prefix-match any sibling part.
        parts = [_Named("leg.left"), _Named("leg.right")]
        assert fuzzy_match(
            "leg.",
            parts,
            keys=_name_only,
            tokenizer=dot_segments,
            strategy="positional",
        ) == []


class TestFuzzyMatchExactPass:
    def test_exact_match_returns_single(self):
        a, b = _Named("head"), _Named("torso")
        assert fuzzy_match("head", [a, b], keys=_name_only) == [a]

    def test_exact_match_is_case_insensitive(self):
        a = _Named("Head")
        assert fuzzy_match("HEAD", [a], keys=_name_only) == [a]

    def test_exact_short_circuits_substring(self):
        # Creature with a literal ``leg`` part AND a ``foreleg`` part:
        # ``leg`` exact-matches ``leg`` and must not also drag in
        # ``foreleg`` via substring. This is the prefix-wins
        # invariant that the existing find_parts logic guarantees.
        leg = _Named("leg")
        foreleg = _Named("foreleg")
        assert fuzzy_match("leg", [leg, foreleg], keys=_name_only) == [leg]


class TestFuzzyMatchUnorderedStrategy:
    def test_two_token_query_unordered_resolves(self):
        # Tokens can appear in any order on the key side.
        teacher = _Named("flying math teacher")
        result = fuzzy_match(
            "math flying",
            [teacher],
            keys=_name_only,
        )
        assert result == [teacher]

    def test_unordered_query_more_tokens_than_key_can_still_match(self):
        # ``"math math"`` against ``"math teacher"``: each query token
        # finds SOME key token to prefix-match. Unordered semantics
        # allow it (the existing find_plugin_classes behavior).
        teacher = _Named("math teacher")
        assert fuzzy_match("math math", [teacher], keys=_name_only) == [teacher]

    def test_substring_fallback_in_unordered(self):
        # No token starts with ``eacher``, but it's a substring of
        # ``teacher`` — substring pass catches it.
        teacher = _Named("math teacher")
        result = fuzzy_match("flying eacher", [teacher], keys=_name_only)
        # Substring pass kicks in because both tokens are non-prefix.
        # ``flying`` does NOT prefix any token of ``math teacher`` —
        # this should miss prefix and rely on substring. But ``flying``
        # also isn't a substring of ``math`` or ``teacher``.
        assert result == []  # genuinely no match here

    def test_substring_pass_when_prefix_pass_empty(self):
        # ``each`` is not a prefix of either ``math`` or ``teacher``
        # but IS a substring of ``teacher``. Single-token query hits
        # substring pass after prefix pass returns empty.
        teacher = _Named("math teacher")
        assert fuzzy_match("each", [teacher], keys=_name_only) == [teacher]


class TestFuzzyMatchPositionalStrategy:
    def test_segment_aligned_prefix_match(self):
        leg_left = _Named("leg.left")
        leg_right = _Named("leg.right")
        # ``leg.r`` → ``leg.right`` only.
        result = fuzzy_match(
            "leg.r",
            [leg_left, leg_right],
            keys=_name_only,
            tokenizer=dot_segments,
            strategy="positional",
        )
        assert result == [leg_right]

    def test_query_longer_than_key_no_match_positional(self):
        # ``leg.left.outer`` against a 2-segment key ``leg.left``:
        # positional strategy rejects (query has more tokens).
        leg = _Named("leg.left")
        result = fuzzy_match(
            "leg.left.outer",
            [leg],
            keys=_name_only,
            tokenizer=dot_segments,
            strategy="positional",
        )
        assert result == []

    def test_segment_substring_fallback(self):
        # On a werewolf-like creature with foreleg/hindleg parts,
        # ``l.l`` should reach all four legs via segment-substring
        # fallback after segment-prefix returns empty.
        parts = [
            _Named("foreleg.left"),
            _Named("foreleg.right"),
            _Named("hindleg.left"),
            _Named("hindleg.right"),
        ]
        result = fuzzy_match(
            "l.l",
            parts,
            keys=_name_only,
            tokenizer=dot_segments,
            strategy="positional",
        )
        # ``l`` is a substring of both ``foreleg`` and ``hindleg``;
        # ``l`` is a substring of ``left`` (and the second segment of
        # the right-side parts is ``right``, which contains no ``l``).
        # Wait — "right" does NOT contain "l". Confirmed: only the
        # two ``.left`` parts match.
        assert set(result) == {parts[0], parts[2]}

    def test_edit_distance_pass_when_enabled(self):
        # ``forl.r`` typo → ``foreleg.right`` via edit-distance on
        # segment 0 + prefix on segment 1.
        target = _Named("foreleg.right")
        other = _Named("hindleg.right")
        result = fuzzy_match(
            "forl.r",
            [target, other],
            keys=_name_only,
            tokenizer=dot_segments,
            strategy="positional",
            edit_distance=True,
        )
        assert result == [target]

    def test_edit_distance_disabled_by_default(self):
        # Same query, no edit_distance — typo doesn't resolve.
        target = _Named("foreleg.right")
        result = fuzzy_match(
            "forl.r",
            [target],
            keys=_name_only,
            tokenizer=dot_segments,
            strategy="positional",
        )
        assert result == []


class TestFuzzyMatchAliases:
    def test_alias_resolves_when_primary_name_does_not(self):
        hydra = _Named("hydra", aliases=["swamp hydra", "hexed hydra"])
        result = fuzzy_match(
            "swamp",
            [hydra],
            keys=_name_and_aliases,
        )
        assert result == [hydra]

    def test_dedup_when_query_matches_multiple_keys_of_one_candidate(self):
        # ``hydra`` exact-matches the primary name AND prefix-matches
        # ``swamp hydra`` and ``hexed hydra``. Result must be one
        # entry, not three.
        hydra = _Named("hydra", aliases=["swamp hydra", "hexed hydra"])
        result = fuzzy_match(
            "hydra",
            [hydra],
            keys=_name_and_aliases,
        )
        assert result == [hydra]


class TestFuzzyMatchOrderAndDedup:
    def test_preserves_iteration_order(self):
        a = _Named("alpha")
        b = _Named("beta")
        c = _Named("alphabet")
        # ``alph`` prefix-matches both ``alpha`` and ``alphabet``.
        result = fuzzy_match("alph", [a, b, c], keys=_name_only)
        assert result == [a, c]

    def test_dedup_across_repeated_candidates(self):
        # If the candidate iterable repeats the same object, dedup
        # collapses it.
        a = _Named("head")
        result = fuzzy_match("head", [a, a, a], keys=_name_only)
        assert result == [a]


# ---------------------------------------------------------------------------
# FuzzyResult — tier introspection + list-compat shim
# ---------------------------------------------------------------------------


class TestFuzzyResultTiers:
    """Tier-aware return shape — caller can reach for ``.tightest``
    (strict prioritization, the default view) or ``.all`` (union),
    or introspect individual tiers for "did you mean..." UX."""

    def test_exact_match_lands_only_in_exact_tier(self):
        # Tiers are non-overlapping — a candidate that exact-matches
        # is NOT also listed in prefix/substring even though it
        # technically prefix/substring-matches itself. Keeps the
        # ``.tightest`` short-circuit honest.
        a = _Named("wand")
        b = _Named("magic_wand")
        result = fuzzy_match("wand", [a, b], keys=_name_only)
        assert result.exact == [a]
        # ``magic_wand`` tokenizes to ['magic', 'wand'] under the
        # default whitespace_tokens (splits on ``_``); query token
        # ``wand`` prefix-matches the second key token, so
        # magic_wand lands in the prefix tier — NOT substring.
        # The non-overlap rule keeps ``a`` out of prefix even
        # though it technically prefix-matches itself.
        assert result.prefix == [b]
        assert result.substring == []
        assert result.edit_distance == []

    def test_tightest_returns_exact_when_present(self):
        a = _Named("wand")
        b = _Named("magic_wand")
        result = fuzzy_match("wand", [a, b], keys=_name_only)
        # Strict prioritization view: exact wins, substring matches
        # are suppressed in this view.
        assert result.tightest == [a]

    def test_tightest_falls_through_when_exact_empty(self):
        a = _Named("magic_wand")
        result = fuzzy_match("magic", [a], keys=_name_only)
        # No exact match — ``.tightest`` falls through to prefix.
        assert result.exact == []
        assert result.tightest == [a]

    def test_all_returns_union_in_tier_order(self):
        a = _Named("wand")
        b = _Named("magic_wand")
        result = fuzzy_match("wand", [a, b], keys=_name_only)
        # Union: exact first, then prefix. Both are surfaced in
        # the autocomplete view — the caller decides whether to
        # auto-resolve to ``a`` (.tightest) or list both as
        # candidates (.all).
        assert result.all == [a, b]

    def test_edit_distance_isolated_to_its_tier(self):
        a = _Named("foreleg")
        # ``forl`` is one edit from ``forel`` (a prefix of foreleg)
        # but NOT a prefix or substring of ``foreleg``.
        result = fuzzy_match(
            "forl", [a], keys=_name_only,
            tokenizer=dot_segments, strategy="positional",
            edit_distance=True,
        )
        assert result.exact == []
        assert result.prefix == []
        assert result.substring == []
        assert result.edit_distance == [a]
        assert result.tightest == [a]

    def test_introspection_use_case_did_you_mean(self):
        # Caller wants to confirm fuzzy resolutions but not exact
        # ones — ``.exact`` empty + ``.tightest`` non-empty is the
        # signal.
        a = _Named("foreleg")
        result = fuzzy_match(
            "forl", [a], keys=_name_only,
            tokenizer=dot_segments, strategy="positional",
            edit_distance=True,
        )
        assert not result.exact, "exact tier empty — fuzzy resolution"
        assert result.tightest == [a]


class TestFuzzyResultListCompat:
    """List-compatible shims preserve the ergonomic shape for
    callers that just want the strict-prioritization view."""

    def test_eq_against_list_compares_tightest(self):
        a = _Named("head")
        result = fuzzy_match("head", [a], keys=_name_only)
        assert result == [a]

    def test_iter_yields_tightest(self):
        a = _Named("alpha")
        b = _Named("alphabet")
        result = fuzzy_match("alph", [a, b], keys=_name_only)
        assert list(result) == [a, b]

    def test_len_equals_tightest_len(self):
        a = _Named("alpha")
        b = _Named("alphabet")
        result = fuzzy_match("alph", [a, b], keys=_name_only)
        assert len(result) == 2

    def test_bool_truthy_when_any_match(self):
        a = _Named("head")
        assert bool(fuzzy_match("head", [a], keys=_name_only)) is True
        assert bool(fuzzy_match("nope", [a], keys=_name_only)) is False

    def test_indexable_via_tightest(self):
        a = _Named("alpha")
        b = _Named("alphabet")
        result = fuzzy_match("alph", [a, b], keys=_name_only)
        assert result[0] is a
        assert result[1] is b

    def test_in_operator_uses_tightest(self):
        a = _Named("wand")
        b = _Named("magic_wand")
        result = fuzzy_match("wand", [a, b], keys=_name_only)
        # Exact match short-circuits the substring fallback in the
        # tightest view — ``b`` is in ``.all`` but NOT in tightest.
        assert a in result
        assert b not in result
        assert b in result.all

    def test_empty_result_is_falsy(self):
        result = FuzzyResult()
        assert not result
        assert result == []
        assert list(result) == []

    def test_repr_shows_all_tiers(self):
        a = _Named("wand")
        b = _Named("magic_wand")
        result = fuzzy_match("wand", [a, b], keys=_name_only)
        r = repr(result)
        assert "exact=" in r and "prefix=" in r
        assert "substring=" in r and "edit_distance=" in r
