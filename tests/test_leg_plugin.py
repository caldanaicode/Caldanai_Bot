"""Tests for the Phase 1.B item 2.4 LegPlugin.

Covers:
- Plugin discovery: ``LegPlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("leg")``.
- Factory: ``BodyPart.make("leg")`` returns a ``LegPlugin`` instance
  with all class-level defaults populated.
- Class defaults: ``is_critical`` is False, all four Reach keys are
  present in exposure (including the ``Reach.REACH`` key that the
  design-doc sketch omitted — we populate it explicitly at 1.0 to
  match ``Reach.MELEE``), debuffs span MINOR/MODERATE/SEVERE/USELESS
  with DODGE on every row and ATTACK on all rows except MINOR, and
  the ``health_max = "1d10"`` dice-string resolves to an int in
  [1, 10].
- Integration with Creature stat aggregation: at full health a leg
  contributes nothing. MINOR injury hits DODGE only. MODERATE/
  SEVERE/USELESS injuries hit both DODGE and ATTACK.
  ``get_dodge()`` reflects the DODGE debuff.
- DODGE clamp: a USELESS leg's -10 DODGE against a creature with
  base dodge 5 clamps to 0 (not -5) via the ``max(0, ...)`` guard in
  ``Creature.get_dodge``.
- Damage routing: destroying a non-critical leg does NOT kill the
  creature. The creature survives with reduced HP; the leg is
  destroyed and reports ``InjuryLevels.USELESS``; stat aggregation
  picks up the USELESS DODGE debuff.
Deterministic testing: where damage-routing behavior is under test, we
construct legs with an explicit integer ``health_max`` (via
``BodyPart.make("leg", health_max=10)``) rather than relying on the
``"1d10"`` dice-string default, so the test outcome doesn't depend on
the roll.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


def _make_creature(**kwargs) -> Creature:
    defaults = dict(
        name="training_dummy",
        atk="1d4",
        defense=10,
        dodge=5,
        health_max=20,
        health=20,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


@pytest.fixture
def loaded_plugins():
    """Ensure plugin discovery has run so ``BodyPart.make("leg")``
    works even if an earlier test swapped the registry out from under
    us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_leg_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("leg") is LegPlugin

    def test_leg_plugin_subclasses_bodypartplugin(self):
        assert issubclass(LegPlugin, BodyPartPlugin)


class TestFactory:
    def test_make_leg_returns_legplugin_instance(self, loaded_plugins):
        part = BodyPart.make("leg")
        assert isinstance(part, LegPlugin)
        assert isinstance(part, BodyPart)

    def test_make_leg_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("leg")
        assert part.name == "leg"
        assert part.is_critical is False
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert InjuryLevels.SEVERE in part.debuffs

    def test_make_leg_name_override(self, loaded_plugins):
        """Monsters will compose multiple legs via ``name="leg.left"``
        / ``"leg.right"`` kwargs."""
        part = BodyPart.make("leg", name="leg.left")
        assert isinstance(part, LegPlugin)
        assert part.name == "leg.left"


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_false(self):
        assert LegPlugin.is_critical is False

    def test_exposure_has_all_four_reach_keys(self):
        """The design-doc sketch was sparse (MELEE/THROWN/RANGED). We
        populate ``Reach.REACH`` explicitly at 1.0 to match MELEE so
        that every reach has an unambiguous value and plugins never
        fall through to a default."""
        assert set(LegPlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_values(self):
        """Melee/reach uniform at 1.0 (a sword swing naturally has the
        angle — you can't NOT hit a leg); thrown/ranged drop to 0.7
        because archers and throwers aim higher on the body."""
        assert LegPlugin.exposure[Reach.MELEE] == 1.0
        assert LegPlugin.exposure[Reach.REACH] == 1.0
        assert LegPlugin.exposure[Reach.THROWN] == 0.7
        assert LegPlugin.exposure[Reach.RANGED] == 0.7

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(LegPlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        assert InjuryLevels.USELESS in levels

    def test_debuffs_scale_dodge(self):
        d = LegPlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.DODGE] == -1
        assert d[InjuryLevels.MODERATE][Stat.DODGE] == -3
        assert d[InjuryLevels.SEVERE][Stat.DODGE] == -5
        assert d[InjuryLevels.USELESS][Stat.DODGE] == -10

    def test_debuffs_scale_attack_from_moderate(self):
        """ATTACK is the secondary penalty (kicks + bracing). MINOR
        does not touch ATTACK; MODERATE/SEVERE/USELESS do."""
        d = LegPlugin.debuffs
        assert Stat.ATTACK not in d[InjuryLevels.MINOR]
        assert d[InjuryLevels.MODERATE][Stat.ATTACK] == -1
        assert d[InjuryLevels.SEVERE][Stat.ATTACK] == -2
        assert d[InjuryLevels.USELESS][Stat.ATTACK] == -4

    def test_debuffs_do_not_touch_defense(self):
        """Legs never debuff DEFENSE (that's the arm's SEVERE niche)."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.DEFENSE not in LegPlugin.debuffs[level]

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "1d10"`` should resolve to an int in [1, 10]
        at construction time (dice-string support from item 1.5)."""
        for _ in range(30):
            part = BodyPart.make("leg")
            assert isinstance(part.health_max, int)
            assert 1 <= part.health_max <= 10


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_leg_no_stat_impact(self, loaded_plugins):
        c = _make_creature()
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        # Defense emerges from torso (none here) → core_toughness (0).
        assert c.get_defense() == 0
        # Dodge emerges from legs: ratio=1.0, MEDIUM → int(5 * 1.0) = 5.
        assert c.get_dodge() == 5

    def test_minor_leg_injury_debuffs_dodge_only(self, loaded_plugins):
        c = _make_creature()
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]
        # ~80% health -> MINOR band.
        leg.health = 8
        assert leg.get_injury_level() == InjuryLevels.MINOR
        assert c.get_stat_modifier_total(Stat.DODGE) == -1
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        # Dodge emerges: ratio=0.8, int(5 * 0.8) = 4.
        assert c.get_dodge() == 4

    def test_moderate_leg_injury_debuffs_dodge_and_attack(
        self, loaded_plugins
    ):
        c = _make_creature()
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]
        # ~40% health -> MODERATE band.
        leg.health = 4
        assert leg.get_injury_level() == InjuryLevels.MODERATE
        assert c.get_stat_modifier_total(Stat.DODGE) == -3
        assert c.get_stat_modifier_total(Stat.ATTACK) == -1
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        # Dodge emerges: ratio=0.5, int(5 * 0.5) = 2.
        assert c.get_dodge() == 2

    def test_severe_leg_injury_debuffs_dodge_and_attack(
        self, loaded_plugins
    ):
        c = _make_creature()
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]
        # 20% health -> SEVERE band.
        leg.health = 2
        assert leg.get_injury_level() == InjuryLevels.SEVERE
        assert c.get_stat_modifier_total(Stat.DODGE) == -5
        assert c.get_stat_modifier_total(Stat.ATTACK) == -2
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        # Dodge emerges: ratio=0.25, int(5 * 0.25) = 1.
        assert c.get_dodge() == 1

    def test_useless_leg_debuffs_dodge_and_attack(self, loaded_plugins):
        c = _make_creature()
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]
        leg.health = 0
        assert leg.get_injury_level() == InjuryLevels.USELESS
        assert c.get_stat_modifier_total(Stat.DODGE) == -10
        assert c.get_stat_modifier_total(Stat.ATTACK) == -4
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0


class TestDodgeClamp:
    def test_useless_leg_dodge_clamps_to_zero(self, loaded_plugins):
        """Creature with base dodge 5 and a USELESS leg (-10 DODGE)
        should clamp to 0, not return -5. Pins the ``max(0, ...)``
        clamp contract from item 1.10."""
        c = _make_creature(dodge=5)
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]
        leg.health = 0
        assert leg.get_injury_level() == InjuryLevels.USELESS
        assert c.get_stat_modifier_total(Stat.DODGE) == -10
        assert c.get_dodge() == 0


# ---------------------------------------------------------------------------
# Damage routing
# ---------------------------------------------------------------------------


class TestDamageRouting:
    def test_destroying_non_critical_leg_does_not_kill_creature(
        self, loaded_plugins
    ):
        """Creature with ``health_max=40`` and leg with ``health_max=10``:
        ``apply_damage(20, target_part=leg)`` should

        - destroy the leg (health clamps to 0, injury level USELESS)
        - drain the body by 20 (Model D — unified HP)
        - leave the creature alive at ``health == 20`` (leg is
          non-critical, so no instant-kill routing kicks in).
        - stat aggregation picks up the USELESS DODGE debuff (-10).
        """
        c = _make_creature(health_max=40, health=40)
        leg = BodyPart.make("leg", health_max=10)
        c.body_parts = [leg]

        c.apply_damage(20, target_part=leg)

        assert leg.is_destroyed() is True
        assert leg.get_injury_level() == InjuryLevels.USELESS
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 40, (
            "non-critical leg destruction must not kill the creature; "
            "part-targeted apply_damage does not touch body HP"
        )
        assert c.get_stat_modifier_total(Stat.DODGE) == -10
