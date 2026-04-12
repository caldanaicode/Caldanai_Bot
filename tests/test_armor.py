"""Tests for Caldanai.lib.rpg.inventory.equipment.armor.Armor class."""

import pytest
from bson.objectid import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


# ---------------------------------------------------------------------------
# Construction with bonuses dict
# ---------------------------------------------------------------------------

class TestArmorConstruction:
    def test_basic_construction(self):
        armor = Armor(
            iid=ObjectId(),
            name="iron plate",
            unit_weight=10.0,
            unit_value=50,
            quality=Qualities.ORDINARY,
            slots=EquipmentSlots.TORSO,
            bonuses={"defense": 5, "dodge": 2},
            plugin="iron_plate",
        )
        assert armor.name == "iron plate"
        assert armor.item_type == "Armor"
        assert armor.slots == EquipmentSlots.TORSO

    def test_bonuses_scaled_by_quality_multiplier(self):
        quality = Qualities.MASTERWORK  # multiplier = 2.0
        armor = Armor(
            quality=quality,
            bonuses={"defense": 10, "dodge": 4},
            plugin="test",
        )
        assert armor.bonuses["defense"] == int(10 * quality.value["multiplier"])
        assert armor.bonuses["dodge"] == int(4 * quality.value["multiplier"])

    def test_bonuses_with_ordinary_quality(self):
        quality = Qualities.ORDINARY  # multiplier = 1.0
        armor = Armor(
            quality=quality,
            bonuses={"defense": 7},
            plugin="test",
        )
        assert armor.bonuses["defense"] == 7

    def test_bonuses_empty_dict(self):
        armor = Armor(quality=Qualities.ORDINARY, bonuses={}, plugin="test")
        assert armor.bonuses == {}


# ---------------------------------------------------------------------------
# Construction with bonuses=None (regression: should not crash)
# ---------------------------------------------------------------------------

class TestArmorBonusesNone:
    def test_bonuses_none_does_not_crash(self):
        armor = Armor(
            quality=Qualities.ORDINARY,
            bonuses=None,
            plugin="test",
        )
        assert armor.bonuses == {}

    def test_bonuses_default_none(self):
        """When bonuses is omitted entirely, it defaults to None and should not crash."""
        armor = Armor(quality=Qualities.ORDINARY, plugin="test")
        assert armor.bonuses == {}


# ---------------------------------------------------------------------------
# Quality multiplier applied to bonuses
# ---------------------------------------------------------------------------

class TestQualityMultiplier:
    @pytest.mark.parametrize(
        "quality,expected_mult",
        [
            (Qualities.JUNK, 0.75),
            (Qualities.ORDINARY, 1.0),
            (Qualities.FINE, 1.25),
            (Qualities.QUALITY, 1.5),
            (Qualities.SUPERIOR, 1.75),
            (Qualities.MASTERWORK, 2.0),
        ],
    )
    def test_bonus_multiplied_correctly(self, quality, expected_mult):
        base_bonus = 10
        armor = Armor(
            quality=quality,
            bonuses={"defense": base_bonus},
            plugin="test",
        )
        assert armor.bonuses["defense"] == int(base_bonus * expected_mult)
