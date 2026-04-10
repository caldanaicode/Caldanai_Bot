"""Tests for Caldanai.lib.rpg.creatures (Creature class)."""

from unittest.mock import patch, MagicMock

import pytest

from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.enums import DamageTypes


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
    @patch("Caldanai.lib.rpg.creatures.AttackRoll")
    @patch("Caldanai.lib.rpg.creatures.DamageRoll")
    @patch("Caldanai.lib.rpg.creatures.Dice")
    def test_do_attack_returns_tuple(self, mock_dice_cls, mock_dmg_cls, mock_atk_cls):
        """do_attack should return (str, int) regardless of roll outcomes."""
        attacker = _make_creature(name="attacker", atk="1d4")
        target = _make_creature(name="target", defense=2, dodge=5)

        # We need on_attacked to return a tuple; easiest to let it run naturally
        # but we need real roll objects. Just call it without mocking on_attacked.
        mock_dice_cls.from_ndn.return_value = MagicMock(rolls=(2,), value=2, sides=4, count=1)
        mock_atk_cls.return_value = MagicMock(
            rolls=(10,), sides=20, skillBonus=0, result=10, isCritical=False, isFumble=False
        )
        mock_dmg_cls.return_value = MagicMock(
            rolls=(3,), sides=4, skillBonus=0, weaponBonus=0, result=3
        )

        # Since the mocks intercept the constructors used inside do_attack,
        # on_attacked will also use the mocked classes. Let's just verify the
        # interface contract instead.
        with patch.object(target, "on_attacked", return_value=("attack msg", 5)):
            msg, dmg = attacker.do_attack(target)
            assert isinstance(msg, str)
            assert isinstance(dmg, int)
            assert dmg == 5


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
