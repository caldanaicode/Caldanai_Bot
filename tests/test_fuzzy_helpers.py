"""Unit tests for the per-pair fuzzy-match primitives in
:mod:`caldanai.lib.rpg.helpers.fuzzy`.

These primitives are case-sensitive — callers normalize before
calling — so tests pass lowercase strings throughout.
"""

import pytest

from caldanai.lib.rpg.helpers.fuzzy import (
    _levenshtein_le_1,
    is_prefix,
    is_substring,
    is_within_one_edit,
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
