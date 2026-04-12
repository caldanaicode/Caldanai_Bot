"""Tests for Caldanai.lib.rpg.combat.attack_source."""

from unittest.mock import MagicMock

from caldanai.lib.rpg.combat.attack_source import (
    AttackSource,
    NaturalAttackSource,
    UnarmedAttackSource,
    WeaponAttackSource,
    _get_skill_bonus,
)
from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll


def _attacker_with_skill(skill_name=None, atk_bonus=5, dmg_bonus=3):
    """Build a mock attacker whose get_skill_bonus returns a fixed tuple."""
    attacker = MagicMock()
    attacker.get_skill_bonus = MagicMock(return_value=(atk_bonus, dmg_bonus))
    return attacker


class TestUnarmedAttackSource:
    def test_produces_d4_bludgeoning(self):
        src = UnarmedAttackSource(label="Left")
        assert src.damage_type == DamageTypes.BLUDGEONING
        assert src.skill == "unarmed"
        assert src.label == "Left"

    def test_make_attack_rolls_returns_d20_and_d4(self):
        src = UnarmedAttackSource()
        attacker = _attacker_with_skill()
        atk, dmg = src.make_attack_rolls(attacker)
        assert isinstance(atk, AttackRoll)
        assert isinstance(dmg, DamageRoll)
        assert atk.sides == 20
        assert dmg.sides == 4

    def test_applies_skill_bonuses(self):
        src = UnarmedAttackSource()
        attacker = _attacker_with_skill(atk_bonus=7, dmg_bonus=4)
        atk, dmg = src.make_attack_rolls(attacker)
        assert atk.skillBonus == 7
        assert dmg.skillBonus == 4


class TestWeaponAttackSource:
    def test_uses_weapon_properties(self):
        weapon = MagicMock()
        weapon.damage_type = DamageTypes.SLASHING
        weapon.skill = "one-handed slashing"
        weapon.attack = "2d6"
        weapon.bonus = 3

        src = WeaponAttackSource(weapon, label="Right")
        assert src.damage_type == DamageTypes.SLASHING
        assert src.skill == "one-handed slashing"
        assert src.label == "Right"

    def test_make_attack_rolls_uses_weapon_dice_and_bonus(self):
        weapon = MagicMock()
        weapon.damage_type = DamageTypes.PIERCING
        weapon.skill = "two-handed piercing"
        weapon.attack = "3d8"
        weapon.bonus = 5

        src = WeaponAttackSource(weapon)
        attacker = _attacker_with_skill(atk_bonus=2, dmg_bonus=1)
        atk, dmg = src.make_attack_rolls(attacker)

        assert atk.sides == 20
        assert dmg.sides == 8
        assert dmg.weaponBonus == 5
        assert atk.skillBonus == 2
        assert dmg.skillBonus == 1


class TestNaturalAttackSource:
    def test_basic_properties(self):
        src = NaturalAttackSource(
            atk="4d6",
            dmg_type=DamageTypes.FIRE,
            label="Breath",
            skill="fire breath",
        )
        assert src.damage_type == DamageTypes.FIRE
        assert src.skill == "fire breath"
        assert src.label == "Breath"

    def test_default_skill_is_natural(self):
        src = NaturalAttackSource(atk="2d4")
        assert src.skill == "natural"
        assert src.damage_type is None
        assert src.label == ""

    def test_make_attack_rolls_uses_custom_dice(self):
        src = NaturalAttackSource(atk="5d10", dmg_type=DamageTypes.DARK)
        attacker = _attacker_with_skill(atk_bonus=0, dmg_bonus=0)
        atk, dmg = src.make_attack_rolls(attacker)
        assert atk.sides == 20
        assert dmg.sides == 10

    def test_no_weapon_bonus(self):
        src = NaturalAttackSource(atk="1d6")
        attacker = _attacker_with_skill()
        _, dmg = src.make_attack_rolls(attacker)
        assert dmg.weaponBonus == 0


class TestGetSkillBonus:
    def test_returns_zero_tuple_for_creatures_without_skill_system(self):
        attacker = MagicMock(spec=[])  # no get_skill_bonus attribute
        assert _get_skill_bonus(attacker, "anything") == (0, 0)

    def test_calls_attacker_get_skill_bonus_when_present(self):
        attacker = _attacker_with_skill(atk_bonus=10, dmg_bonus=6)
        assert _get_skill_bonus(attacker, "unarmed") == (10, 6)
        attacker.get_skill_bonus.assert_called_once_with("unarmed")


class TestBaseClass:
    def test_abstract_methods_cannot_be_instantiated(self):
        import pytest
        with pytest.raises(TypeError):
            AttackSource(label="Oops")  # type: ignore[abstract]
