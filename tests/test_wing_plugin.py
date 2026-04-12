"""Tests for the Phase 1.B item 2.5 WingPlugin.

Covers:

- Plugin discovery & factory: ``WingPlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("wing")``; ``BodyPart.make("wing")`` returns a
  ``WingPlugin`` instance with all class-level defaults populated.
- Class defaults: ``is_critical`` is False, all four Reach keys are
  present in exposure (including the ``Reach.REACH`` key the design
  doc sketch omitted -- we populate it explicitly at 0.5 to match
  ``Reach.MELEE``), debuffs span MINOR/MODERATE/SEVERE/USELESS with
  DODGE on every row and ATTACK on all rows except MINOR, and the
  ``health_max = "1d8"`` dice-string resolves to an int in [1, 8].
- Integration with Creature stat aggregation: at full health a wing
  contributes nothing; MINOR hits DODGE only; MODERATE/SEVERE/USELESS
  hit both DODGE and ATTACK, matching the design-doc numbers.
- ``on_injury_change`` hook -- the novel contract for this item:
  - Direct call: ``wing.on_injury_change(creature, SEVERE, USELESS)``
    returns a non-empty string AND removes ``"flying"`` from the
    creature's flags.
  - Other transitions (``NONE -> MINOR``, ``MODERATE -> SEVERE``,
    etc.) do NOT modify ``creature.flags`` and return ``""``.
  - Safe on missing flag: a creature that never had ``"flying"`` in
    its flags is still hit with the grounded message on a
    ``-> USELESS`` transition but ``set.discard`` does not raise.
- Full damage-routing integration: ``creature.apply_damage(20,
  target_part=wing)`` destroys the wing, fires ``on_injury_change``,
  removes the ``"flying"`` flag, and leaves the creature alive (wing
  is non-critical).
- Wing grounding + flag-dependent debuff pipeline: a toy stub that
  contributes -1 DODGE when ``"flying" not in owner.flags`` is
  dormant while the creature flies, then kicks in the instant the
  wing is destroyed. Pins the full state-dependent debuff pipeline.
- Doppelganger pain cries: non-empty strings for each injury level,
  empty for NONE, all four distinct.

Deterministic testing: damage-routing tests construct wings with an
explicit integer ``health_max`` (via ``BodyPart.make("wing",
health_max=10)``) rather than relying on the ``"1d8"`` dice default.
"""

import pytest

from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
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
    """Ensure plugin discovery has run so ``BodyPart.make("wing")``
    works even if an earlier test swapped the registry out from under
    us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_wing_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("wing") is WingPlugin

    def test_wing_plugin_subclasses_bodypartplugin(self):
        assert issubclass(WingPlugin, BodyPartPlugin)


class TestFactory:
    def test_make_wing_returns_wingplugin_instance(self, loaded_plugins):
        part = BodyPart.make("wing")
        assert isinstance(part, WingPlugin)
        assert isinstance(part, BodyPart)

    def test_make_wing_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("wing")
        assert part.name == "wing"
        assert part.is_critical is False
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert InjuryLevels.SEVERE in part.debuffs

    def test_make_wing_name_override(self, loaded_plugins):
        """Dragons compose multiple wings via ``name="wing 1"`` etc."""
        part = BodyPart.make("wing", name="wing 1")
        assert isinstance(part, WingPlugin)
        assert part.name == "wing 1"


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_false(self):
        assert WingPlugin.is_critical is False

    def test_exposure_has_all_four_reach_keys(self):
        """Design-doc sketch listed MELEE/THROWN/RANGED only. We
        populate ``Reach.REACH`` explicitly at 0.5 to match MELEE so
        plugins never fall through to a default."""
        assert set(WingPlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_values(self):
        """Wings tuck away in melee (0.5) and reach (0.5), splay out
        against thrown weapons (0.7) and are huge ranged targets
        (1.0)."""
        assert WingPlugin.exposure[Reach.MELEE] == 0.5
        assert WingPlugin.exposure[Reach.REACH] == 0.5
        assert WingPlugin.exposure[Reach.THROWN] == 0.7
        assert WingPlugin.exposure[Reach.RANGED] == 1.0

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(WingPlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        assert InjuryLevels.USELESS in levels

    def test_debuffs_scale_dodge(self):
        d = WingPlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.DODGE] == -1
        assert d[InjuryLevels.MODERATE][Stat.DODGE] == -2
        assert d[InjuryLevels.SEVERE][Stat.DODGE] == -3
        assert d[InjuryLevels.USELESS][Stat.DODGE] == -5

    def test_debuffs_scale_attack_from_moderate(self):
        """ATTACK is the secondary penalty (wing buffets). MINOR does
        not touch ATTACK; MODERATE/SEVERE/USELESS do."""
        d = WingPlugin.debuffs
        assert Stat.ATTACK not in d[InjuryLevels.MINOR]
        assert d[InjuryLevels.MODERATE][Stat.ATTACK] == -1
        assert d[InjuryLevels.SEVERE][Stat.ATTACK] == -2
        assert d[InjuryLevels.USELESS][Stat.ATTACK] == -3

    def test_debuffs_do_not_touch_defense(self):
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.DEFENSE not in WingPlugin.debuffs[level]

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "1d8"`` should resolve to an int in [1, 8]
        at construction time."""
        for _ in range(30):
            part = BodyPart.make("wing")
            assert isinstance(part.health_max, int)
            assert 1 <= part.health_max <= 8


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_wing_no_stat_impact(self, loaded_plugins):
        c = _make_creature()
        wing = BodyPart.make("wing", health_max=10)
        c.body_parts = [wing]
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        assert c.get_defense() == 10
        assert c.get_dodge() == 5

    def test_minor_wing_injury_debuffs_dodge_only(self, loaded_plugins):
        c = _make_creature()
        wing = BodyPart.make("wing", health_max=10)
        c.body_parts = [wing]
        # ~80% health -> MINOR band.
        wing.health = 8
        assert wing.get_injury_level() == InjuryLevels.MINOR
        assert c.get_stat_modifier_total(Stat.DODGE) == -1
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0

    def test_moderate_wing_injury_debuffs_dodge_and_attack(
        self, loaded_plugins
    ):
        c = _make_creature()
        wing = BodyPart.make("wing", health_max=10)
        c.body_parts = [wing]
        wing.health = 4  # ~40% -> MODERATE
        assert wing.get_injury_level() == InjuryLevels.MODERATE
        assert c.get_stat_modifier_total(Stat.DODGE) == -2
        assert c.get_stat_modifier_total(Stat.ATTACK) == -1
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0

    def test_severe_wing_injury_debuffs_dodge_and_attack(
        self, loaded_plugins
    ):
        c = _make_creature()
        wing = BodyPart.make("wing", health_max=10)
        c.body_parts = [wing]
        wing.health = 2  # 20% -> SEVERE
        assert wing.get_injury_level() == InjuryLevels.SEVERE
        assert c.get_stat_modifier_total(Stat.DODGE) == -3
        assert c.get_stat_modifier_total(Stat.ATTACK) == -2
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0

    def test_useless_wing_debuffs_dodge_and_attack(self, loaded_plugins):
        c = _make_creature()
        wing = BodyPart.make("wing", health_max=10)
        c.body_parts = [wing]
        wing.health = 0
        assert wing.get_injury_level() == InjuryLevels.USELESS
        assert c.get_stat_modifier_total(Stat.DODGE) == -5
        assert c.get_stat_modifier_total(Stat.ATTACK) == -3
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0


# ---------------------------------------------------------------------------
# on_injury_change hook -- the novel contract for this item
# ---------------------------------------------------------------------------


class TestOnInjuryChangeDirect:
    def test_transition_to_useless_removes_flying_flag(
        self, loaded_plugins
    ):
        """Direct call: SEVERE -> USELESS removes ``"flying"`` from the
        creature's flags and returns a non-empty grounded message."""
        c = _make_creature()
        c.flags = {"flying"}
        wing = BodyPart.make("wing", health_max=10)

        assert c.flags == {"flying"}
        msg = wing.on_injury_change(
            c, InjuryLevels.SEVERE, InjuryLevels.USELESS
        )

        assert isinstance(msg, str)
        assert msg != ""
        assert "flying" not in c.flags

    def test_transition_to_useless_message_mentions_grounded(
        self, loaded_plugins
    ):
        """Flavor text should reference the creature by name and
        mention grounding (design-doc string is ``"@1's wing crumples;
        @1o is grounded."``)."""
        c = _make_creature(name="wyvern")
        c.flags = {"flying"}
        wing = BodyPart.make("wing", health_max=10)

        msg = wing.on_injury_change(
            c, InjuryLevels.SEVERE, InjuryLevels.USELESS
        )
        assert "wyvern" in msg
        assert "grounded" in msg

    def test_transition_none_to_minor_does_not_touch_flags(
        self, loaded_plugins
    ):
        c = _make_creature()
        c.flags = {"flying"}
        wing = BodyPart.make("wing", health_max=10)

        msg = wing.on_injury_change(
            c, InjuryLevels.NONE, InjuryLevels.MINOR
        )
        assert msg == ""
        assert c.flags == {"flying"}

    def test_transition_moderate_to_severe_does_not_touch_flags(
        self, loaded_plugins
    ):
        c = _make_creature()
        c.flags = {"flying"}
        wing = BodyPart.make("wing", health_max=10)

        msg = wing.on_injury_change(
            c, InjuryLevels.MODERATE, InjuryLevels.SEVERE
        )
        assert msg == ""
        assert c.flags == {"flying"}

    def test_useless_transition_safe_when_flying_absent(
        self, loaded_plugins
    ):
        """A creature that never had ``"flying"`` in its flags is
        still hit with the grounded message on a ``-> USELESS``
        transition, but ``set.discard`` does not raise."""
        c = _make_creature()
        assert "flying" not in c.flags  # sanity
        wing = BodyPart.make("wing", health_max=10)

        # Must not raise.
        msg = wing.on_injury_change(
            c, InjuryLevels.SEVERE, InjuryLevels.USELESS
        )
        assert isinstance(msg, str)
        assert msg != ""
        assert "flying" not in c.flags  # still absent, no-op discard


# ---------------------------------------------------------------------------
# Full damage-routing integration -- the end-to-end pipeline test
# ---------------------------------------------------------------------------


class TestDamageRoutingIntegration:
    def test_apply_damage_destroys_wing_and_grounds_creature(
        self, loaded_plugins
    ):
        """Creature with ``health_max=20``, ``"flying"`` in flags, and
        a wing with ``health_max=10``. ``apply_damage(20,
        target_part=wing)`` should:

        - destroy the wing (injury level USELESS)
        - fire ``on_injury_change`` which discards ``"flying"`` from
          the creature's flags
        - leave the creature alive at ``health == 20`` (non-critical
          wing, body takes full damage under Model D)
        """
        c = _make_creature(health_max=40, health=40)
        c.flags = {"flying"}
        wing = BodyPart.make("wing", health_max=10)
        c.body_parts = [wing]

        c.apply_damage(20, target_part=wing)

        assert wing.is_destroyed() is True
        assert wing.get_injury_level() == InjuryLevels.USELESS
        assert "flying" not in c.flags, (
            "on_injury_change should have fired and discarded 'flying'"
        )
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 40, (
            "non-critical wing destruction must not kill the creature; "
            "part-targeted apply_damage does not touch body HP"
        )


# ---------------------------------------------------------------------------
# Wing grounding + flag-dependent debuff pipeline smoke test
# ---------------------------------------------------------------------------


class _FlagDependentStub(BodyPart):
    """Test-only flag-dependent part that returns -1 DODGE iff the owning
    creature is **not** currently flying. Used to verify that wing
    destruction correctly triggers downstream stat changes."""

    def __init__(self):
        super().__init__(
            name="flag_part",
            health_max=1,
            is_critical=False,
        )

    def get_stat_modifier(self, stat: Stat, owner) -> int:
        if stat != Stat.DODGE:
            return 0
        if "flying" in owner.flags:
            return 0
        return -1


class TestWingGroundingDebuffPipeline:
    def test_flag_part_dormant_while_flying_then_active_after_wing_destroyed(
        self, loaded_plugins
    ):
        """End-to-end pin of the state-dependent debuff machinery:

        1. Creature with flags={"flying"}, a wing, and a flag-dependent stub.
        2. While flying, stub is dormant -> DODGE modifier = 0.
        3. Destroy the wing via ``apply_damage`` -- the wing's
           ``on_injury_change`` fires, ``"flying"`` is discarded.
        4. The stub is now active -> DODGE modifier includes its -1.
        """
        c = _make_creature(health_max=40, health=40)
        c.flags = {"flying"}
        wing = BodyPart.make("wing", health_max=10)
        stub = _FlagDependentStub()
        c.body_parts = [wing, stub]

        # While flying: stub dormant, wing healthy -> no DODGE modifier.
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

        # Ground the creature by destroying the wing.
        c.apply_damage(20, target_part=wing)

        assert wing.is_destroyed() is True
        assert "flying" not in c.flags
        # Now stub contributes -1 AND wing contributes -5 (USELESS).
        assert c.get_stat_modifier_total(Stat.DODGE) == -5 + -1


# ---------------------------------------------------------------------------
# Doppelganger pain cry
# ---------------------------------------------------------------------------


class TestDoppelgangerPainCry:
    def test_pain_cry_is_non_empty_for_each_injury_level(
        self, loaded_plugins
    ):
        wing = BodyPart.make("wing", health_max=10)
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            cry = wing.get_doppelganger_pain_cry(level)
            assert isinstance(cry, str)
            assert cry != "", f"pain cry empty for level {level}"

    def test_pain_cry_empty_for_none_level(self, loaded_plugins):
        wing = BodyPart.make("wing", health_max=10)
        assert wing.get_doppelganger_pain_cry(InjuryLevels.NONE) == ""

    def test_pain_cries_are_distinct_per_level(self, loaded_plugins):
        wing = BodyPart.make("wing", health_max=10)
        cries = {
            wing.get_doppelganger_pain_cry(level)
            for level in (
                InjuryLevels.MINOR,
                InjuryLevels.MODERATE,
                InjuryLevels.SEVERE,
                InjuryLevels.USELESS,
            )
        }
        assert len(cries) == 4
