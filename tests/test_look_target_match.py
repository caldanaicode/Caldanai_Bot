"""Regression tests for ``RpgInfoCommands._monster_matches_look_target``.

Pre-2026-04-25 ``$look`` accepted only the active monster's exact
``self.name`` (case-insensitively). For variant-named creatures
(``hexed hydra``, ``flying math teacher``) the player saw the
species in spawn flavor and reached for ``$look hydra`` /
``$look hexed`` / ``$look math``, all of which silently returned
"Nothing to see here" — caught live during the 2026-04-25
hexed-hydra playtest.

The helper now matches:
- exact full-name (case-insensitive)
- any single whitespace-separated token within the name

Partial token matches (``hex`` for ``hexed hydra``) still fail —
those want the bigger fuzzy resolver shipped for ``$spawn`` (see
``project_fuzzy_monster_names``).
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


class TestNonMatch:
    def test_partial_substring_within_token_fails(self):
        """``hex`` is NOT a full token in ``hexed hydra`` so it
        shouldn't match — that level of fuzzy belongs to the
        ``find_plugin_classes`` resolver, not this helper."""
        assert _match(_monster("hexed hydra"), "hex") is False

    def test_unrelated_target_fails(self):
        assert _match(_monster("hexed hydra"), "bandit") is False

    def test_empty_target_fails(self):
        """Empty target is a degenerate case; ``"" in [...split()]``
        is False because split() never produces empty strings."""
        assert _match(_monster("hexed hydra"), "") is False

    def test_single_word_monster_still_matches_exact(self):
        assert _match(_monster("bandit"), "bandit") is True

    def test_single_word_monster_rejects_partial(self):
        assert _match(_monster("bandit"), "ban") is False
