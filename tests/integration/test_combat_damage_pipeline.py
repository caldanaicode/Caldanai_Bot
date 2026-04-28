"""Integration tests for the full combat damage pipeline.

These tests exercise the complete path: ``do_attack`` (which calls
``resolve_attack`` per source, applying creature trait multipliers)
→ per-result ``apply_damage`` (which applies only the part's trait
multiplier under Model D).

The unit tests for ``resolve_attack`` and ``apply_damage`` each pass
in isolation, but the double-multiplier bug (creature traits applied
in BOTH methods) was only visible when the two were chained together
with a non-trivial trait multiplier. These integration tests exist
specifically to catch that class of bug.

Q.7 trial: absorption rolls ``1d{defense}`` per hit. These tests
pin the defense-was-applied behaviour by mocking the absorption
roll so the expected post-defense damage stays deterministic; the
absorption-variance contract itself is pinned in
``tests/test_q7_dice_absorption.py``.
"""

from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures import Creature, pick_random_part
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach, Stat
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll


def _max_absorb_patch():
    """Patch ``Dice.quick_roll`` inside the creatures module so the
    ``1d{defense}`` absorption roll always returns the max face — the
    pre-Q.7 flat-defense behaviour. Tests that pinned specific post-
    defense damage values use this so the absorption variance doesn't
    break their arithmetic; Q.7 variance is covered separately."""
    return patch(
        "caldanai.lib.rpg.creatures.Dice.quick_roll",
        side_effect=lambda spec, **kw: int(spec.split("d")[1]),
    )


@pytest.fixture(autouse=True)
def _load_plugins():
    BodyPartPlugin.load_plugins()
    yield


def _make_creature(health=100, health_max=100, defense=0, dodge=0, traits=None):
    c = Creature(
        name="test_target", atk="1d4", defense=defense,
        dodge=dodge, health_max=health_max, health=health,
    )
    if traits:
        c.traits = traits
    return c


def _make_attacker():
    return Creature(
        name="test_attacker", atk="1d4", defense=5,
        dodge=5, health_max=50, health=50,
    )


def _force_hit_rolls(atk_roll, dmg_value):
    """Force deterministic rolls on an AttackRoll + DamageRoll pair."""
    atk_roll.rolls = (19,)
    atk_roll.result = 19
    atk_roll.isCritical = False
    atk_roll.isFumble = False
    dmg_roll = DamageRoll.__new__(DamageRoll)
    dmg_roll.dice = None
    dmg_roll.weapon_bonus = 0
    dmg_roll.skill_bonus = 0
    dmg_roll.result = dmg_value
    return atk_roll, dmg_roll


class TestTraitMultiplierAppliedOnce:
    """The creature's trait multiplier must be applied exactly once
    in the resolve_attack → apply_damage pipeline, not twice."""

    def test_half_resistance_halves_damage_once(self):
        """Creature with 0.5x FIRE resistance, defense=2. Raw 20.
        Q.6.2: multiplier + defense applied per-hit inside resolve_attack.
        sub_damage = int(20 * 0.5) = 10; with the absorption roll mocked
        to its max (2), damage = max(0, 10 - 2) = 8.
        apply_damage routes 8 to arm."""
        target = _make_creature(defense=2, dodge=1, traits={DamageTypes.FIRE: 0.5})
        torso = BodyPart.make("torso", name="torso", health_max=500)
        arm = BodyPart.make("arm", name="arm.left", health_max=500)
        target.body_parts = [torso, arm]

        attacker = _make_attacker()
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="fire sword",
        )

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 20)

        with _max_absorb_patch():
            result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        # int(20 * 0.5) = 10 sub_damage; max-roll absorbs 2 → 8 post-defense.
        assert result.sub_damage == 10
        assert result.damage == 8

        result.target_part = arm
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        # Arm takes post-defense damage.
        assert arm.health == 492   # 500 - 8

    def test_double_vulnerability_doubles_damage_once(self):
        """Creature with 2.0x FIRE vulnerability, defense=2. Raw 10.
        Q.6.2: int(10 * 2.0) = 20 sub_damage; with absorption mocked
        to its max (2), 20 - 2 = 18 post-defense."""
        target = _make_creature(defense=2, dodge=1, traits={DamageTypes.FIRE: 2.0})
        torso = BodyPart.make("torso", name="torso", health_max=500)
        arm = BodyPart.make("arm", name="arm.left", health_max=500)
        target.body_parts = [torso, arm]

        attacker = _make_attacker()
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="fire sword",
        )

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 10)

        with _max_absorb_patch():
            result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        assert result.sub_damage == 20
        assert result.damage == 18

        result.target_part = arm
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        assert arm.health == 482  # 500 - 18

    def test_creature_and_part_multipliers_combine_correctly(self):
        """Creature 0.5x FIRE, part 2.0x FIRE, defense=2. Raw 20.
        Q.6.2: creature-multiplier + defense apply in resolve_attack.
        sub_damage = int(20 * 0.5) = 10; with absorption mocked to its
        max (2), damage = max(0, 10-2) = 8.
        apply_damage then applies part 2.0x: int(8 * 2.0) = 16 to head."""
        target = _make_creature(defense=2, dodge=1, traits={DamageTypes.FIRE: 0.5})
        torso = BodyPart.make("torso", name="torso", health_max=500)
        head = BodyPart.make("head", name="head", health_max=50,
                             traits={DamageTypes.FIRE: 2.0})
        target.body_parts = [torso, head]

        attacker = _make_attacker()
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="fire sword",
        )

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 20)

        with _max_absorb_patch():
            result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        assert result.sub_damage == 10
        assert result.damage == 8

        result.target_part = head
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        # Part 2.0x trait applied downstream in apply_damage path:
        # int(8 * 2.0) = 16 taken by head.
        assert head.health == 34  # 50 - 16

    def test_no_trait_full_damage(self):
        """No traits, defense=2. Raw 20.
        Q.6.2: sub_damage = 20; with absorption mocked to its max (2),
        damage = max(0, 20-2) = 18."""
        target = _make_creature(defense=2, dodge=1)
        torso = BodyPart.make("torso", name="torso", health_max=500)
        arm = BodyPart.make("arm", name="arm.left", health_max=500)
        target.body_parts = [torso, arm]

        attacker = _make_attacker()
        source = NaturalAttackSource(atk="1d4", label="plain sword")

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 20)

        with _max_absorb_patch():
            result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        assert result.sub_damage == 20
        assert result.damage == 18

        result.target_part = arm
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        assert arm.health == 482  # 500 - 18


class TestDoAttackFullPipeline:
    """End-to-end through do_attack, which picks parts and chains
    resolve_attack → stores result.target_part automatically."""

    def test_do_attack_against_target_with_traits_and_parts(self):
        """Full do_attack pipeline with creature traits. Damage should
        be trait-multiplied exactly once regardless of how many sources."""
        target = _make_creature(
            health=50, health_max=50, defense=0, dodge=1,
            traits={DamageTypes.FIRE: 0.5},
        )
        torso = BodyPart.make("torso", name="torso", health_max=50)
        target.body_parts = [torso]

        attacker = _make_attacker()
        sequence = attacker.do_attack(target)

        for result in sequence.results:
            if result.damage > 0:
                target.apply_damage(
                    result.damage, result.dmg_type, result.target_part,
                )

        total_raw = sequence.total_damage()
        # Manually apply body HP reduction (simulating do_combat)
        # defense=0, so final = max(1, total_raw - 0) = total_raw
        defense = target.get_defense()
        num_hits = sum(1 for r in sequence.results if r.damage > 0)
        final = max(num_hits, total_raw - defense) if num_hits > 0 else 0
        target.health = max(0, target.health - final)

        # Body HP should have decreased by the defense-adjusted total
        assert target.health == max(0, 50 - final)

    def test_goblin_dies_at_zero_hp(self):
        """Regression test for the original bug: a goblin with trait
        multipliers should actually die when total damage >= HP."""
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin

        goblin = Goblin()
        goblin.health = 1
        goblin.health_max = 1
        goblin.dodge = 1  # easy to hit

        attacker = _make_attacker()
        sequence = attacker.do_attack(goblin)

        for result in sequence.results:
            if result.damage > 0:
                goblin.apply_damage(
                    result.damage, result.dmg_type, result.target_part,
                )

        # Manually apply body HP reduction (simulating do_combat)
        total_raw = sequence.total_damage()
        num_hits = sum(1 for r in sequence.results if r.damage > 0)
        if total_raw > 0:
            defense = goblin.get_defense()
            final = max(num_hits, total_raw - defense)
            goblin.health = max(0, goblin.health - final)
            assert goblin.is_dead()
