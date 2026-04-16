"""Tests for item 5.0b — combat targeting wiring.

Verifies that body-part targeting flows end-to-end through ``do_attack``
and that per-result damage application works correctly with Model D
(unified body HP + part injury tracking).
"""

import random
from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures import Creature, pick_random_part
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, CombinedRoll, DamageRoll
from caldanai.lib.rpg.helpers.dice import Dice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_creature(name="goblin", atk="2d6", defense=2, dodge=5,
                   health_max=100, body_parts=None):
    """Create a Creature with optional body parts."""
    c = Creature(name=name, atk=atk, defense=defense, dodge=dodge,
                 health_max=health_max)
    if body_parts:
        c.body_parts = body_parts
    return c


def _make_part(name="torso", health_max=20, is_critical=False,
               exposure=None, traits=None):
    """Create a BodyPart with optional overrides."""
    return BodyPart(
        name=name,
        health_max=health_max,
        is_critical=is_critical,
        exposure=exposure,
        traits=traits,
    )


def _make_combined(forced_attack=15, forced_damage=6, dodge=5):
    """Build a real CombinedRoll for testing."""
    atk = AttackRoll(skill_bonus=0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    atk.rolls = (forced_attack,)
    atk.result = forced_attack
    atk.isCritical = forced_attack == 20
    atk.isFumble = forced_attack == 1
    dmg.rolls = (forced_damage,)
    dmg.result = forced_damage
    return CombinedRoll(atk, dmg, dodge)


# ---------------------------------------------------------------------------
# Test 1: do_attack picks parts on a target with body parts
# ---------------------------------------------------------------------------

class TestDoAttackPicksParts:
    def test_all_results_have_target_part(self):
        torso = _make_part("torso", 50)
        head = _make_part("head", 20, is_critical=True)
        target = _make_creature("target", health_max=200, body_parts=[torso, head])
        attacker = _make_creature("attacker", atk="1d4")

        sequence = attacker.do_attack(target)

        for result in sequence.results:
            assert result.target_part is not None
            assert result.target_part in [torso, head]


# ---------------------------------------------------------------------------
# Test 2: do_attack respects reach-weighted exposure
# ---------------------------------------------------------------------------

class TestDoAttackRespectsReach:
    def test_low_exposure_part_is_rarely_picked(self):
        """A part with 0.01 MELEE exposure should be picked far less often
        than a part with 1.0 MELEE exposure over many trials."""
        rare_part = _make_part(
            "hard_to_hit_head", 20,
            exposure={Reach.MELEE: 0.01, Reach.REACH: 1.0,
                      Reach.THROWN: 1.0, Reach.RANGED: 1.0},
        )
        common_part = _make_part(
            "torso", 50,
            exposure={Reach.MELEE: 1.0, Reach.REACH: 1.0,
                      Reach.THROWN: 1.0, Reach.RANGED: 1.0},
        )
        target = _make_creature(
            "target", health_max=500,
            body_parts=[rare_part, common_part],
        )
        # Use a MELEE attacker with deterministic seed
        attacker = _make_creature("attacker", atk="1d4")

        random.seed(42)
        rare_count = 0
        trials = 500
        for _ in range(trials):
            seq = attacker.do_attack(target)
            for r in seq.results:
                if r.target_part is rare_part:
                    rare_count += 1

        # With 0.01 vs 1.0 weight, rare should be ~1% of picks
        assert rare_count < trials * 0.10, (
            f"Rare part picked {rare_count}/{trials} times — expected < 10%"
        )


# ---------------------------------------------------------------------------
# Test 3: do_attack with a partless target
# ---------------------------------------------------------------------------

class TestDoAttackPartlessTarget:
    def test_all_results_have_none_target_part(self):
        target = _make_creature("target", health_max=100)  # no body_parts
        attacker = _make_creature("attacker", atk="1d4")

        sequence = attacker.do_attack(target)

        for result in sequence.results:
            assert result.target_part is None


# ---------------------------------------------------------------------------
# Test 3b: fuzzy explicit targeting end-to-end
# ---------------------------------------------------------------------------

class TestDoAttackFuzzyExplicitTargeting:
    def test_abbreviated_name_resolves_uniquely(self):
        """``do_attack(explicit_part_names=["leg.r"])`` must land on
        ``leg.right`` via ``find_parts``'s segment-prefix match — the
        full chain that powers ``$kill leg.r``."""
        left = _make_part("leg.left", 10)
        right = _make_part("leg.right", 10)
        target = _make_creature("target", health_max=100, body_parts=[left, right])
        attacker = _make_creature("attacker", atk="1d4")

        sequence = attacker.do_attack(target, explicit_part_names=["leg.r"])

        for result in sequence.results:
            assert result.target_part is right, (
                f"Expected leg.right, got {result.target_part.name}"
            )

    def test_multi_source_cycles_through_expanded_targets(self):
        """A 5-source attacker given two explicit targets (as the cog
        produces when the player types an ambiguous token like
        ``$kill leg``) must cycle round-robin rather than dogpile the
        last name. Guards against the regression the reviewer flagged
        where extras clamped to ``explicit_parts[-1]``."""
        left = _make_part("leg.left", 100)
        right = _make_part("leg.right", 100)
        target = _make_creature("target", health_max=500, body_parts=[left, right])

        attacker = _make_creature("hydra", atk="2d6")
        sources = [
            NaturalAttackSource(atk="2d6", label=f"Head {i}", skill="natural")
            for i in range(5)
        ]
        attacker.get_attack_sources = lambda: sources

        sequence = attacker.do_attack(
            target, explicit_part_names=["leg.left", "leg.right"]
        )

        hits = [r.target_part for r in sequence.results]
        # Round-robin: indices 0,2,4 → left; 1,3 → right.
        assert hits == [left, right, left, right, left]


# ---------------------------------------------------------------------------
# Test 4: multi-source picks independently
# ---------------------------------------------------------------------------

class TestDoAttackMultiSourceDifferentParts:
    def test_multiple_sources_can_pick_different_parts(self):
        """With 3+ sources and a multi-part target, at least some results
        should have different target_part values."""
        parts = [
            _make_part("left_arm", 20),
            _make_part("right_arm", 20),
            _make_part("torso", 50),
            _make_part("head", 20, is_critical=True),
        ]
        target = _make_creature("target", health_max=200, body_parts=parts)

        # Create a multi-source attacker (simulating hydra heads)
        attacker = _make_creature("hydra", atk="2d6")
        sources = [
            NaturalAttackSource(atk="2d6", label=f"Head {i}", skill="natural")
            for i in range(5)
        ]
        attacker.get_attack_sources = lambda: sources

        random.seed(12345)
        sequence = attacker.do_attack(target)

        # Collect all distinct target parts
        picked_parts = {r.target_part for r in sequence.results}
        assert len(picked_parts) > 1, (
            "With 5 sources and 4 parts, expected at least 2 distinct target parts"
        )


# ---------------------------------------------------------------------------
# Test 5: per-result damage application (integration)
# ---------------------------------------------------------------------------

class TestDoCombatPerResultDamage:
    def test_per_result_damage_reduces_body_and_part(self):
        """Apply damage per-result: body HP goes down by total, and each
        targeted part absorbs its share."""
        torso = _make_part("torso", 50)
        head = _make_part("head", 20, is_critical=True)
        target = _make_creature("target", health_max=200, body_parts=[torso, head])

        # Simulate two attack results targeting different parts
        combined1 = _make_combined(forced_attack=15, forced_damage=8, dodge=5)
        combined2 = _make_combined(forced_attack=15, forced_damage=6, dodge=5)

        src = MagicMock()
        src.label = "Fist"
        src.damage_type = None

        r1 = AttackResult(
            source=src, combined=combined1, damage=10,
            multiplier=1.0, defense=2, dodge=5,
        )
        r1.target_part = torso

        r2 = AttackResult(
            source=src, combined=combined2, damage=7,
            multiplier=1.0, defense=2, dodge=5,
        )
        r2.target_part = head

        # Apply damage per-result (part-targeted: only affects parts)
        for result in [r1, r2]:
            target.apply_damage(
                result.damage,
                dmg_type=result.dmg_type,
                target_part=result.target_part,
            )

        # Manually apply body HP reduction (simulating what do_combat does)
        total_raw = r1.damage + r2.damage  # 10 + 7 = 17
        final = max(1, total_raw - target.defense)  # 17 - 2 = 15
        target.health -= final
        target.health = max(0, target.health)

        # Body HP reduced by defense-adjusted total
        assert target.health == 200 - 15

        # Each part absorbed its respective damage
        assert torso.health == 50 - 10
        assert head.health == 20 - 7


# ---------------------------------------------------------------------------
# Test 6: death mid-round from critical part destruction
# ---------------------------------------------------------------------------

class TestDeathMidRound:
    def test_critical_part_destruction_kills_creature(self):
        """If a critical part (head) is destroyed, the creature dies even
        though body HP would have remained positive."""
        head = _make_part("head", 10, is_critical=True)
        torso = _make_part("torso", 50)
        target = _make_creature("target", health_max=200, body_parts=[head, torso])

        # Hit the head for 15 damage — enough to destroy it (10 HP)
        target.apply_damage(15, target_part=head)

        assert head.is_destroyed()
        assert target.health == 0
        assert target.is_dead()

    def test_subsequent_results_are_noop_after_death(self):
        """After the creature dies, additional apply_damage calls don't
        reduce health below 0."""
        head = _make_part("head", 5, is_critical=True)
        torso = _make_part("torso", 50)
        target = _make_creature("target", health_max=200, body_parts=[head, torso])

        # Kill via critical head
        target.apply_damage(10, target_part=head)
        assert target.is_dead()

        # Another hit to torso — health stays at 0
        target.apply_damage(20, target_part=torso)
        assert target.health == 0


# ---------------------------------------------------------------------------
# Test 7: AttackResult has target_part field
# ---------------------------------------------------------------------------

class TestAttackResultHasTargetPartField:
    def test_target_part_defaults_to_none(self):
        combined = _make_combined()
        src = MagicMock()
        src.label = "Test"
        src.damage_type = None
        result = AttackResult(
            source=src, combined=combined, damage=5,
            multiplier=1.0, defense=2, dodge=5,
        )
        assert result.target_part is None

    def test_target_part_stores_body_part(self):
        part = _make_part("arm", 20)
        combined = _make_combined()
        src = MagicMock()
        src.label = "Test"
        src.damage_type = None
        result = AttackResult(
            source=src, combined=combined, damage=5,
            multiplier=1.0, defense=2, dodge=5,
            target_part=part,
        )
        assert result.target_part is part
        assert result.target_part.name == "arm"
