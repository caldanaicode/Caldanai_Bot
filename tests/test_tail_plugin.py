"""Tests for the Phase 1.B item 2.6 TailPlugin.

Covers:
- Plugin discovery: ``TailPlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("tail")``.
- Factory: ``BodyPart.make("tail")`` returns a ``TailPlugin`` instance
  with all class-level defaults populated.
- Class defaults: ``is_critical`` is False, all four Reach keys are
  present in exposure (uniformly lower than legs because tails are
  mobile, off-center targets that can be tucked out of the way),
  debuffs span MINOR/MODERATE/SEVERE/USELESS with DODGE only (tails
  are balance organs, not attack organs), and ``health_max = "1d6"``
  resolves to an int in [1, 6].
- **Contract pin**: ``Stat.ATTACK`` is NEVER touched at any injury
  level. Tails don't swing weapons and a base tail is not an attack
  appendage -- specialty tails (scorpion sting, dragon tail slap) can
  subclass. ``Stat.DEFENSE`` is also NEVER touched.
- Integration with Creature stat aggregation: full health contributes
  nothing, MINOR hits DODGE -1, USELESS hits DODGE -5. ``get_dodge()``
  reflects the DODGE debuff.
- Damage routing: destroying a non-critical tail does NOT kill the
  creature. The creature survives; stat aggregation picks up the
  USELESS DODGE debuff (-5).
Deterministic testing: where damage-routing behavior is under test, we
construct tails with an explicit integer ``health_max`` (via
``BodyPart.make("tail", health_max=10)``) rather than relying on the
``"1d6"`` dice-string default, so outcomes don't depend on the roll.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
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
    """Ensure plugin discovery has run so ``BodyPart.make("tail")``
    works even if an earlier test swapped the registry out from under
    us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_tail_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("tail") is TailPlugin

    def test_tail_plugin_subclasses_bodypartplugin(self):
        assert issubclass(TailPlugin, BodyPartPlugin)


class TestFactory:
    def test_make_tail_returns_tailplugin_instance(self, loaded_plugins):
        part = BodyPart.make("tail")
        assert isinstance(part, TailPlugin)
        assert isinstance(part, BodyPart)

    def test_make_tail_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("tail")
        assert part.name == "tail"
        assert part.is_critical is False
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert InjuryLevels.SEVERE in part.debuffs

    def test_make_tail_name_override(self, loaded_plugins):
        """Monsters may compose specialty tails via ``name`` overrides
        (e.g. ``"barbed tail"``, ``"spined tail"``)."""
        part = BodyPart.make("tail", name="barbed tail")
        assert isinstance(part, TailPlugin)
        assert part.name == "barbed tail"


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_false(self):
        assert TailPlugin.is_critical is False

    def test_exposure_has_all_four_reach_keys(self):
        assert set(TailPlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_values_lower_than_other_parts(self):
        """Tails are mobile, off-center targets that can be tucked out
        of the way. Exposure is uniformly lower than legs (1.0 melee)
        across all reach bands. Ranged/thrown/reach are slightly higher
        than melee because a dodging tail silhouette is still visible
        at distance even if harder to hit up close."""
        assert TailPlugin.exposure[Reach.MELEE] == 0.5
        assert TailPlugin.exposure[Reach.REACH] == 0.6
        assert TailPlugin.exposure[Reach.THROWN] == 0.6
        assert TailPlugin.exposure[Reach.RANGED] == 0.6

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(TailPlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        assert InjuryLevels.USELESS in levels

    def test_debuffs_scale_dodge(self):
        d = TailPlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.DODGE] == -1
        assert d[InjuryLevels.MODERATE][Stat.DODGE] == -2
        assert d[InjuryLevels.SEVERE][Stat.DODGE] == -3
        assert d[InjuryLevels.USELESS][Stat.DODGE] == -5

    def test_debuffs_never_touch_attack(self):
        """Contract pin: a base tail NEVER debuffs ``Stat.ATTACK``.

        Tails are balance organs, not attack organs. A generic tail
        doesn't swing a weapon or throw a punch, so losing it does not
        reduce a creature's attack rolls. Specialty tails (a scorpion's
        sting, a dragon's tail slap) that *do* deal damage should
        subclass ``TailPlugin`` and declare their own ATTACK debuff --
        the base class must stay neutral so it composes cleanly on any
        quadruped/reptile/monkey."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.ATTACK not in TailPlugin.debuffs[level], (
                f"TailPlugin must not debuff ATTACK at {level}; that's "
                f"the specialty-tail subclass's job, not the base class"
            )

    def test_debuffs_never_touch_defense(self):
        """Contract pin: a base tail NEVER debuffs ``Stat.DEFENSE``.

        Defense debuffs are the arm's SEVERE niche (parry loss). A tail
        has nothing to do with blocking or parrying."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.DEFENSE not in TailPlugin.debuffs[level], (
                f"TailPlugin must not debuff DEFENSE at {level}; that's "
                f"the arm's SEVERE niche"
            )

    def test_debuffs_only_contain_dodge(self):
        """The base tail's only debuff key at every level is DODGE."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert set(TailPlugin.debuffs[level].keys()) == {Stat.DODGE}

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "1d6"`` should resolve to an int in [1, 6]
        at construction time (dice-string support from item 1.5)."""
        for _ in range(30):
            part = BodyPart.make("tail")
            assert isinstance(part.health_max, int)
            assert 1 <= part.health_max <= 6


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_tail_no_stat_impact(self, loaded_plugins):
        c = _make_creature()
        tail = BodyPart.make("tail", health_max=10)
        c.body_parts = [tail]
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        assert c.get_defense() == 10
        assert c.get_dodge() == 5

    def test_minor_tail_injury_debuffs_dodge_only(self, loaded_plugins):
        c = _make_creature()
        tail = BodyPart.make("tail", health_max=10)
        c.body_parts = [tail]
        # ~80% health -> MINOR band.
        tail.health = 8
        assert tail.get_injury_level() == InjuryLevels.MINOR
        assert c.get_stat_modifier_total(Stat.DODGE) == -1
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_dodge() == 5 - 1

    def test_moderate_tail_injury_debuffs_dodge_only(self, loaded_plugins):
        c = _make_creature()
        tail = BodyPart.make("tail", health_max=10)
        c.body_parts = [tail]
        # ~40% health -> MODERATE band.
        tail.health = 4
        assert tail.get_injury_level() == InjuryLevels.MODERATE
        assert c.get_stat_modifier_total(Stat.DODGE) == -2
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_dodge() == 5 - 2

    def test_severe_tail_injury_debuffs_dodge_only(self, loaded_plugins):
        c = _make_creature()
        tail = BodyPart.make("tail", health_max=10)
        c.body_parts = [tail]
        # 20% health -> SEVERE band.
        tail.health = 2
        assert tail.get_injury_level() == InjuryLevels.SEVERE
        assert c.get_stat_modifier_total(Stat.DODGE) == -3
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_dodge() == 5 - 3

    def test_useless_tail_debuffs_dodge_only(self, loaded_plugins):
        c = _make_creature()
        tail = BodyPart.make("tail", health_max=10)
        c.body_parts = [tail]
        tail.health = 0
        assert tail.get_injury_level() == InjuryLevels.USELESS
        assert c.get_stat_modifier_total(Stat.DODGE) == -5
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_dodge() == 0


# ---------------------------------------------------------------------------
# Damage routing
# ---------------------------------------------------------------------------


class TestDamageRouting:
    def test_destroying_non_critical_tail_does_not_kill_creature(
        self, loaded_plugins
    ):
        """Creature with ``health_max=40`` and tail with ``health_max=10``:
        ``apply_damage(20, target_part=tail)`` should

        - destroy the tail (health clamps to 0, injury level USELESS)
        - drain the body by 20 (Model D — unified HP)
        - leave the creature alive at ``health == 20`` (tail is
          non-critical, so no instant-kill routing kicks in).
        - stat aggregation picks up the USELESS DODGE debuff (-5).
        """
        c = _make_creature(health_max=40, health=40)
        tail = BodyPart.make("tail", health_max=10)
        c.body_parts = [tail]

        c.apply_damage(20, target_part=tail)

        assert tail.is_destroyed() is True
        assert tail.get_injury_level() == InjuryLevels.USELESS
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 40, (
            "non-critical tail destruction must not kill the creature; "
            "part-targeted apply_damage does not touch body HP"
        )
        assert c.get_stat_modifier_total(Stat.DODGE) == -5
