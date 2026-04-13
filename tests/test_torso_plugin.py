"""Tests for the Phase 1.B item 2.2 TorsoPlugin.

Covers:
- Plugin discovery: ``TorsoPlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("torso")``.
- Factory: ``BodyPart.make("torso")`` returns a ``TorsoPlugin`` instance
  with all class-level defaults populated (including ``is_critical=True``
  and the full four-reach exposure table).
- ``BodyPart.make("torso", is_critical=True)`` still yields an instance
  with ``is_critical=True``. This is a redundant override (the default
  is already True) but the dragon's composition in the Phase 1 design
  doc explicitly passes ``is_critical=True``, so we pin the behavior to
  protect that call site from breaking.
- Class defaults: ``is_critical`` is True, all four Reach keys are
  present in exposure (each equal to 1.0 — the torso is the easiest
  thing to hit from any angle), debuffs span
  MINOR/MODERATE/SEVERE/USELESS, and the ``health_max = "2d10"``
  dice-string resolves to an int in [2, 20].
- Integration with Creature stat aggregation: at full health a torso
  contributes nothing to any stat. MODERATE injury simultaneously
  debuffs ATTACK, DEFENSE, and DODGE — the torso is the only base part
  so far that touches all three core combat stats at once.
- Damage routing: destroying a critical torso kills the creature.
Deterministic testing: where damage-routing behavior is under test, we
construct torsos with an explicit integer ``health_max`` (via
``BodyPart.make("torso", health_max=10)``) rather than relying on the
``"2d10"`` dice-string default, so the test outcome doesn't depend on
the roll.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
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
    """Ensure plugin discovery has run so ``BodyPart.make("torso")``
    works even if an earlier test swapped the registry out from under
    us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_torso_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("torso") is TorsoPlugin

    def test_torso_plugin_subclasses_bodypartplugin(self):
        assert issubclass(TorsoPlugin, BodyPartPlugin)


class TestFactory:
    def test_make_torso_returns_torsoplugin_instance(self, loaded_plugins):
        part = BodyPart.make("torso")
        assert isinstance(part, TorsoPlugin)
        assert isinstance(part, BodyPart)

    def test_make_torso_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("torso")
        assert part.name == "torso"
        assert part.is_critical is True
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert InjuryLevels.SEVERE in part.debuffs

    def test_make_torso_redundant_is_critical_override(self, loaded_plugins):
        """The dragon composition in the design doc explicitly passes
        ``is_critical=True`` even though that's already the default. Pin
        that call site so it keeps working."""
        part = BodyPart.make("torso", is_critical=True)
        assert isinstance(part, TorsoPlugin)
        assert part.is_critical is True


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_true(self):
        assert TorsoPlugin.is_critical is True

    def test_exposure_has_all_four_reach_keys(self):
        assert set(TorsoPlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_values_all_one(self):
        """The torso is the largest, most-exposed part of any creature.
        Uniformly 1.0 — the full body is one giant torso-shaped target."""
        for reach in (
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        ):
            assert TorsoPlugin.exposure[reach] == 1.0

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(TorsoPlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        # USELESS unreachable for a critical part but listed for symmetry.
        assert InjuryLevels.USELESS in levels

    def test_debuffs_touch_attack_defense_and_dodge(self):
        """Core injuries affect breathing, balance, and twist/dodge
        motion — so the torso is unique among base parts in debuffing
        all three core combat stats simultaneously."""
        d = TorsoPlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.ATTACK] == -1
        assert d[InjuryLevels.MODERATE][Stat.ATTACK] == -2
        assert d[InjuryLevels.MODERATE][Stat.DEFENSE] == -1
        assert d[InjuryLevels.MODERATE][Stat.DODGE] == -1
        assert d[InjuryLevels.SEVERE][Stat.ATTACK] == -3
        assert d[InjuryLevels.SEVERE][Stat.DEFENSE] == -2
        assert d[InjuryLevels.SEVERE][Stat.DODGE] == -2
        assert d[InjuryLevels.USELESS][Stat.ATTACK] == -5
        assert d[InjuryLevels.USELESS][Stat.DEFENSE] == -4
        assert d[InjuryLevels.USELESS][Stat.DODGE] == -4

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "2d10"`` should resolve to an int in [2, 20]
        at construction time (dice-string support from item 1.5)."""
        for _ in range(30):
            part = BodyPart.make("torso")
            assert isinstance(part.health_max, int)
            assert 2 <= part.health_max <= 20


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_torso_no_stat_impact(self, loaded_plugins):
        c = _make_creature()
        torso = BodyPart.make("torso", health_max=10)
        c.body_parts = [torso]
        # Torso at full health -> InjuryLevels.NONE -> no debuffs.
        assert c.get_defense() == 10
        assert c.get_dodge() == 5
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_moderate_torso_injury_debuffs_all_three_stats(
        self, loaded_plugins
    ):
        c = _make_creature()
        torso = BodyPart.make("torso", health_max=10)
        c.body_parts = [torso]
        # 50% health -> MODERATE band.
        torso.health = 5
        assert torso.get_injury_level() == InjuryLevels.MODERATE
        assert c.get_stat_modifier_total(Stat.ATTACK) == -2
        assert c.get_stat_modifier_total(Stat.DEFENSE) == -1
        assert c.get_stat_modifier_total(Stat.DODGE) == -1

    def test_moderate_torso_injury_propagates_to_getters(
        self, loaded_plugins
    ):
        c = _make_creature()
        torso = BodyPart.make("torso", health_max=10)
        c.body_parts = [torso]
        torso.health = 5
        assert torso.get_injury_level() == InjuryLevels.MODERATE
        assert c.get_defense() == 10 - 1
        assert c.get_dodge() == 5 - 1


# ---------------------------------------------------------------------------
# Damage routing
# ---------------------------------------------------------------------------


class TestDamageRouting:
    def test_destroying_critical_torso_kills_creature(self, loaded_plugins):
        """``is_critical=True`` + torso destroyed → ``self.health = 0``
        (see ``Creature.apply_damage`` option C routing).

        We pin ``torso.health_max`` explicitly to 10 so this test doesn't
        depend on the ``2d10`` dice roll.
        """
        c = _make_creature(health_max=30, health=30)
        torso = BodyPart.make("torso", health_max=10)
        c.body_parts = [torso]
        c.apply_damage(20, target_part=torso)
        assert torso.is_destroyed()
        assert c.health == 0
