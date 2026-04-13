"""Tests for the generic ToePlugin.

Covers:

- Plugin discovery & factory: ``ToePlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("toe")``; ``BodyPart.make("toe")`` returns a
  ``ToePlugin`` instance with all class-level defaults populated.
- Class defaults: ``is_critical`` is False, ``health_max`` is the
  integer literal ``1``, nonzero exposure for melee/reach/thrown/ranged,
  ``debuffs`` has a USELESS entry for -1 DODGE.
- Generic behavior: no ``get_stat_modifier`` override on the class;
  toes use the standard debuffs table.
- A creature with healthy toes does NOT get -1 dodge per toe.
- A destroyed toe contributes -1 DODGE via the debuffs table.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.toe import ToePlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


def _make_creature(**kwargs) -> Creature:
    defaults = dict(
        name="training_dummy",
        atk="1d4",
        defense=10,
        dodge=5,
        health_max=40,
        health=40,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


@pytest.fixture
def loaded_plugins():
    """Ensure plugin discovery has run so ``BodyPart.make("toe")`` works
    even if an earlier test swapped the registry out from under us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_toe_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("toe") is ToePlugin

    def test_toe_plugin_subclasses_bodypartplugin(self):
        assert issubclass(ToePlugin, BodyPartPlugin)


class TestFactory:
    def test_make_toe_returns_toeplugin_instance(self, loaded_plugins):
        part = BodyPart.make("toe")
        assert isinstance(part, ToePlugin)
        assert isinstance(part, BodyPart)

    def test_make_toe_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("toe")
        assert part.name == "toe"
        assert part.is_critical is False
        assert part.health_max == 1
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert part.debuffs == {InjuryLevels.USELESS: {Stat.DODGE: -1}}

    def test_make_toe_name_override(self, loaded_plugins):
        part = BodyPart.make("toe", name="toe 17")
        assert isinstance(part, ToePlugin)
        assert part.name == "toe 17"


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_false(self):
        assert ToePlugin.is_critical is False

    def test_health_max_is_integer_one(self):
        """``health_max`` is the integer literal 1, not a dice string."""
        assert ToePlugin.health_max == 1
        assert isinstance(ToePlugin.health_max, int)

    def test_exposure_nonzero_for_melee(self):
        assert ToePlugin.exposure[Reach.MELEE] == 0.3

    def test_exposure_nonzero_for_reach(self):
        assert ToePlugin.exposure[Reach.REACH] == 0.2

    def test_exposure_nonzero_for_thrown(self):
        assert ToePlugin.exposure[Reach.THROWN] == 0.1

    def test_exposure_nonzero_for_ranged(self):
        assert ToePlugin.exposure[Reach.RANGED] == 0.1

    def test_debuffs_has_useless_dodge(self):
        """The debuffs table has an USELESS entry that gives -1 DODGE."""
        assert InjuryLevels.USELESS in ToePlugin.debuffs
        assert ToePlugin.debuffs[InjuryLevels.USELESS] == {Stat.DODGE: -1}

    def test_no_get_stat_modifier_override(self):
        """ToePlugin must NOT override get_stat_modifier — it relies
        entirely on the standard debuffs table."""
        assert "get_stat_modifier" not in ToePlugin.__dict__


# ---------------------------------------------------------------------------
# Generic behavior: no per-toe dodge penalty at full health
# ---------------------------------------------------------------------------


class TestGenericToeBehavior:
    def test_healthy_toes_do_not_penalize_dodge(self, loaded_plugins):
        """A creature with 10 healthy toes should get 0 dodge penalty.
        The old ToePlugin penalized living toes on non-flying creatures."""
        c = _make_creature(dodge=10)
        c.flags = set()
        c.body_parts = [
            BodyPart.make("toe", name=f"toe {i + 1}") for i in range(10)
        ]
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        # Toes alone: no legs → dodge = core_agility (0).
        assert c.get_dodge() == 0

    def test_destroyed_toe_contributes_minus_one_dodge(self, loaded_plugins):
        """A destroyed toe (USELESS) contributes -1 DODGE via the
        standard debuffs table."""
        c = _make_creature(dodge=10)
        toe = BodyPart.make("toe", name="toe 1")
        c.body_parts = [toe]

        # Healthy: no penalty.
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

        # Destroy the toe.
        toe.health = 0
        assert toe.is_destroyed()
        assert toe.get_injury_level() == InjuryLevels.USELESS

        # Now contributes -1 DODGE via stat modifier aggregation.
        assert c.get_stat_modifier_total(Stat.DODGE) == -1
        # Toes alone: no legs → dodge = core_agility (0).
        assert c.get_dodge() == 0

    def test_multiple_destroyed_toes_stack(self, loaded_plugins):
        """Multiple destroyed toes each contribute -1 DODGE."""
        c = _make_creature(dodge=10)
        toes = [BodyPart.make("toe", name=f"toe {i + 1}") for i in range(3)]
        c.body_parts = toes

        for toe in toes:
            toe.health = 0

        assert c.get_stat_modifier_total(Stat.DODGE) == -3
        # Toes alone: no legs → dodge = core_agility (0).
        assert c.get_dodge() == 0
