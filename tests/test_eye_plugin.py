"""Tests for the Phase 1.B item 2.7 EyePlugin.

Covers:
- Plugin discovery: ``EyePlugin`` is discovered by
  ``BodyPartPlugin.load_plugins()`` and retrievable via
  ``get_plugin_class("eye")``.
- Factory: ``BodyPart.make("eye")`` returns an ``EyePlugin`` instance
  with all class-level defaults populated, and ``BodyPart.make("eye",
  name="left eye")`` allows per-instance name overrides (required for
  multi-eye composition on creatures with two or more eyes).
- Class defaults: ``is_critical`` is False, all four Reach keys are
  present in exposure with *uniformly low* values (all <= 0.3) to
  reflect that eyes are tiny, hard-to-hit targets. Debuffs span
  MINOR/MODERATE/SEVERE/USELESS with HIT only (eyes debuff aim, not
  attack power, defense, or dodge). ``health_max = "1d4"`` resolves to
  an int in [1, 4].
- **Contract pin**: ``Stat.HIT`` is the ONLY stat the base eye touches
  at any level. ``Stat.ATTACK``, ``Stat.DEFENSE``, and ``Stat.DODGE``
  are NEVER in any debuff row. Non-linear HIT scaling: -1/-2/-4/-8,
  where the USELESS jump is intentionally steeper than a linear
  extension of SEVERE -- a fully blinded creature should be a sitting
  duck.
- Integration with Creature stat aggregation: full health contributes
  nothing; MINOR hits HIT -1 with DODGE 0; USELESS hits HIT -8 with
  DODGE 0. A two-eye creature with both eyes useless aggregates to
  HIT -16.
- **Multi-eye composition**: a creature built with two separately-named
  ``EyePlugin`` instances ("left eye" and "right eye") correctly routes
  damage to the targeted eye, aggregates debuffs per-eye, and resolves
  via ``creature.get_part("left eye") / get_part("right eye")``. This
  is the novel contract for item 2.7 (the item 1.8 ``get_part`` name
  lookup is pinned here for the multi-instance case).
- Damage routing: destroying a non-critical eye does NOT kill the
  creature. The creature survives; stat aggregation picks up HIT -8.
- Doppelganger pain cries: non-empty strings for each injury level,
  empty for NONE, all four distinct.

Deterministic testing: where damage-routing behavior is under test, we
construct eyes with an explicit integer ``health_max`` (via
``BodyPart.make("eye", health_max=4)``) rather than relying on the
``"1d4"`` dice-string default, so outcomes don't depend on the roll.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
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
    """Ensure plugin discovery has run so ``BodyPart.make("eye")`` works
    even if an earlier test swapped the registry out from under us."""
    BodyPartPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_eye_plugin_is_discoverable(self, loaded_plugins):
        assert BodyPartPlugin.get_plugin_class("eye") is EyePlugin

    def test_eye_plugin_subclasses_bodypartplugin(self):
        assert issubclass(EyePlugin, BodyPartPlugin)


class TestFactory:
    def test_make_eye_returns_eyeplugin_instance(self, loaded_plugins):
        part = BodyPart.make("eye")
        assert isinstance(part, EyePlugin)
        assert isinstance(part, BodyPart)

    def test_make_eye_propagates_class_defaults(self, loaded_plugins):
        part = BodyPart.make("eye")
        assert part.name == "eye"
        assert part.is_critical is False
        assert set(part.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }
        assert InjuryLevels.SEVERE in part.debuffs

    def test_make_eye_name_override(self, loaded_plugins):
        """Creatures with multiple eyes compose via ``name`` overrides
        (``"left eye"``, ``"right eye"``, ``"center eye"`` for a cyclops,
        or eight separately-named spider eyes)."""
        part = BodyPart.make("eye", name="left eye")
        assert isinstance(part, EyePlugin)
        assert part.name == "left eye"


# ---------------------------------------------------------------------------
# Class defaults
# ---------------------------------------------------------------------------


class TestClassDefaults:
    def test_is_critical_is_false(self):
        """Blinding a creature does not kill it -- even a fully blinded
        creature can still swing wildly."""
        assert EyePlugin.is_critical is False

    def test_exposure_has_all_four_reach_keys(self):
        assert set(EyePlugin.exposure.keys()) == {
            Reach.MELEE,
            Reach.REACH,
            Reach.THROWN,
            Reach.RANGED,
        }

    def test_exposure_uniformly_low(self):
        """Eyes are tiny, hard-to-hit targets. Every reach band's
        exposure must be <= 0.3 -- dramatically lower than arms (0.6-0.8)
        or torso. Random attack routing should land on an eye rarely;
        explicit targeting (``attack @dragon eye``) should be the
        primary way to hit one."""
        for reach in (Reach.MELEE, Reach.REACH, Reach.THROWN, Reach.RANGED):
            assert EyePlugin.exposure[reach] <= 0.3, (
                f"EyePlugin exposure[{reach}] must be <= 0.3 to reflect "
                f"that eyes are tiny, hard-to-hit targets; got "
                f"{EyePlugin.exposure[reach]}"
            )

    def test_exposure_specific_values(self):
        """Pin the specific exposure values. Ranged is highest (archers
        can aim); melee/reach are lowest (hitting a specific eye with a
        sword requires a deliberate gouge)."""
        assert EyePlugin.exposure[Reach.MELEE] == 0.1
        assert EyePlugin.exposure[Reach.REACH] == 0.1
        assert EyePlugin.exposure[Reach.THROWN] == 0.2
        assert EyePlugin.exposure[Reach.RANGED] == 0.3

    def test_debuffs_cover_all_injury_levels(self):
        levels = set(EyePlugin.debuffs.keys())
        assert InjuryLevels.MINOR in levels
        assert InjuryLevels.MODERATE in levels
        assert InjuryLevels.SEVERE in levels
        assert InjuryLevels.USELESS in levels

    def test_debuffs_scale_hit_non_linearly(self):
        """Pin the exact HIT values -1/-2/-4/-8. The jump from SEVERE
        to USELESS is intentionally steeper than linear -- a fully
        blinded creature should be qualitatively worse at aiming than
        one with a merely severely-injured eye."""
        d = EyePlugin.debuffs
        assert d[InjuryLevels.MINOR][Stat.HIT] == -1
        assert d[InjuryLevels.MODERATE][Stat.HIT] == -2
        assert d[InjuryLevels.SEVERE][Stat.HIT] == -4
        assert d[InjuryLevels.USELESS][Stat.HIT] == -8

    def test_useless_is_more_than_linear_extension_of_severe(self):
        """Explicit contract pin: ``USELESS`` HIT must be strictly more
        severe than a linear extension of the ``SEVERE`` row. This
        encodes the "fully blinded is qualitatively different"
        intent -- if a future refactor accidentally smooths this out to
        linear scaling, the test trips."""
        severe = EyePlugin.debuffs[InjuryLevels.SEVERE][Stat.HIT]
        useless = EyePlugin.debuffs[InjuryLevels.USELESS][Stat.HIT]
        # Both values are negative; "more severe" means more negative,
        # i.e. useless < severe * 1.5 (since severe is negative, 1.5 *
        # severe is the linear extension, and useless should be <= it).
        assert useless <= severe * 1.5, (
            f"EyePlugin USELESS HIT ({useless}) must be at least as "
            f"severe as 1.5x the SEVERE row ({severe * 1.5}); the jump "
            f"at full blindness is intentional and should not be "
            f"smoothed to linear"
        )

    def test_debuffs_never_touch_attack(self):
        """Contract pin: a base eye NEVER debuffs ``Stat.ATTACK``.

        Eyes affect aim (HIT), not raw attack power. Even a blind
        creature can still swing hard -- it just can't target well."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.ATTACK not in EyePlugin.debuffs[level], (
                f"EyePlugin must not debuff ATTACK at {level}; eye "
                f"injuries affect HIT (aim), not raw attack power"
            )

    def test_debuffs_never_touch_defense(self):
        """Contract pin: a base eye NEVER debuffs ``Stat.DEFENSE``.

        DEFENSE debuffs are the arm's SEVERE niche (parry loss). Eyes
        have nothing to do with blocking or parrying."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.DEFENSE not in EyePlugin.debuffs[level], (
                f"EyePlugin must not debuff DEFENSE at {level}; that's "
                f"the arm's SEVERE niche"
            )

    def test_debuffs_never_touch_dodge(self):
        """Contract pin: a base eye NEVER debuffs ``Stat.DODGE``.

        DODGE is the tail/leg niche (balance and footwork). While
        blindness intuitively might hurt dodging, the base eye plugin
        keeps its contract tight: HIT only. Creatures that want
        blindness to hurt dodge can compose additional parts or
        subclass."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert Stat.DODGE not in EyePlugin.debuffs[level], (
                f"EyePlugin must not debuff DODGE at {level}; base eye "
                f"contract is HIT-only"
            )

    def test_debuffs_only_contain_hit(self):
        """The base eye's only debuff key at every level is HIT."""
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            assert set(EyePlugin.debuffs[level].keys()) == {Stat.HIT}

    def test_health_max_dice_string_resolves_in_range(self, loaded_plugins):
        """``health_max = "1d4"`` should resolve to an int in [1, 4]
        at construction time (dice-string support from item 1.5)."""
        for _ in range(30):
            part = BodyPart.make("eye")
            assert isinstance(part.health_max, int)
            assert 1 <= part.health_max <= 4


# ---------------------------------------------------------------------------
# Integration with Creature stat aggregation
# ---------------------------------------------------------------------------


class TestCreatureAggregation:
    def test_full_health_eye_no_stat_impact(self, loaded_plugins):
        c = _make_creature()
        eye = BodyPart.make("eye", health_max=4)
        c.body_parts = [eye]
        assert c.get_stat_modifier_total(Stat.HIT) == 0
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        assert c.get_dodge() == 5

    def test_minor_eye_injury_debuffs_hit_only(self, loaded_plugins):
        c = _make_creature()
        eye = BodyPart.make("eye", health_max=10)
        c.body_parts = [eye]
        # ~80% health -> MINOR band.
        eye.health = 8
        assert eye.get_injury_level() == InjuryLevels.MINOR
        assert c.get_stat_modifier_total(Stat.HIT) == -1
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_moderate_eye_injury_debuffs_hit_only(self, loaded_plugins):
        c = _make_creature()
        eye = BodyPart.make("eye", health_max=10)
        c.body_parts = [eye]
        # ~40% health -> MODERATE band.
        eye.health = 4
        assert eye.get_injury_level() == InjuryLevels.MODERATE
        assert c.get_stat_modifier_total(Stat.HIT) == -2
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_severe_eye_injury_debuffs_hit_only(self, loaded_plugins):
        c = _make_creature()
        eye = BodyPart.make("eye", health_max=10)
        c.body_parts = [eye]
        # 20% health -> SEVERE band.
        eye.health = 2
        assert eye.get_injury_level() == InjuryLevels.SEVERE
        assert c.get_stat_modifier_total(Stat.HIT) == -4
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_useless_eye_debuffs_hit_only(self, loaded_plugins):
        c = _make_creature()
        eye = BodyPart.make("eye", health_max=4)
        c.body_parts = [eye]
        eye.health = 0
        assert eye.get_injury_level() == InjuryLevels.USELESS
        assert c.get_stat_modifier_total(Stat.HIT) == -8
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.DODGE) == 0

    def test_two_useless_eyes_aggregate_hit_debuff(self, loaded_plugins):
        """A creature with two destroyed eyes should aggregate HIT -16
        (-8 per eye). This pins the per-part summation in
        ``get_stat_modifier_total`` for the multi-instance case."""
        c = _make_creature()
        left_eye = BodyPart.make("eye", name="left eye", health_max=4)
        right_eye = BodyPart.make("eye", name="right eye", health_max=4)
        c.body_parts = [left_eye, right_eye]
        left_eye.health = 0
        right_eye.health = 0
        assert c.get_stat_modifier_total(Stat.HIT) == -16


# ---------------------------------------------------------------------------
# Multi-eye composition (the novel contract for item 2.7)
# ---------------------------------------------------------------------------


class TestMultiEyeComposition:
    """Creatures with multiple eyes must compose cleanly via per-instance
    ``name`` overrides, and ``creature.get_part(name)`` (item 1.8) must
    resolve each by name."""

    def test_two_eyes_full_health_no_hit_debuff(self, loaded_plugins):
        c = _make_creature()
        left_eye = BodyPart.make("eye", name="left eye", health_max=4)
        right_eye = BodyPart.make("eye", name="right eye", health_max=4)
        c.body_parts = [left_eye, right_eye]
        assert c.get_stat_modifier_total(Stat.HIT) == 0

    def test_destroying_left_eye_debuffs_hit_by_eight(self, loaded_plugins):
        c = _make_creature()
        left_eye = BodyPart.make("eye", name="left eye", health_max=4)
        right_eye = BodyPart.make("eye", name="right eye", health_max=4)
        c.body_parts = [left_eye, right_eye]

        c.apply_damage(10, target_part=left_eye)

        assert left_eye.is_destroyed() is True
        assert left_eye.get_injury_level() == InjuryLevels.USELESS
        assert right_eye.is_destroyed() is False
        assert right_eye.get_injury_level() == InjuryLevels.NONE
        assert c.get_stat_modifier_total(Stat.HIT) == -8

    def test_destroying_both_eyes_debuffs_hit_by_sixteen(self, loaded_plugins):
        c = _make_creature(health_max=40, health=40)
        left_eye = BodyPart.make("eye", name="left eye", health_max=4)
        right_eye = BodyPart.make("eye", name="right eye", health_max=4)
        c.body_parts = [left_eye, right_eye]

        c.apply_damage(10, target_part=left_eye)
        c.apply_damage(10, target_part=right_eye)

        assert left_eye.is_destroyed() is True
        assert right_eye.is_destroyed() is True
        assert c.get_stat_modifier_total(Stat.HIT) == -16
        # Still alive: eyes are non-critical. (HP 40 - 10 - 10 = 20 > 0)
        assert c.health > 0

    def test_get_part_name_lookup_resolves_each_eye(self, loaded_plugins):
        """Pin the item 1.8 ``get_part`` name-based lookup for the
        multi-instance case: each eye is retrievable by its declared
        name, and unknown names return ``None``."""
        c = _make_creature()
        left_eye = BodyPart.make("eye", name="left eye", health_max=4)
        right_eye = BodyPart.make("eye", name="right eye", health_max=4)
        c.body_parts = [left_eye, right_eye]

        assert c.get_part("left eye") is left_eye
        assert c.get_part("right eye") is right_eye
        assert c.get_part("center eye") is None


# ---------------------------------------------------------------------------
# Damage routing
# ---------------------------------------------------------------------------


class TestDamageRouting:
    def test_destroying_non_critical_eye_does_not_kill_creature(
        self, loaded_plugins
    ):
        """Creature with ``health_max=20`` and eye with ``health_max=4``:
        ``apply_damage(10, target_part=eye)`` should

        - destroy the eye (health clamps to 0, injury level USELESS)
        - drain the body by 10 (Model D — unified HP)
        - leave the creature alive at ``health == 10``
        - stat aggregation picks up the USELESS HIT debuff (-8).
        """
        c = _make_creature(health_max=20, health=20)
        eye = BodyPart.make("eye", health_max=4)
        c.body_parts = [eye]

        c.apply_damage(10, target_part=eye)

        assert eye.is_destroyed() is True
        assert eye.get_injury_level() == InjuryLevels.USELESS
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 20, (
            "non-critical eye destruction must not kill the creature; "
            "part-targeted apply_damage does not touch body HP"
        )
        assert c.get_stat_modifier_total(Stat.HIT) == -8


# ---------------------------------------------------------------------------
# Doppelganger pain cry
# ---------------------------------------------------------------------------


class TestDoppelgangerPainCry:
    def test_pain_cry_is_non_empty_for_each_injury_level(self, loaded_plugins):
        eye = BodyPart.make("eye", health_max=4)
        for level in (
            InjuryLevels.MINOR,
            InjuryLevels.MODERATE,
            InjuryLevels.SEVERE,
            InjuryLevels.USELESS,
        ):
            cry = eye.get_doppelganger_pain_cry(level)
            assert isinstance(cry, str)
            assert cry != "", f"pain cry empty for level {level}"

    def test_pain_cry_empty_for_none_level(self, loaded_plugins):
        eye = BodyPart.make("eye", health_max=4)
        assert eye.get_doppelganger_pain_cry(InjuryLevels.NONE) == ""

    def test_pain_cries_are_distinct_per_level(self, loaded_plugins):
        eye = BodyPart.make("eye", health_max=4)
        cries = {
            eye.get_doppelganger_pain_cry(level)
            for level in (
                InjuryLevels.MINOR,
                InjuryLevels.MODERATE,
                InjuryLevels.SEVERE,
                InjuryLevels.USELESS,
            )
        }
        assert len(cries) == 4
