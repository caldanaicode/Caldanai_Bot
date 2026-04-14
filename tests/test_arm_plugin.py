"""Tests for the Phase 1.B item 2.3 ArmPlugin.

Covers:
- Plugin discovery: ``ArmPlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("arm")``.
- Factory: ``BodyPart.make("arm")`` returns an ``ArmPlugin`` instance
  with all class-level defaults populated (including
  ``is_critical=False`` and the full four-reach asymmetric exposure
  table).
- Class defaults: ``is_critical`` is False, all four Reach keys are
  present in exposure with expected asymmetric values, debuffs span
  MINOR/MODERATE/SEVERE/USELESS, and the ``health_max = "1d8"``
  dice-string resolves to an int in [1, 8].
- ``disable_slot`` marker: the USELESS debuff row carries the
  forward-facing ``"disable_slot": True`` marker. Pinned so it can't
  be silently removed by a future refactor that mistakes it for dead
  code — a future equipment-integration item will consume it to
  disable the corresponding weapon slot.
- Integration with Creature stat aggregation: at full health an arm
  contributes nothing. MINOR injury hits ATTACK only. SEVERE injury
  hits both ATTACK and DEFENSE (a broken arm can't parry). USELESS
  injury hits ATTACK and leaves DEFENSE alone; the
  ``"disable_slot": True`` string key in the same row is *not*
  consulted by ``get_stat_modifier_total`` (it's a string, not a
  ``Stat`` enum) and does not accidentally spill into DEFENSE or any
  other stat. This pins the "mixed-key dict is safe for aggregation"
  contract.
- Damage routing: destroying a non-critical arm does NOT kill the
  creature. The creature survives with reduced HP; the arm is
  destroyed and reports ``InjuryLevels.USELESS``.
Deterministic testing: where damage-routing behavior is under test, we
construct arms with an explicit integer ``health_max`` (via
``BodyPart.make("arm", health_max=10)``) rather than relying on the
``"1d8"`` dice-string default, so the test outcome doesn't depend on
the roll.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
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
    """Ensure plugin discovery has run so ``BodyPart.make("arm")``
    works even if an earlier test swapped the registry out from under
    us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_arm_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("arm") is ArmPlugin

    def test_arm_plugin_subclasses_bodypartplugin(self):
        assert issubclass(ArmPlugin, BodyPartPlugin)


class TestFactory:
    def test_make_arm_returns_armplugin_instance(self, loaded_plugins):
        part = BodyPart.make("arm")
        assert isinstance(part, ArmPlugin)
        assert isinstance(part, BodyPart)

    def test_make_arm_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("arm")
        assert part.name == "arm"
        assert part.is_critical is False
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert InjuryLevels.SEVERE in part.debuffs

    def test_make_arm_name_override(self, loaded_plugins):
        """Monsters will compose multiple arms via ``name="arm.left"``
        / ``"arm.right"`` kwargs."""
        part = BodyPart.make("arm", name="arm.left")
        assert isinstance(part, ArmPlugin)
        assert part.name == "arm.left"


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_false(self):
        assert ArmPlugin.is_critical is False

    def test_exposure_has_all_four_reach_keys(self):
        assert set(ArmPlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_values_are_asymmetric(self):
        """Arms swing into melee/reach weapons (0.8), are harder to
        hit with thrown (0.7), and the hardest to land arrows on
        versus the torso (0.6)."""
        assert ArmPlugin.exposure[Reach.MELEE] == 0.8
        assert ArmPlugin.exposure[Reach.REACH] == 0.8
        assert ArmPlugin.exposure[Reach.THROWN] == 0.7
        assert ArmPlugin.exposure[Reach.RANGED] == 0.6

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(ArmPlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        assert InjuryLevels.USELESS in levels

    def test_debuffs_scale_attack_linearly(self):
        d = ArmPlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.ATTACK] == -1
        assert d[InjuryLevels.MODERATE][Stat.ATTACK] == -2
        assert d[InjuryLevels.SEVERE][Stat.ATTACK] == -3
        assert d[InjuryLevels.USELESS][Stat.ATTACK] == -5

    def test_severe_debuff_includes_defense_penalty(self):
        """A broken arm can't parry: SEVERE adds a -1 DEFENSE penalty
        on top of the ATTACK scaling."""
        assert ArmPlugin.debuffs[InjuryLevels.SEVERE][Stat.DEFENSE] == -1

    def test_minor_and_moderate_debuffs_do_not_touch_defense(self):
        """Below SEVERE, an injured arm can still parry normally."""
        assert Stat.DEFENSE not in ArmPlugin.debuffs[InjuryLevels.MINOR]
        assert Stat.DEFENSE not in ArmPlugin.debuffs[InjuryLevels.MODERATE]

    def test_useless_row_has_disable_slot_marker(self):
        """Forward-facing marker for a future equipment-integration
        item: an USELESS arm should disable the corresponding weapon
        slot. Pinned here so the marker can't be silently removed by a
        refactor that mistakes it for dead code.

        The marker is a *string* key in the same dict as ``Stat``
        enum keys; Python allows mixing them, and
        ``get_stat_modifier_total`` ignores non-Stat keys."""
        row = ArmPlugin.debuffs[InjuryLevels.USELESS]
        assert "disable_slot" in row
        assert row["disable_slot"] is True

    def test_useless_row_does_not_accidentally_zero_defense(self):
        """The USELESS row only touches ATTACK (plus the inert
        ``disable_slot`` marker). DEFENSE is not listed."""
        row = ArmPlugin.debuffs[InjuryLevels.USELESS]
        assert Stat.DEFENSE not in row

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "2d8"`` should resolve to an int in [2, 16]
        at construction time (dice-string support from item 1.5)."""
        for _ in range(30):
            part = BodyPart.make("arm")
            assert isinstance(part.health_max, int)
            assert 2 <= part.health_max <= 16


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_arm_no_stat_impact(self, loaded_plugins):
        c = _make_creature()
        arm = BodyPart.make("arm", health_max=10)
        c.body_parts = [arm]
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        # Arm alone: no torso → defense=0, no legs → dodge=0 (emergence).
        assert c.get_defense() == 0
        assert c.get_dodge() == 0

    def test_minor_arm_injury_debuffs_attack_only(self, loaded_plugins):
        c = _make_creature()
        arm = BodyPart.make("arm", health_max=10)
        c.body_parts = [arm]
        # ~80% health -> MINOR band.
        arm.health = 8
        assert arm.get_injury_level() == InjuryLevels.MINOR
        assert c.get_stat_modifier_total(Stat.ATTACK) == -1
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_severe_arm_injury_debuffs_attack_and_defense(
        self, loaded_plugins
    ):
        c = _make_creature()
        arm = BodyPart.make("arm", health_max=10)
        c.body_parts = [arm]
        # 20% health -> SEVERE band (MINOR: [0.60, 1.0),
        # MODERATE: [0.30, 0.60), SEVERE: (0, 0.30), USELESS: <= 0).
        arm.health = 2
        assert arm.get_injury_level() == InjuryLevels.SEVERE
        assert c.get_stat_modifier_total(Stat.ATTACK) == -3
        assert c.get_stat_modifier_total(Stat.DEFENSE) == -1
        # DODGE never touched by arm debuffs.
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        # No torso → defense = core_toughness (0) regardless of arm debuffs.
        assert c.get_defense() == 0

    def test_useless_arm_does_not_affect_defense(self, loaded_plugins):
        """USELESS arm: ATTACK -5, DEFENSE unchanged. The
        ``"disable_slot": True`` non-Stat entry in the same row is
        inert — it must not spill into DEFENSE or any other stat."""
        c = _make_creature()
        arm = BodyPart.make("arm", health_max=10)
        c.body_parts = [arm]
        arm.health = 0
        assert arm.get_injury_level() == InjuryLevels.USELESS
        assert c.get_stat_modifier_total(Stat.ATTACK) == -5
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_mixed_key_dict_is_safe_for_aggregation(self, loaded_plugins):
        """Non-Stat key isolation: the ``"disable_slot": True`` string
        key in the USELESS row must not affect aggregation of any
        other stat. Pins the "mixed-key dict is safe" contract.
        """
        c = _make_creature()
        arm = BodyPart.make("arm", health_max=10)
        c.body_parts = [arm]
        arm.health = 0
        assert arm.get_injury_level() == InjuryLevels.USELESS
        # The marker is still present on the row...
        assert (
            arm.debuffs[InjuryLevels.USELESS].get("disable_slot") is True
        )
        # ...but it's inert for aggregation.
        for stat in (Stat.DEFENSE, Stat.DODGE, Stat.HIT, Stat.HEALTH_MAX):
            assert c.get_stat_modifier_total(stat) == 0, (
                f"non-Stat 'disable_slot' key leaked into {stat}"
            )


# ---------------------------------------------------------------------------
# Damage routing
# ---------------------------------------------------------------------------


class TestDamageRouting:
    def test_destroying_non_critical_arm_does_not_kill_creature(
        self, loaded_plugins
    ):
        """Creature with ``health_max=40`` and arm with ``health_max=10``:
        ``apply_damage(20, target_part=arm)`` should

        - destroy the arm (health clamps to 0, injury level USELESS)
        - drain the body by 20 (Model D — unified HP)
        - leave the creature alive at ``health == 20`` (arm is
          non-critical, so no instant-kill routing kicks in).
        """
        c = _make_creature(health_max=40, health=40)
        arm = BodyPart.make("arm", health_max=10)
        c.body_parts = [arm]

        c.apply_damage(20, target_part=arm)

        assert arm.is_destroyed() is True
        assert arm.get_injury_level() == InjuryLevels.USELESS
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 40, (
            "non-critical arm destruction must not kill the creature; "
            "part-targeted apply_damage does not touch body HP"
        )
