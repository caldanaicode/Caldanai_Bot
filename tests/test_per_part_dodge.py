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
        """Part with MELEE exposure 0.05 (below EXPOSURE_FLOOR=0.3):
        ``effective_dodge = base * size_ratio / FLOOR = 8 * 1.0 / 0.3 = 26``
        for same-size (MEDIUM v MEDIUM) attacker/target. A roll equal to
        effective_dodge hits; one less misses."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.05  # will be floored to EXPOSURE_FLOOR
        hard_part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[hard_part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        # Same-size ratio = 1.0, exposure floored to 0.3.
        expected = int(8 * 1.0 / EXPOSURE_FLOOR)

        # Force attack roll to exactly match effective dodge → hit
        with patch.object(
            NaturalAttackSource, "make_attack_rolls",
            autospec=True,
        ) as m:
            def _rolls(self_src, attacker_):
                from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
                from caldanai.lib.rpg.helpers.dice import Dice
                atk = AttackRoll(skill_bonus=0)
                atk.rolls = (10,)
                atk.result = expected
                atk.isCritical = False
                atk.isFumble = False
                dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
                dmg.rolls = (4,)
                dmg.result = 4
                return atk, dmg
            m.side_effect = _rolls

            seq = attacker.do_attack(target, explicit_part_names=["torso"])
            assert not seq.results[0].combined.isMiss

            # One less than effective → miss
            def _rolls_miss(self_src, attacker_):
                from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
                from caldanai.lib.rpg.helpers.dice import Dice
                atk = AttackRoll(skill_bonus=0)
                atk.rolls = (10,)
                atk.result = expected - 1
                atk.isCritical = False
                atk.isFumble = False
                dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
                dmg.rolls = (4,)
                dmg.result = 4
                return atk, dmg
            m.side_effect = _rolls_miss

            seq2 = attacker.do_attack(target, explicit_part_names=["torso"])
            assert seq2.results[0].combined.isMiss


class TestRandomTargetAlsoGetsTargetedDodge:
    """Random targeting pays the same targeted-dodge tax as explicit
    targeting. The tax lives with the *target part*, not the *intent*
    — a random swing that happens to land on an eye should be just as
    hard to connect as a deliberate eye-poke. Otherwise blind swinging
    paradoxically hits low-exposure parts *easier* than deliberate
    targeting."""

    def test_random_pick_uses_targeted_dodge(self):
        """A single-part target with low MELEE exposure: random pick
        is forced (only option), and dodge math applies the same as
        explicit targeting."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.1
        part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        seq = attacker.do_attack(target, explicit_part_names=None)
        # Exposure 0.1 → floored to 0.3; same-size ratio 1.0.
        # Effective = 8 * 1.0 / 0.3 = 26.
        assert seq.results[0].dodge == 26

    def test_random_pick_fully_exposed_part_equals_base_dodge(self):
        """Full exposure (1.0) → no dodge scaling → effective dodge
        matches base. Confirms the math degenerates cleanly when
        there's no exposure tax to apply."""
        part = _make_part("torso", 50, exposure=_full_exposure())
        target = _make_creature("target", dodge=8, body_parts=[part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")
        seq = attacker.do_attack(target, explicit_part_names=None)
        assert seq.results[0].dodge == 8


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
        """With exposure 0.0 for MELEE, ``max(EXPOSURE_FLOOR, 0.0)``
        clamps the divisor to ``EXPOSURE_FLOOR``, keeping effective
        dodge finite."""
        exposure = _full_exposure()
        exposure[Reach.MELEE] = 0.0
        zero_part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=8, body_parts=[zero_part])
        target.get_dodge = lambda: 8
        attacker = _make_creature("attacker", atk="1d4")

        # Same-size (MEDIUM v MEDIUM) ratio = 1.0.
        expected = int(8 * 1.0 / max(EXPOSURE_FLOOR, 0.0))

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


class TestCrossSizeDodgeRatio:
    """The attacker/target size ratio modulates explicit-target dodge
    math. A TINY attacker targeting a MEDIUM creature has an easier
    time than a MEDIUM attacker targeting the same MEDIUM creature; a
    MEDIUM attacker targeting a TINY creature pays extra. Ratio is
    clamped so extreme mismatches (pixie vs colossal) don't obliterate
    the math."""

    def _setup_pair(self, attacker_size, target_size, exposure_val=1.0, base_dodge=10):
        from caldanai.lib.rpg.helpers.enums import Size
        exposure = _full_exposure()
        exposure[Reach.MELEE] = exposure_val
        part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=base_dodge, body_parts=[part])
        target.get_dodge = lambda: base_dodge
        target.size = target_size
        attacker = _make_creature("attacker", atk="1d4")
        attacker.size = attacker_size
        return attacker, target

    def test_smaller_attacker_gets_lower_effective_dodge(self):
        """TINY vs MEDIUM: ratio 0.5/1.0 = 0.5. Effective dodge
        ``base * 0.5 / 1.0 = 5`` (with base=10, exposure=1.0)."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._setup_pair(
            Size.TINY, Size.MEDIUM, exposure_val=1.0, base_dodge=10,
        )
        seq = attacker.do_attack(target, explicit_part_names=["torso"])
        assert seq.results[0].dodge == 5

    def test_bigger_attacker_gets_higher_effective_dodge(self):
        """MEDIUM vs TINY: ratio 1.0/0.5 = 2.0. Effective dodge
        ``base * 2.0 / 1.0 = 20``."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._setup_pair(
            Size.MEDIUM, Size.TINY, exposure_val=1.0, base_dodge=10,
        )
        seq = attacker.do_attack(target, explicit_part_names=["torso"])
        assert seq.results[0].dodge == 20

    def test_extreme_mismatch_is_clamped(self):
        """TINY vs COLOSSAL: raw ratio 0.5/1.75 ≈ 0.286, clamped up to
        0.5. Prevents pixie from trivializing a dragon."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._setup_pair(
            Size.TINY, Size.COLOSSAL, exposure_val=1.0, base_dodge=10,
        )
        seq = attacker.do_attack(target, explicit_part_names=["torso"])
        # Clamp floor is 0.5 → 10 * 0.5 / 1.0 = 5.
        assert seq.results[0].dodge == 5

    def test_extreme_mismatch_is_clamped_the_other_way(self):
        """COLOSSAL vs TINY: raw ratio 1.75/0.5 = 3.5, clamped down to
        2.0."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._setup_pair(
            Size.COLOSSAL, Size.TINY, exposure_val=1.0, base_dodge=10,
        )
        seq = attacker.do_attack(target, explicit_part_names=["torso"])
        # Clamp ceiling is 2.0 → 10 * 2.0 / 1.0 = 20.
        assert seq.results[0].dodge == 20

    def test_same_size_no_ratio_change(self):
        """MEDIUM v MEDIUM: ratio 1.0, unchanged from pre-refactor
        behavior for same-size combat (which is most of the game)."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._setup_pair(
            Size.MEDIUM, Size.MEDIUM, exposure_val=0.5, base_dodge=10,
        )
        seq = attacker.do_attack(target, explicit_part_names=["torso"])
        # 10 * 1.0 / 0.5 = 20.
        assert seq.results[0].dodge == 20


class TestGetTargetedDodgeHelper:
    """``Creature.get_targeted_dodge`` is the shared entry point for
    the explicit-target dodge math. It's called by the base
    ``do_attack`` and available for custom ``do_attack`` /
    ``attack_random`` overrides (hydra and friends) to use directly.
    """

    def test_directly_callable_from_any_context(self):
        """Signature ``(attacker, target_part, source)`` returns an int
        that callers can pass to ``resolve_attack`` as ``target_dodge``."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource

        part = _make_part("torso", 50, exposure=_full_exposure())
        target = _make_creature("target", dodge=10, body_parts=[part])
        target.get_dodge = lambda: 10
        attacker = _make_creature("attacker")

        source = NaturalAttackSource(atk="1d4", label="test")
        result = target.get_targeted_dodge(attacker, part, source)
        # 10 * 1.0 (same size) / 1.0 (full exposure) = 10.
        assert result == 10

    def test_override_is_honored_in_base_do_attack(self):
        """Monster subclasses can override ``get_targeted_dodge``; the
        base ``do_attack`` will use the override via normal method
        dispatch, no changes to the attack path required."""
        exposure = _full_exposure()
        part = _make_part("torso", 50, exposure=exposure)
        target = _make_creature("target", dodge=10, body_parts=[part])
        target.get_dodge = lambda: 10
        # Custom override: return a hardcoded "untargetable" value.
        target.get_targeted_dodge = lambda atk, p, s: 999

        attacker = _make_creature("attacker")
        seq = attacker.do_attack(target, explicit_part_names=["torso"])
        assert seq.results[0].dodge == 999

    def test_random_targeting_uses_the_helper(self):
        """Random targeting (no explicit_part_names) DOES call
        ``get_targeted_dodge`` — the tax follows the target part, not
        the intent of the attacker. Fixes the earlier asymmetry where
        a blind swinger could land an eye-shot more easily than a
        deliberate targeter."""
        from unittest.mock import MagicMock

        part = _make_part("torso", 50, exposure=_full_exposure())
        target = _make_creature("target", dodge=10, body_parts=[part])
        target.get_dodge = lambda: 10

        # Spy on get_targeted_dodge to verify it fires.
        spy = MagicMock(wraps=target.get_targeted_dodge)
        target.get_targeted_dodge = spy

        attacker = _make_creature("attacker")
        attacker.do_attack(target)  # no explicit_part_names
        spy.assert_called()
