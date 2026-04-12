"""Tests for the Phase 1.B item 2.1 HeadPlugin.

Covers:
- Plugin discovery: ``HeadPlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("head")``.
- Factory: ``BodyPart.make("head")`` returns a ``HeadPlugin`` instance
  with all class-level defaults populated (including ``is_critical`` and
  the full four-reach exposure table).
- ``BodyPart.make("head", name=...)`` overrides the name while keeping
  other defaults (mirrors the dragon example
  ``BodyPart.make("head", name="head")``).
- Class defaults: ``is_critical`` is True, all four Reach keys are
  present in exposure, debuffs span MINOR/MODERATE/SEVERE/USELESS, and
  the ``health_max = "1d8"`` dice-string resolves to ``[1, 8]``.
- Integration with Creature stat aggregation: at full health a head
  contributes nothing to defense/dodge (no DEFENSE/DODGE rows in the
  debuffs table). MINOR injury → ATTACK -1. SEVERE → ATTACK -3 and
  HIT -2.
- Damage routing: ``creature.apply_damage(..., target_part=head)`` with
  enough damage to destroy a critical head kills the creature.
- Doppelganger pain cries are non-empty strings for each injury level
  and empty for NONE.

Deterministic testing: where damage-routing behavior is under test, we
construct heads with an explicit integer ``health_max`` (via
``BodyPart.make("head", health_max=10)``) rather than relying on the
``"1d8"`` dice-string default, so the test outcome doesn't depend on
the roll.
"""

from typing import List, Optional

import pytest

from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


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
    """Ensure plugin discovery has run so ``BodyPart.make("head")`` works
    even if an earlier test swapped the registry out from under us."""
    BodyPartPlugin.load_plugins()
    yield
    # No teardown needed: load_plugins is idempotent and the real plugin
    # files on disk are the source of truth.


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_head_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("head") is HeadPlugin

    def test_head_plugin_subclasses_bodypartplugin(self):
        assert issubclass(HeadPlugin, BodyPartPlugin)


class TestFactory:
    def test_make_head_returns_headplugin_instance(self, loaded_plugins):
        part = BodyPart.make("head")
        assert isinstance(part, HeadPlugin)
        assert isinstance(part, BodyPart)

    def test_make_head_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("head")
        assert part.name == "head"
        assert part.is_critical is True
        # exposure has all four reach keys populated
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_make_head_name_override_preserves_other_defaults(
        self, loaded_plugins
    ):
        part = BodyPart.make("head", name="head")
        assert part.name == "head"
        assert part.is_critical is True
        assert Reach.MELEE in part.exposure
        # debuffs table still present
        assert InjuryLevels.SEVERE in part.debuffs


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_true(self):
        assert HeadPlugin.is_critical is True

    def test_exposure_has_all_four_reach_keys(self):
        assert set(HeadPlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_values_in_expected_order(self):
        """Heads are harder to hit in melee than at range (you have to
        swing up past the torso). Ranged is 1.0 because archers aim at
        heads on purpose."""
        exp = HeadPlugin.exposure
        assert exp[Reach.MELEE] == 0.7
        assert exp[Reach.REACH] == 0.8
        assert exp[Reach.THROWN] == 0.9
        assert exp[Reach.RANGED] == 1.0

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(HeadPlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        # USELESS is unreachable for a critical part (creature dies first)
        # but the row is listed defensively per the design note.
        assert InjuryLevels.USELESS in levels

    def test_debuffs_scale_with_severity(self):
        """MINOR < MODERATE < SEVERE in magnitude of the ATTACK penalty."""
        d = HeadPlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.ATTACK] == -1
        assert d[InjuryLevels.MODERATE][Stat.ATTACK] == -2
        assert d[InjuryLevels.SEVERE][Stat.ATTACK] == -3
        # HIT debuff shows up at MODERATE onward
        assert d[InjuryLevels.MODERATE][Stat.HIT] == -1
        assert d[InjuryLevels.SEVERE][Stat.HIT] == -2

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "1d8"`` should resolve to an int in [1, 8] at
        construction time (dice-string support from item 1.5)."""
        for _ in range(20):
            part = BodyPart.make("head")
            assert isinstance(part.health_max, int)
            assert 1 <= part.health_max <= 8


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_head_does_not_affect_defense_or_dodge(
        self, loaded_plugins
    ):
        c = _make_creature()
        head = BodyPart.make("head", health_max=10)
        c.body_parts = [head]
        # Head at full health -> InjuryLevels.NONE -> no debuffs at all
        assert c.get_defense() == 10
        assert c.get_dodge() == 5
        # ATTACK aggregate should also be 0 contribution.
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0

    def test_minor_head_injury_applies_attack_debuff(self, loaded_plugins):
        c = _make_creature()
        head = BodyPart.make("head", health_max=10)
        c.body_parts = [head]
        # 70% health -> MINOR (the [0.60, 1.00) band)
        head.health = 7
        assert head.get_injury_level() == InjuryLevels.MINOR
        assert c.get_stat_modifier_total(Stat.ATTACK) == -1
        # No hit penalty yet at MINOR
        assert c.get_stat_modifier_total(Stat.HIT) == 0

    def test_severe_head_injury_applies_attack_and_hit_debuffs(
        self, loaded_plugins
    ):
        c = _make_creature()
        head = BodyPart.make("head", health_max=10)
        c.body_parts = [head]
        # 10% health -> SEVERE (the (0, 0.30) band)
        head.health = 1
        assert head.get_injury_level() == InjuryLevels.SEVERE
        assert c.get_stat_modifier_total(Stat.ATTACK) == -3
        assert c.get_stat_modifier_total(Stat.HIT) == -2


# ---------------------------------------------------------------------------
# Damage routing
# ---------------------------------------------------------------------------


class TestDamageRouting:
    def test_destroying_critical_head_kills_creature(self, loaded_plugins):
        """``is_critical=True`` + head destroyed → ``self.health = 0``
        (see ``Creature.apply_damage`` option C routing).

        We pin ``head.health_max`` explicitly to 10 so this test doesn't
        depend on the ``1d8`` dice roll.
        """
        c = _make_creature(health_max=30, health=30)
        head = BodyPart.make("head", health_max=10)
        c.body_parts = [head]
        c.apply_damage(20, target_part=head)
        assert head.is_destroyed()
        assert c.health == 0


# ---------------------------------------------------------------------------
# Doppelganger pain cry
# ---------------------------------------------------------------------------


class TestDoppelgangerPainCry:
    def test_pain_cry_is_non_empty_for_each_injury_level(self, loaded_plugins):
        head = BodyPart.make("head", health_max=10)
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            cry = head.get_doppelganger_pain_cry(level)
            assert isinstance(cry, str)
            assert cry != "", f"pain cry empty for level {level}"

    def test_pain_cry_empty_for_none_level(self, loaded_plugins):
        head = BodyPart.make("head", health_max=10)
        assert head.get_doppelganger_pain_cry(InjuryLevels.NONE) == ""

    def test_pain_cries_are_distinct_per_level(self, loaded_plugins):
        head = BodyPart.make("head", health_max=10)
        cries = {
            head.get_doppelganger_pain_cry(level)
            for level in (
                InjuryLevels.MINOR,
                InjuryLevels.MODERATE,
                InjuryLevels.SEVERE,
                InjuryLevels.USELESS,
            )
        }
        # Four levels should produce four distinct strings.
        assert len(cries) == 4
