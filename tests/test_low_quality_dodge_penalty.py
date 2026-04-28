"""Regression tests for the low-quality armor dodge penalty.

When armor of ORDINARY quality or below is worn, the wearer takes
a small dodge hit. Heavy/structural pieces (chest, upper-arm,
upper-leg, shin) carry the penalty; small pieces (gloves, hoods,
caps, bracers, boots, decorative bands) leave it at 0. FINE+
quality pieces are well-fitted and skip the penalty regardless.

The penalty applies globally (not per-part) — see the comment on
``effective_defense_for_part`` in ``creatures/__init__.py``:
"armor slows the whole creature down, not just the armored part."
"""

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory import Inventory
from caldanai.lib.rpg.inventory.equipment.armor import Armor


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _player_with(*plugin_quality_pairs):
    """Build a player and load each (plugin_name, quality_str) item.

    Mirrors ``test_destroyed_part_drops_gear._player_with_inventory``
    but takes (plugin, quality) tuples so we can vary quality
    per-piece.
    """
    p = Player(uid=1, gid=2, cid=3)
    items = []
    for plugin_name, quality_str in plugin_quality_pairs:
        item = Inventory.load_item(
            data={"plugin": plugin_name, "quality": quality_str},
        )
        p.inventory.add(item)
        items.append(item)
    return p, items


# ---------------------------------------------------------------------------
# Class-attribute defaults and per-piece overrides
# ---------------------------------------------------------------------------


class TestArmorDodgePenaltyClassAttr:
    def test_armor_base_default_is_zero(self):
        """Pieces that don't override the attr stay at 0."""
        assert Armor.LOW_QUALITY_DODGE_PENALTY == 0

    @pytest.mark.parametrize(
        "plugin,expected",
        [
            ("rough_jerkin", 2),     # heavy chest — biggest tax
            ("rough_rerebrace", 1),  # heavy upper-arm plate
            ("rough_greave", 1),     # heavy upper-leg
            ("scrap_shin", 1),       # heavy shin wrap
            ("leather_jerkin", 1),   # light-class chest still carries some bulk
        ],
    )
    def test_heavy_pieces_have_penalty(self, plugin, expected):
        item = Inventory.load_item(data={"plugin": plugin, "quality": "ORDINARY"})
        assert item.LOW_QUALITY_DODGE_PENALTY == expected

    @pytest.mark.parametrize(
        "plugin",
        [
            "patchwork_bracer",
            "ratty_glove",
            "worn_boot",
            "rough_cap",
            "rag_hood",
            "scrap_collar",
            "bandits_sash",
            "mushroom_hat",
            "leather_cap",
            "leather_bracer",
            "leather_glove",
            "leather_boot",
            "leather_greave",
        ],
    )
    def test_light_pieces_no_penalty(self, plugin):
        """Small pieces don't tax mobility regardless of quality."""
        item = Inventory.load_item(data={"plugin": plugin, "quality": "ORDINARY"})
        assert item.LOW_QUALITY_DODGE_PENALTY == 0


# ---------------------------------------------------------------------------
# Player.get_dodge applies penalty only at quality multiplier <= 1.0
# ---------------------------------------------------------------------------


class TestPlayerDodgePenaltyApplication:
    def test_no_armor_no_penalty(self):
        p, _ = _player_with()
        assert p._low_quality_dodge_penalty() == 0

    def test_junk_jerkin_subtracts_two(self):
        p, (jerkin,) = _player_with(("rough_jerkin", "JUNK"))
        baseline = p.get_dodge()
        p.equip(jerkin)
        assert p.get_dodge() == baseline - 2

    def test_ordinary_jerkin_subtracts_two(self):
        p, (jerkin,) = _player_with(("rough_jerkin", "ORDINARY"))
        baseline = p.get_dodge()
        p.equip(jerkin)
        assert p.get_dodge() == baseline - 2

    @pytest.mark.parametrize(
        "quality_str", ["FINE", "QUALITY", "SUPERIOR", "MASTERWORK"]
    )
    def test_high_quality_jerkin_no_penalty(self, quality_str):
        """Pieces of FINE+ are fitted well enough to skip the tax."""
        p, (jerkin,) = _player_with(("rough_jerkin", quality_str))
        baseline = p.get_dodge()
        p.equip(jerkin)
        # Note: high-quality armor may also CARRY a positive dodge bonus
        # if the piece declares one. The scrap pieces don't, so the
        # only difference here is the absence of the penalty — dodge
        # equals baseline.
        assert p.get_dodge() == baseline

    def test_full_low_quality_kit_sums(self):
        """jerkin (2) + rerebrace (1) + greave (1) + shin (1) = 5 dodge cost."""
        p, items = _player_with(
            ("rough_jerkin", "ORDINARY"),
            ("rough_rerebrace", "ORDINARY"),
            ("rough_greave", "ORDINARY"),
            ("scrap_shin", "ORDINARY"),
        )
        baseline = p.get_dodge()
        for item in items:
            p.equip(item)
        assert p._low_quality_dodge_penalty() == 5
        assert p.get_dodge() == max(0, baseline - 5)

    def test_dodge_clamped_at_zero(self):
        """If penalty exceeds base, dodge bottoms out at 0 (not negative)."""
        # Stack enough heavy junk to bury the baseline.
        p, items = _player_with(
            ("rough_jerkin", "JUNK"),
            ("rough_rerebrace", "JUNK"),
            ("rough_greave", "JUNK"),
            ("scrap_shin", "JUNK"),
        )
        for item in items:
            p.equip(item)
        assert p.get_dodge() >= 0

    def test_mixed_quality_only_low_penalize(self):
        """Junk rerebrace penalizes; fine rerebrace on the other arm doesn't.

        Two arm-plate placements share the ARMS slot, so we equip
        one to each side via explicit-side equip if supported; the
        simpler test is junk jerkin (penalty) + fine greave (no
        penalty) — different placements, same quality differentiation.
        """
        p, (jerkin, greave) = _player_with(
            ("rough_jerkin", "JUNK"),
            ("rough_greave", "FINE"),
        )
        baseline = p.get_dodge()
        p.equip(jerkin)
        p.equip(greave)
        # Only the junk jerkin (penalty 2) counts; fine greave skips.
        assert p._low_quality_dodge_penalty() == 2
        assert p.get_dodge() == baseline - 2

    def test_leather_jerkin_low_quality_penalizes(self):
        """Crafted leather isn't immune — quality is the gate."""
        p, (lj,) = _player_with(("leather_jerkin", "JUNK"))
        baseline = p.get_dodge()
        p.equip(lj)
        assert p.get_dodge() == baseline - 1

    def test_leather_jerkin_fine_no_penalty(self):
        p, (lj,) = _player_with(("leather_jerkin", "FINE"))
        baseline = p.get_dodge()
        p.equip(lj)
        assert p.get_dodge() == baseline

    def test_leather_greave_no_penalty_at_any_quality(self):
        """Light-class small pieces stay at 0 even when junk."""
        p, (lg,) = _player_with(("leather_greave", "JUNK"))
        baseline = p.get_dodge()
        p.equip(lg)
        assert p.get_dodge() == baseline
