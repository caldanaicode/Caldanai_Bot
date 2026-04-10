"""Tests for Caldanai.lib.rpg.inventory.equipment.weapons.Weapon class."""

import pytest
from bson.objectid import ObjectId

from Caldanai.lib.rpg.helpers.enums import DamageTypes, EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


# ---------------------------------------------------------------------------
# Construction and properties
# ---------------------------------------------------------------------------

class TestWeaponConstruction:
    def test_basic_construction(self):
        weapon = Weapon(
            iid=ObjectId(),
            name="longsword",
            unit_weight=4.0,
            unit_value=30,
            quality=Qualities.ORDINARY,
            slots=EquipmentSlots.EITHER_HELD,
            atk="1d8",
            dmg_type=DamageTypes.SLASHING,
            plugin="longsword",
        )
        assert weapon.name == "longsword"
        assert weapon.item_type == "Weapon"
        assert weapon.attack == "1d8"
        assert weapon.damage_type == DamageTypes.SLASHING

    def test_default_attack(self):
        weapon = Weapon(quality=Qualities.ORDINARY, plugin="test")
        assert weapon.attack == "1d4"

    def test_bonus_calculated_from_dice_and_quality(self):
        quality = Qualities.MASTERWORK  # multiplier = 2.0
        weapon = Weapon(
            quality=quality,
            atk="2d6",
            plugin="test",
        )
        # dice = 2, bonus = int(2 * 2.0) = 4
        assert weapon.bonus == int(2 * quality.value["multiplier"])

    def test_explicit_bonus_overrides_calculation(self):
        weapon = Weapon(
            quality=Qualities.ORDINARY,
            atk="1d8",
            bonus=99,
            plugin="test",
        )
        assert weapon.bonus == 99

    def test_skill_string_one_handed(self):
        weapon = Weapon(
            quality=Qualities.ORDINARY,
            slots=EquipmentSlots.EITHER_HELD,
            dmg_type=DamageTypes.SLASHING,
            plugin="test",
        )
        assert "one-handed" in weapon.skill

    def test_skill_string_two_handed(self):
        weapon = Weapon(
            quality=Qualities.ORDINARY,
            slots=EquipmentSlots.TWO_HANDED,
            dmg_type=DamageTypes.BLUDGEONING,
            plugin="test",
        )
        assert "two-handed" in weapon.skill

    def test_slots_default(self):
        weapon = Weapon(quality=Qualities.ORDINARY, plugin="test")
        assert weapon.slots == EquipmentSlots.EITHER_HELD


# ---------------------------------------------------------------------------
# Damage type handling
# ---------------------------------------------------------------------------

class TestDamageType:
    def test_single_damage_type(self):
        weapon = Weapon(
            quality=Qualities.ORDINARY,
            dmg_type=DamageTypes.PIERCING,
            plugin="test",
        )
        assert weapon.damage_type == DamageTypes.PIERCING

    def test_combined_damage_type(self):
        combined = DamageTypes.SLASHING | DamageTypes.FIRE
        weapon = Weapon(
            quality=Qualities.ORDINARY,
            dmg_type=combined,
            plugin="test",
        )
        assert weapon.damage_type & DamageTypes.SLASHING
        assert weapon.damage_type & DamageTypes.FIRE

    def test_damage_type_none(self):
        weapon = Weapon(quality=Qualities.ORDINARY, plugin="test")
        assert weapon.damage_type is None

    def test_damage_type_in_skill_string(self):
        weapon = Weapon(
            quality=Qualities.ORDINARY,
            slots=EquipmentSlots.EITHER_HELD,
            dmg_type=DamageTypes.SLASHING,
            plugin="test",
        )
        assert "slashing" in weapon.skill
