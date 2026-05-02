"""Tests for recipe plugin discovery + the leather recipe set."""
import pytest

from caldanai.lib.rpg.crafting import (
    RecipePlugin,
    discover_recipes,
    get_recipe,
    list_recipes,
    RECIPES,
)


@pytest.fixture(autouse=True)
def fresh_registry():
    """Re-discover recipes each test so registry state doesn't
    leak between tests."""
    discover_recipes()


class TestDiscovery:
    def test_finds_all_leather_pieces(self):
        leather_outputs = {
            "leather_cap",
            "leather_bracer",
            "leather_glove",
            "leather_boot",
            "leather_greave",
            "leather_jerkin",
        }
        assert leather_outputs.issubset(RECIPES.keys())

    def test_get_recipe_returns_class(self):
        cls = get_recipe("leather_jerkin")
        assert cls is not None
        assert issubclass(cls, RecipePlugin)
        assert cls.output == "leather_jerkin"

    def test_get_recipe_unknown_returns_none(self):
        assert get_recipe("not_a_real_recipe") is None

    def test_list_recipes_sorted(self):
        all_outputs = [c.output for c in list_recipes()]
        assert all_outputs == sorted(all_outputs)


class TestLeatherRecipeAttributes:
    @pytest.mark.parametrize(
        "stem,expected_count",
        [
            ("leather_cap", 2),
            ("leather_bracer", 2),
            ("leather_glove", 2),
            ("leather_boot", 2),
            ("leather_greave", 4),
            ("leather_jerkin", 5),
        ],
    )
    def test_material_counts_per_size(self, stem, expected_count):
        cls = get_recipe(stem)
        assert cls is not None
        assert cls.materials == {"leather": expected_count}

    @pytest.mark.parametrize(
        "stem",
        [
            "leather_cap",
            "leather_bracer",
            "leather_glove",
            "leather_boot",
            "leather_greave",
            "leather_jerkin",
        ],
    )
    def test_all_use_leatherworking_skill(self, stem):
        cls = get_recipe(stem)
        assert cls.skill == "leatherworking"

    @pytest.mark.parametrize(
        "stem",
        [
            "leather_cap",
            "leather_bracer",
            "leather_glove",
            "leather_boot",
            "leather_greave",
            "leather_jerkin",
        ],
    )
    def test_basic_recipes_known_by_default(self, stem):
        """All MVP leather recipes are basic — no scroll required."""
        cls = get_recipe(stem)
        assert cls.requires_known is False

    def test_display_name_humanizes(self):
        cls = get_recipe("leather_jerkin")
        assert cls.display_name() == "leather jerkin"


class TestRecipePluginBase:
    def test_base_class_not_in_registry(self):
        """RecipePlugin itself shouldn't register — it has no
        output stem, and discovery skips empty output."""
        for cls in RECIPES.values():
            assert cls is not RecipePlugin

    def test_default_attrs(self):
        """Sanity check on the base-class defaults."""
        assert RecipePlugin.output == ""
        assert RecipePlugin.materials == {}
        assert RecipePlugin.skill is None
        assert RecipePlugin.min_skill == 0
        assert RecipePlugin.requires_known is False

    def test_xp_reward_defaults_tuned_2026_05_02(self):
        """Per Celowin's 2026-05-02 community feedback, the default
        per-attempt XP rewards were bumped from 5/2 to 20/5 AND
        actual grants are now scaled by player skill level via
        ``Player.gain_craft_experience`` (mirrors combat's
        ``5 + floor(5 * sqrt(level))`` with a 2× multiplier since
        crafting is material-gated).

        Math at L1, 50% success rate: success = 20 + 10 = 30,
        failure = 5, avg = 17.5 → ~57 attempts to L2 (1000 XP).
        At higher levels the sqrt scaling keeps per-level attempts
        in the 60-200 range up through L10, holding steady against
        the quadratic level-threshold curve.

        This test guards against an accidental revert; the scaling
        formula itself is tested in
        ``tests/test_player_craft_xp.py``.
        """
        assert RecipePlugin.xp_reward_success == 20
        assert RecipePlugin.xp_reward_failure == 5
