"""Tests for :meth:`Creature.matches_token`.

The helper is the shared spawned-monster name matcher behind
``$kill`` (leading-token peel) and ``$look`` (single-target match).
``test_kill_command_grammar.py`` and ``test_look_target_match.py``
exercise the integrated behavior at each call site; this module
pins the helper's resolution order and edge cases directly so the
contract has a single, focused home.

Resolution order under test:

1. Exact / word-token (case-insensitive) — always wins, even when
   ``conflict_check`` would otherwise fire.
2. Pre-fuzzy ``conflict_check`` guard — bails the prefix + difflib
   passes only.
3. Prefix-of-any-word.
4. :func:`difflib.get_close_matches` with cutoff 0.75.
"""

from caldanai.lib.rpg.creatures import Creature


def _creature(name: str) -> Creature:
    return Creature(
        name=name, atk="1d4", defense=2, dodge=5, health_max=10,
    )


# ---------------------------------------------------------------------------
# Pass 1 — exact / word-token (always wins)
# ---------------------------------------------------------------------------


class TestExactMatch:
    def test_exact_full_name(self):
        assert _creature("hexed hydra").matches_token("hexed hydra") is True

    def test_word_token_against_multi_word_name(self):
        assert _creature("hexed hydra").matches_token("hydra") is True

    def test_exact_match_wins_over_conflict_check(self):
        """Exact / word-token always wins. A ``conflict_check`` that
        returns truthy MUST NOT shadow an exact match — the token
        is unambiguous regardless of competing interpretations.
        This pins today's ``$kill`` behavior: a token equal to a
        word in the monster name AND accepted by ``find_parts``
        still consumes."""
        c = _creature("hydra")
        assert (
            c.matches_token("hydra", conflict_check=lambda t: ["fake-part"])
            is True
        )


# ---------------------------------------------------------------------------
# Pass 3 — prefix-of-any-word
# ---------------------------------------------------------------------------


class TestPrefixMatch:
    def test_prefix_of_word_in_multi_word_name(self):
        assert _creature("hexed hydra").matches_token("hyd") is True

    def test_prefix_against_single_word_name(self):
        assert _creature("bandit").matches_token("ban") is True

    def test_prefix_blocked_by_conflict_check(self):
        """Prefix path bails when ``conflict_check`` fires. Mirrors
        ``$kill h`` against a hydra: ``find_parts('h')`` returns
        ``[head]`` so the fuzzy peel is suppressed."""
        c = _creature("hydra")
        assert (
            c.matches_token("hyd", conflict_check=lambda t: ["fake-part"])
            is False
        )


# ---------------------------------------------------------------------------
# Pass 4 — difflib typo tolerance
# ---------------------------------------------------------------------------


class TestDifflibMatch:
    def test_typo_against_single_word_name(self):
        """Dropped letter — ``hdra`` resolves to ``hydra``."""
        assert _creature("hydra").matches_token("hdra") is True

    def test_typo_against_word_in_multi_word_name(self):
        """``hdra`` against "hexed hydra" — difflib matches the
        ``hydra`` word."""
        assert _creature("hexed hydra").matches_token("hdra") is True

    def test_difflib_blocked_by_conflict_check(self):
        """Difflib path also bails when ``conflict_check`` fires."""
        c = _creature("hydra")
        assert (
            c.matches_token("hdra", conflict_check=lambda t: ["fake-part"])
            is False
        )


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_token_returns_false(self):
        assert _creature("hydra").matches_token("") is False

    def test_empty_name_returns_false(self):
        assert _creature("").matches_token("hydra") is False

    def test_nonsense_token_returns_false(self):
        """``xyz`` shares nothing with ``hexed hydra`` — neither
        prefix nor difflib (cutoff 0.75) accept it."""
        assert _creature("hexed hydra").matches_token("xyz") is False
