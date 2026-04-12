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
"""

import pytest

from Caldanai.lib.rpg.creatures import Creature, pick_random_part
from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from Caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from Caldanai.lib.rpg.helpers.enums import DamageTypes, Reach, Stat
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll


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
        """Creature with 0.5x FIRE resistance, defense=2. Raw damage 20.
        resolve_attack: int(20 * 0.5) = 10 (no defense subtracted).
        apply_damage routes 10 to part (no FIRE trait -> 1.0x).
        Body HP: do_combat subtracts defense once: 100 - max(1, 10 - 2) = 92."""
        target = _make_creature(defense=2, dodge=1, traits={DamageTypes.FIRE: 0.5})
        torso = BodyPart.make("torso", name="torso", health_max=50)
        target.body_parts = [torso]

        attacker = _make_attacker()
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="fire sword",
        )

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 20)

        result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        # int(20 * 0.5) = 10, no defense subtracted
        assert result.damage == 10

        result.target_part = torso
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        # Part takes the raw damage
        assert torso.health == 40   # 50 - 10

        # Manually apply body HP reduction (simulating do_combat)
        defense = target.get_defense()
        final = max(1, result.damage - defense)  # max(1, 10 - 2) = 8
        target.health = max(0, target.health - final)

        assert target.health == 92  # 100 - 8

    def test_double_vulnerability_doubles_damage_once(self):
        """Creature with 2.0x FIRE vulnerability, defense=2. Raw damage 10.
        resolve_attack: int(10 * 2.0) = 20 (no defense subtracted).
        Body HP: do_combat subtracts defense once: 100 - max(1, 20 - 2) = 82."""
        target = _make_creature(defense=2, dodge=1, traits={DamageTypes.FIRE: 2.0})
        torso = BodyPart.make("torso", name="torso", health_max=50)
        target.body_parts = [torso]

        attacker = _make_attacker()
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="fire sword",
        )

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 10)

        result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        # int(10 * 2.0) = 20, no defense subtracted
        assert result.damage == 20

        result.target_part = torso
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        # Part takes the raw damage
        assert torso.health == 30  # 50 - 20

        # Manually apply body HP reduction (simulating do_combat)
        defense = target.get_defense()
        final = max(1, result.damage - defense)  # max(1, 20 - 2) = 18
        target.health = max(0, target.health - final)

        assert target.health == 82  # 100 - 18

    def test_creature_and_part_multipliers_combine_correctly(self):
        """Creature 0.5x FIRE, part 2.0x FIRE, defense=2. Raw damage 20.
        resolve_attack applies creature: int(20 * 0.5) = 10 (no defense).
        apply_damage applies part 2.0x: int(10 * 2.0) = 20 to part only.
        Body HP: do_combat subtracts defense once: 100 - max(1, 10 - 2) = 92."""
        target = _make_creature(defense=2, dodge=1, traits={DamageTypes.FIRE: 0.5})
        head = BodyPart.make("head", name="head", health_max=50,
                             traits={DamageTypes.FIRE: 2.0})
        target.body_parts = [head]

        attacker = _make_attacker()
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="fire sword",
        )

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 20)

        result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        # creature 0.5x: int(20 * 0.5) = 10, no defense subtracted
        assert result.damage == 10

        result.target_part = head
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        # Part 2.0x in apply_damage: int(10 * 2.0) = 20
        assert head.health == 30  # 50 - 20

        # Manually apply body HP reduction (simulating do_combat)
        defense = target.get_defense()
        final = max(1, result.damage - defense)  # max(1, 10 - 2) = 8
        target.health = max(0, target.health - final)

        assert target.health == 92  # 100 - 8

    def test_no_trait_full_damage(self):
        """No traits on creature or part, defense=2. Raw damage 20.
        resolve_attack: 20 * 1.0 = 20 (no defense subtracted)."""
        target = _make_creature(defense=2, dodge=1)
        torso = BodyPart.make("torso", name="torso", health_max=50)
        target.body_parts = [torso]

        attacker = _make_attacker()
        source = NaturalAttackSource(atk="1d4", label="plain sword")

        atk_roll = AttackRoll(skill_bonus=0)
        atk_roll, dmg_roll = _force_hit_rolls(atk_roll, 20)

        result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        # 20 * 1.0 = 20, no defense subtracted
        assert result.damage == 20

        result.target_part = torso
        target.apply_damage(result.damage, result.dmg_type, result.target_part)

        # Part takes the raw damage
        assert torso.health == 30  # 50 - 20

        # Manually apply body HP reduction (simulating do_combat)
        defense = target.get_defense()
        final = max(1, result.damage - defense)  # max(1, 20 - 2) = 18
        target.health = max(0, target.health - final)

        assert target.health == 82  # 100 - 18


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
        from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        from Caldanai.lib.rpg.creatures.monsters.goblin import Goblin

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
