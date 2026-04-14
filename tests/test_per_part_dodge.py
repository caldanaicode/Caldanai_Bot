"""Tests for per-part dodge scaling by exposure.

When a player explicitly targets a body part, the dodge check for that
attack is scaled inversely by the part's exposure for the attack's
reach. Random targeting keeps base dodge (the exposure tax is already
applied via weighted part selection).
"""

from unittest.mock import patch

import pytest

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures import Creature, EXPOSURE_FLOOR
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import Reach


def _make_creature(name="mob", atk="1d4", defense=0, dodge=8,
                   health_max=100, body_parts=None):
    c = Creature(name=name, atk=atk, defense=defense, dodge=dodge,
                 health_max=health_max)
    if body_parts:
        c.body_parts = body_parts
    return c


def _make_part(name="torso", health_max=50, is_critical=False,
               exposure=None, traits=None):
    return BodyPart(
        name=name,
        health_max=health_max,
        is_critical=is_critical,
        exposure=exposure,
        traits=traits,
    )


def _full_exposure():
    return {
        Reach.MELEE:  1.0,
        Reach.REACH:  1.0,
        Reach.THROWN: 1.0,
        Reach.RANGED: 1.0,
    }


class TestExplicitTargetScalesDodge:
    def test_explicit_target_scales_dodge_by_exposure(self):
        """Part with MELEE exposure 0.05 when base dodge is 8:
        effective_dodge = 8 / 0.05 = 160. A roll of 160 hits; 159 misses."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.05
        hard_part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[hard_part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        # Force attack roll to 160 → hit
        with patch.object(
            NaturalAttackSource, "make_attack_rolls",
            autospec=True,
        ) as m:
            def _rolls(self_src, attacker_):
                from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
                from caldanai.lib.rpg.helpers.dice import Dice
                atk = AttackRoll(skill_bonus=0)
                atk.rolls = (10,)
                atk.result = 160
                atk.isCritical = False
                atk.isFumble = False
                dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
                dmg.rolls = (4,)
                dmg.result = 4
                return atk, dmg
            m.side_effect = _rolls

            seq = attacker.do_attack(target, explicit_part_names=["torso"])
            assert not seq.results[0].combined.isMiss

            # Now force attack roll to 159 → miss
            def _rolls_miss(self_src, attacker_):
                from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
                from caldanai.lib.rpg.helpers.dice import Dice
                atk = AttackRoll(skill_bonus=0)
                atk.rolls = (10,)
                atk.result = 159
                atk.isCritical = False
                atk.isFumble = False
                dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
                dmg.rolls = (4,)
                dmg.result = 4
                return atk, dmg
            m.side_effect = _rolls_miss

            seq2 = attacker.do_attack(target, explicit_part_names=["torso"])
            assert seq2.results[0].combined.isMiss


class TestRandomTargetUsesBaseDodge:
    def test_random_target_uses_base_dodge(self):
        """Without explicit_part_names, dodge in the AttackResult is the
        base get_dodge() value, NOT the exposure-boosted value."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.1
        part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        seq = attacker.do_attack(target, explicit_part_names=None)
        assert seq.results[0].dodge == target.get_dodge()


class TestNat20HitsRegardless:
    def test_nat_20_hits_regardless_of_effective_dodge(self):
        """A natural 20 should hit even against an obscene effective
        dodge driven by a very low-exposure explicit target."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.05
        hard_part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[hard_part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        with patch.object(
            NaturalAttackSource, "make_attack_rolls",
            autospec=True,
        ) as m:
            def _rolls(self_src, attacker_):
                from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
                from caldanai.lib.rpg.helpers.dice import Dice
                atk = AttackRoll(skill_bonus=0)
                atk.rolls = (20,)
                atk.result = 20  # nat 20 result well below effective dodge (160)
                atk.isCritical = True
                atk.isFumble = False
                dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
                dmg.rolls = (4,)
                dmg.result = 4
                return atk, dmg
            m.side_effect = _rolls

            seq = attacker.do_attack(target, explicit_part_names=["torso"])
            assert not seq.results[0].combined.isMiss
            assert seq.results[0].combined.isCritical


class TestExposureFloor:
    def test_exposure_floor_prevents_division(self):
        """With exposure 0.0 for MELEE, effective_dodge = base / 0.05
        (floor applied), not infinity / division error."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.0
        zero_part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[zero_part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        expected = int(8 / max(EXPOSURE_FLOOR, 0.0))  # 8 / 0.05 = 160

        with patch.object(
            NaturalAttackSource, "make_attack_rolls",
            autospec=True,
        ) as m:
            def _rolls(self_src, attacker_):
                from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
                from caldanai.lib.rpg.helpers.dice import Dice
                atk = AttackRoll(skill_bonus=0)
                atk.rolls = (10,)
                atk.result = expected  # exactly meets effective dodge → hit
                atk.isCritical = False
                atk.isFumble = False
                dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
                dmg.rolls = (4,)
                dmg.result = 4
                return atk, dmg
            m.side_effect = _rolls

            seq = attacker.do_attack(target, explicit_part_names=["torso"])
            assert seq.results[0].dodge == expected
            assert not seq.results[0].combined.isMiss


class TestDestroyedExplicitTargetFallbackNoBoost:
    def test_destroyed_explicit_target_falls_back_no_boost(self):
        """When the explicit target is destroyed, the system falls back
        to pick_random_part and uses base dodge (no exposure boost)."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.05
        destroyed_part = _make_part("head", 10, exposure=exposure, is_critical=False)
        destroyed_part.health = 0  # destroyed
        other = _make_part("torso", 50, exposure=_full_exposure())
        target = _make_creature("target", dodge=8, body_parts=[destroyed_part, other])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        seq = attacker.do_attack(target, explicit_part_names=["head"])
        # Fallback should NOT boost dodge.
        assert seq.results[0].dodge == target.get_dodge()
