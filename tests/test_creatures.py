"""Tests for Caldanai.lib.rpg.creatures (Creature class)."""

from unittest.mock import patch, MagicMock

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import DamageTypes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_creature(**kwargs):
    """Create a Creature with sensible defaults; kwargs override."""
    defaults = dict(
        name="goblin",
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=20,
        health=20,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


# ---------------------------------------------------------------------------
# apply_damage
# ---------------------------------------------------------------------------

class TestApplyDamage:
    def test_positive_damage_reduces_health(self):
        c = _make_creature(health=20, health_max=20)
        c.apply_damage(5)
        assert c.health == 15

    def test_negative_amount_heals(self):
        c = _make_creature(health=10, health_max=20)
        c.apply_damage(-5)
        assert c.health == 15

    def test_health_clamps_at_zero(self):
        c = _make_creature(health=3, health_max=20)
        c.apply_damage(100)
        assert c.health == 0

    def test_healing_clamps_at_max(self):
        c = _make_creature(health=18, health_max=20)
        c.apply_damage(-10)
        assert c.health == 20

    def test_exact_kill(self):
        c = _make_creature(health=5, health_max=20)
        c.apply_damage(5)
        assert c.health == 0

    def test_zero_damage_is_noop(self):
        c = _make_creature(health=10, health_max=20)
        c.apply_damage(0)
        assert c.health == 10


# ---------------------------------------------------------------------------
# is_dead
# ---------------------------------------------------------------------------

class TestIsDead:
    def test_alive_at_full_health(self):
        c = _make_creature(health=20, health_max=20)
        assert c.is_dead() is False

    def test_alive_at_partial_health(self):
        c = _make_creature(health=1, health_max=20)
        assert c.is_dead() is False

    def test_dead_at_zero(self):
        c = _make_creature(health=0, health_max=20)
        assert c.is_dead() is True


# ---------------------------------------------------------------------------
# get_health_scale
# ---------------------------------------------------------------------------

class TestGetHealthScale:
    def test_full_health(self):
        c = _make_creature(health=20, health_max=20)
        assert c.get_health_scale() == 1.0

    def test_half_health(self):
        c = _make_creature(health=10, health_max=20)
        assert c.get_health_scale() == pytest.approx(0.5)

    def test_zero_health(self):
        c = _make_creature(health=0, health_max=20)
        assert c.get_health_scale() == 0.0

    def test_quarter_health(self):
        c = _make_creature(health=5, health_max=20)
        assert c.get_health_scale() == pytest.approx(0.25)


# ---------------------------------------------------------------------------
# get_overall_health_scale (weighted body + parts ratio)
# ---------------------------------------------------------------------------

class TestGetOverallHealthScale:
    """Weighted body + parts health ratio. Body HP and critical parts
    carry 2x weight; non-critical parts (limbs, eyes) carry 1x. Used
    by `$pray`'s nat-1 single-target rain picker and the 17-19 heal-
    target picker so a player with a wounded head outranks one with
    a sore foot."""

    def _bp(self, name, hp, hp_max, critical=False):
        from caldanai.lib.rpg.creatures.body_part import BodyPart
        part = BodyPart(name=name, health_max=hp_max, is_critical=critical)
        part.health = hp
        return part

    def test_no_parts_equals_body_scale(self):
        """With no body parts, the helper degenerates to the bare
        body HP ratio — same as ``get_health_scale``."""
        c = _make_creature(health=10, health_max=20)
        assert c.get_overall_health_scale() == pytest.approx(0.5)

    def test_full_body_full_parts_is_one(self):
        c = _make_creature(health=20, health_max=20)
        c.body_parts = [
            self._bp("head", 10, 10, critical=True),
            self._bp("arm.left", 8, 8),
        ]
        assert c.get_overall_health_scale() == pytest.approx(1.0)

    def test_critical_part_destroyed_outweighs_limb(self):
        """A creature with a destroyed critical part (head: 0/10)
        ranks lower than one with a destroyed limb (arm: 0/8). Both
        bodies full, both have one other intact part for symmetry."""
        crit_dead = _make_creature(health=20, health_max=20)
        crit_dead.body_parts = [
            self._bp("head", 0, 10, critical=True),
            self._bp("arm.left", 8, 8),
        ]
        limb_dead = _make_creature(health=20, health_max=20)
        limb_dead.body_parts = [
            self._bp("head", 10, 10, critical=True),
            self._bp("arm.left", 0, 8),
        ]
        assert crit_dead.get_overall_health_scale() < limb_dead.get_overall_health_scale()

    def test_critical_weight_parameter_scales_effect(self):
        """A higher ``critical_weight`` should pull the score down
        further when a critical part is wounded."""
        c = _make_creature(health=20, health_max=20)
        c.body_parts = [
            self._bp("head", 0, 10, critical=True),
            self._bp("arm.left", 8, 8),
        ]
        # 3x critical weight punishes the destroyed head harder.
        assert c.get_overall_health_scale(critical_weight=3.0) < c.get_overall_health_scale(critical_weight=2.0)

    def test_wounded_body_with_intact_parts(self):
        """Body at 10/20, all parts at full. Overall score = average
        of body_pct (0.5, weight 2) and parts (each 1.0). Pulled
        upward by intact parts but body still drags."""
        c = _make_creature(health=10, health_max=20)
        c.body_parts = [
            self._bp("head", 10, 10, critical=True),
            self._bp("arm.left", 8, 8),
        ]
        # body=0.5*2 + head=1.0*2 + arm=1.0*1 = 1.0+2.0+1.0 = 4.0
        # weight_total = 2 + 2 + 1 = 5
        # overall = 4.0 / 5 = 0.8
        assert c.get_overall_health_scale() == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# give_clarks
# ---------------------------------------------------------------------------

class TestGiveClarks:
    def test_give_positive(self):
        c = _make_creature()
        c.clarks = 10
        result = c.give_clarks(5)
        assert result is True
        assert c.clarks == 15
        assert c.is_dirty is True

    def test_give_negative_succeeds_when_result_positive(self):
        c = _make_creature()
        c.clarks = 10
        result = c.give_clarks(-5)
        assert result is True
        assert c.clarks == 5

    def test_give_negative_rejected_when_result_nonpositive(self):
        """give_clarks checks `self.clarks + amount > 0`, so result of 0 is rejected."""
        c = _make_creature()
        c.clarks = 5
        result = c.give_clarks(-5)
        assert result is False
        assert c.clarks == 5  # unchanged

    def test_give_negative_rejected_when_would_go_below_zero(self):
        c = _make_creature()
        c.clarks = 3
        result = c.give_clarks(-10)
        assert result is False
        assert c.clarks == 3


# ---------------------------------------------------------------------------
# do_attack — basic mechanics
# ---------------------------------------------------------------------------

class TestDoAttack:
    def test_do_attack_returns_attack_sequence(self):
        """do_attack should return an AttackSequence by iterating attack sources."""
        from caldanai.lib.rpg.combat.attack_result import AttackSequence

        attacker = _make_creature(name="attacker", atk="1d4")
        target = _make_creature(name="target", defense=2, dodge=5)

        sequence = attacker.do_attack(target)
        assert isinstance(sequence, AttackSequence)
        assert sequence.attacker is attacker
        assert sequence.target is target
        assert len(sequence.results) >= 1

    def test_do_attack_iterates_sources(self):
        """Each attack source should produce a result in the sequence."""
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource

        attacker = _make_creature(name="multi", atk="1d4")
        target = _make_creature(name="target", defense=2, dodge=5)

        # Override to return multiple sources
        attacker.get_attack_sources = lambda: [
            NaturalAttackSource(atk="1d4", label="First"),
            NaturalAttackSource(atk="1d4", label="Second"),
        ]

        sequence = attacker.do_attack(target)
        assert len(sequence.results) == 2

    def test_resolve_attack_returns_result(self):
        """resolve_attack should return an AttackResult with damage calculated."""
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll
        from caldanai.lib.rpg.helpers.dice import Dice

        attacker = _make_creature(name="attacker")
        target = _make_creature(name="target", defense=2, dodge=1)

        source = NaturalAttackSource(atk="1d4")
        atk_roll = AttackRoll(skill_bonus=20)  # force hit by huge bonus
        dmg_roll = DamageRoll(dice=Dice.d4(), weapon_bonus=5, skill_bonus=0)

        result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        assert isinstance(result, AttackResult)
        assert result.damage >= 0
        assert result.defense == 2


# ---------------------------------------------------------------------------
# get_trait_multiplier
# ---------------------------------------------------------------------------

class TestGetTraitMultiplier:
    def test_no_traits_returns_one(self):
        c = _make_creature(traits={})
        assert c.get_trait_multiplier(DamageTypes.FIRE) == 1.0

    def test_none_dmg_type_returns_one(self):
        c = _make_creature(traits={DamageTypes.FIRE: 2.0})
        assert c.get_trait_multiplier(None) == 1.0

    def test_exact_match(self):
        c = _make_creature(traits={DamageTypes.FIRE: 2.0})
        assert c.get_trait_multiplier(DamageTypes.FIRE) == 2.0

    def test_partial_flag_match(self):
        """A trait keyed on FIRE should match incoming FIRE|MAGICAL via bitwise overlap."""
        c = _make_creature(traits={DamageTypes.FIRE: 1.5})
        incoming = DamageTypes.FIRE | DamageTypes.MAGICAL
        result = c.get_trait_multiplier(incoming)
        assert result == 1.5

    def test_combined_trait_requires_superset(self):
        """A COMBINED trait like FIRE|SLASHING|COMBINED should only match if the
        incoming type includes both FIRE and SLASHING (and COMBINED)."""
        combined_key = DamageTypes.FIRE | DamageTypes.SLASHING | DamageTypes.COMBINED
        c = _make_creature(traits={combined_key: 3.0})
        # Incoming has both plus COMBINED flag
        incoming = DamageTypes.FIRE | DamageTypes.SLASHING | DamageTypes.COMBINED
        assert c.get_trait_multiplier(incoming) == 3.0

    def test_combined_trait_no_match_when_missing_component(self):
        """COMBINED trait should NOT match if incoming is missing a component."""
        combined_key = DamageTypes.FIRE | DamageTypes.SLASHING | DamageTypes.COMBINED
        c = _make_creature(traits={combined_key: 3.0})
        # Incoming has only FIRE + COMBINED, missing SLASHING
        incoming = DamageTypes.FIRE | DamageTypes.COMBINED
        assert c.get_trait_multiplier(incoming) == 1.0

    def test_highest_multiplier_wins(self):
        c = _make_creature(traits={DamageTypes.FIRE: 1.5, DamageTypes.MAGICAL: 2.5})
        incoming = DamageTypes.FIRE | DamageTypes.MAGICAL
        assert c.get_trait_multiplier(incoming) == 2.5
