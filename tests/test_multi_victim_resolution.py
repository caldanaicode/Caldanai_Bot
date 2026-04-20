"""Tests for ``MultiVictimResolutionResult`` + additive schema fields.

Covers the Phase 1 additive extensions that are zero-behavior-change
in the existing single-victim code path:

- ``AttackSource.intended_target`` default-None, round-trip via
  constructor.
- ``AttackResult.victim`` default-None, constructor-settable.
- ``MultiVictimResolutionResult`` empty / populated shape.
"""

from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.combat.attack_source import (
    NaturalAttackSource,
    UnarmedAttackSource,
)
from caldanai.lib.rpg.combat.resolution import (
    MultiVictimResolutionResult,
    ResolutionResult,
)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach
from caldanai.lib.rpg.helpers.roll_data import (
    AttackRoll,
    CombinedRoll,
    DamageRoll,
)


def _make_creature(name="goblin"):
    return Creature(
        name=name, atk="1d4", defense=2, dodge=5,
        health_max=20, health=20, pronouns="she, her, hers, her",
    )


def _make_result(damage=5, victim=None):
    atk = AttackRoll(skill_bonus=0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    combined = CombinedRoll(atk, dmg, dodge=5)
    source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.SLASHING, label="t")
    return AttackResult(
        source=source, combined=combined, damage=damage,
        multiplier=1.0, defense=0, dodge=5, dmg_type=DamageTypes.SLASHING,
        victim=victim,
    )


class TestAttackSourceIntendedTarget:
    def test_default_is_none(self):
        src = UnarmedAttackSource(label="left")
        assert src.intended_target is None

    def test_assignable_post_construction(self):
        target = _make_creature(name="caels")
        src = NaturalAttackSource(
            atk="1d6", dmg_type=DamageTypes.PIERCING, label="bite",
            reach=Reach.MELEE,
        )
        src.intended_target = target
        assert src.intended_target is target

    def test_backward_compat_constructor(self):
        """Existing ``NaturalAttackSource(...)`` call sites that don't
        pass ``intended_target`` keep working unchanged."""
        src = NaturalAttackSource(atk="2d4", dmg_type=DamageTypes.FIRE, label="breath")
        assert src.intended_target is None
        assert src.reach == Reach.MELEE


class TestAttackResultVictim:
    def test_default_is_none(self):
        r = _make_result(damage=4)
        assert r.victim is None

    def test_constructor_accepts_victim(self):
        victim = _make_creature(name="caels")
        r = _make_result(damage=4, victim=victim)
        assert r.victim is victim


class TestMultiVictimResolutionResult:
    def test_empty_defaults(self):
        mv = MultiVictimResolutionResult()
        assert mv.per_victim == {}
        assert mv.all_results == []
        assert mv.any_critical_part_kill is False

    def test_populated(self):
        victim_a = _make_creature(name="caels")
        victim_b = _make_creature(name="serena")
        rr_a = ResolutionResult(body_damage_total=5, num_hits=1)
        rr_b = ResolutionResult(
            body_damage_total=8, num_hits=1, critical_part_kill=True,
        )
        r_a = _make_result(damage=5, victim=victim_a)
        r_b = _make_result(damage=8, victim=victim_b)
        mv = MultiVictimResolutionResult(
            per_victim={victim_a: rr_a, victim_b: rr_b},
            all_results=[r_a, r_b],
            any_critical_part_kill=True,
        )
        assert mv.per_victim[victim_a] is rr_a
        assert mv.per_victim[victim_b] is rr_b
        assert mv.all_results == [r_a, r_b]
        assert mv.any_critical_part_kill is True

    def test_partial_population_preserves_other_defaults(self):
        mv = MultiVictimResolutionResult(any_critical_part_kill=True)
        assert mv.per_victim == {}
        assert mv.all_results == []
