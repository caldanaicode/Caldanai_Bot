"""Regression tests for ``RpgInfoCommands._monster_matches_look_target``.

Pre-2026-04-25 ``$look`` accepted only the active monster's exact
``self.name`` (case-insensitively). For variant-named creatures
(``hexed hydra``, ``flying math teacher``) the player saw the
species in spawn flavor and reached for ``$look hydra`` /
``$look hexed`` / ``$look math``, all of which silently returned
"Nothing to see here" — caught live during the 2026-04-25
hexed-hydra playtest.

The helper now matches via three passes (mirrors the ``$kill``
leading-monster-token peeler):

1. Exact full-name OR any single whitespace-separated token
   (case-insensitive).
2. Prefix-of-any-word — ``"hyd"`` matches "hexed hydra";
   ``"ban"`` matches "bandit".
3. Typo tolerance via :func:`difflib.get_close_matches` with
   cutoff 0.75 — ``"hdra"`` matches a hydra, ``"werewlf"``
   matches a werewolf.

No body-part conflict guard is needed (unlike ``$kill``) since
``$look``'s only target is the spawned monster.
"""

from types import SimpleNamespace

from caldanai.lib.cogs.rpg_info_commands import RpgInfoCommands


def _monster(name: str):
    return SimpleNamespace(name=name)


_match = RpgInfoCommands._monster_matches_look_target


class TestExactMatch:
    def test_full_name_lowercase(self):
        assert _match(_monster("hexed hydra"), "hexed hydra") is True

    def test_full_name_uppercase(self):
        assert _match(_monster("hexed hydra"), "HEXED HYDRA") is True

    def test_full_name_mixed_case(self):
        assert _match(_monster("hexed hydra"), "Hexed Hydra") is True


class TestTokenMatch:
    def test_species_token_matches_variant(self):
        assert _match(_monster("hexed hydra"), "hydra") is True

    def test_variant_token_matches_variant(self):
        assert _match(_monster("hexed hydra"), "hexed") is True

    def test_first_word_matches_three_word_name(self):
        assert _match(_monster("flying math teacher"), "flying") is True

    def test_middle_word_matches_three_word_name(self):
        assert _match(_monster("flying math teacher"), "math") is True

    def test_last_word_matches_three_word_name(self):
        assert _match(_monster("flying math teacher"), "teacher") is True


class TestPrefixMatch:
    """Pass 2 — prefix-of-any-word. Catches abbreviated reaches
    like ``$look hyd`` and ``$look ske`` that the prior word-token
    rule rejected."""

    def test_prefix_of_species_word_matches_variant(self):
        """``hyd`` is a prefix of ``hydra`` in ``hexed hydra``."""
        assert _match(_monster("hexed hydra"), "hyd") is True

    def test_prefix_of_variant_word_matches_variant(self):
        """``hex`` is a prefix of ``hexed`` in ``hexed hydra``."""
        assert _match(_monster("hexed hydra"), "hex") is True

    def test_prefix_of_single_word_monster(self):
        """``ske`` is a prefix of ``skeleton``."""
        assert _match(_monster("skeleton"), "ske") is True

    def test_longer_prefix_of_single_word_monster(self):
        """``skele`` is also a prefix of ``skeleton``."""
        assert _match(_monster("skeleton"), "skele") is True

    def test_prefix_of_bandit_matches(self):
        assert _match(_monster("bandit"), "ban") is True


class TestTypoMatch:
    """Pass 3 — :func:`difflib.get_close_matches` with cutoff 0.75
    against the full name and each word."""

    def test_typo_dropped_letter_matches_species(self):
        """``hdra`` (dropped ``y``) → "hydra" via difflib."""
        assert _match(_monster("hexed hydra"), "hdra") is True

    def test_typo_in_single_word_monster(self):
        """``werewlf`` (dropped ``o``) → "werewolf" via difflib."""
        assert _match(_monster("werewolf"), "werewlf") is True


class TestNonMatch:
    def test_unrelated_target_fails(self):
        assert _match(_monster("hexed hydra"), "bandit") is False

    def test_empty_target_fails(self):
        """Empty target is a degenerate case; the helper now
        explicitly returns ``False`` rather than relying on
        ``"" in [...split()]``."""
        assert _match(_monster("hexed hydra"), "") is False

    def test_single_word_monster_still_matches_exact(self):
        assert _match(_monster("bandit"), "bandit") is True

    def test_outright_nonsense_rejects(self):
        """``xyz`` shares nothing with any word in the monster's
        name, so neither prefix nor difflib (cutoff 0.75) accept
        it."""
        assert _match(_monster("hexed hydra"), "xyz") is False
        assert _match(_monster("bandit"), "xyz") is False
        assert _match(_monster("werewolf"), "xyz") is False
