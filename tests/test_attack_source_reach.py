"""Tests for the ``reach`` field on ``AttackSource`` and its subclasses.

Item 1.6 of the Phase 1 body-parts plan: every attack source carries a
``Reach`` declaring how it reaches its target, defaulting to
``Reach.MELEE``. Subclasses accept a keyword-only ``reach`` override, and
the field is used downstream by body-part ``exposure`` tables to decide
how exposed a given part is to a given attack.
"""

from typing import Optional, Tuple
from unittest.mock import MagicMock

from caldanai.lib.rpg.combat.attack_source import (
    AttackSource,
    NaturalAttackSource,
    UnarmedAttackSource,
    WeaponAttackSource,
)
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll


class _ConcreteAttackSource(AttackSource):
    """Minimal concrete ``AttackSource`` for testing the abstract base class."""

    @property
    def damage_type(self) -> Optional[DamageTypes]:
        return DamageTypes.BLUDGEONING

    @property
    def skill(self) -> str:
        return "test"

    def make_attack_rolls(self, attacker) -> Tuple[AttackRoll, DamageRoll]:  # pragma: no cover
        return AttackRoll(), DamageRoll(dice=None, weapon_bonus=0, skill_bonus=0)


def _fake_weapon():
    weapon = MagicMock()
    weapon.damage_type = DamageTypes.SLASHING
    weapon.skill = "blades"
    weapon.attack = "1d6"
    weapon.bonus = 0
    return weapon


class TestAttackSourceBaseReach:
    def test_defaults_to_melee(self):
        src = _ConcreteAttackSource()
        assert src.reach == Reach.MELEE

    def test_defaults_to_melee_with_label_kwarg(self):
        src = _ConcreteAttackSource(label="Test")
        assert src.reach == Reach.MELEE
        assert src.label == "Test"

    def test_accepts_reach_override(self):
        src = _ConcreteAttackSource(reach=Reach.RANGED)
        assert src.reach == Reach.RANGED

    def test_accepts_all_reach_values(self):
        for r in (Reach.MELEE, Reach.REACH, Reach.THROWN, Reach.RANGED):
            src = _ConcreteAttackSource(reach=r)
            assert src.reach == r


class TestWeaponAttackSourceReach:
    def test_defaults_to_melee(self):
        src = WeaponAttackSource(_fake_weapon())
        assert src.reach == Reach.MELEE

    def test_accepts_reach_override(self):
        src = WeaponAttackSource(_fake_weapon(), reach=Reach.RANGED)
        assert src.reach == Reach.RANGED

    def test_backwards_compat_positional_weapon_and_label(self):
        # Pre-1.6 call sites do not pass ``reach``; they should keep working
        # and report the default.
        src = WeaponAttackSource(_fake_weapon(), label="Right")
        assert src.reach == Reach.MELEE
        assert src.label == "Right"


class TestUnarmedAttackSourceReach:
    def test_defaults_to_melee(self):
        src = UnarmedAttackSource()
        assert src.reach == Reach.MELEE

    def test_accepts_reach_override(self):
        src = UnarmedAttackSource(reach=Reach.THROWN)
        assert src.reach == Reach.THROWN

    def test_backwards_compat_label_only(self):
        src = UnarmedAttackSource(label="Left")
        assert src.reach == Reach.MELEE
        assert src.label == "Left"


class TestNaturalAttackSourceReach:
    def test_defaults_to_melee(self):
        src = NaturalAttackSource(atk="1d4")
        assert src.reach == Reach.MELEE

    def test_accepts_reach_override(self):
        src = NaturalAttackSource(atk="2d6", reach=Reach.RANGED)
        assert src.reach == Reach.RANGED

    def test_backwards_compat_full_pre_1_6_kwargs(self):
        # Mirrors existing call sites (e.g. dragon breath attack, math teacher).
        src = NaturalAttackSource(
            atk="1d4",
            dmg_type=DamageTypes.SLASHING,
            label="Claw",
            skill="natural",
        )
        assert src.reach == Reach.MELEE
        assert src.label == "Claw"
        assert src.damage_type == DamageTypes.SLASHING
        assert src.skill == "natural"
