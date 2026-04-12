"""Tests for the Phase 1 BodyPart extensions (item 1.3).

Covers:
- New `exposure` field — default and override; missing reach keys fall back
  to 1.0 at lookup time.
- New `debuffs` field — default is an empty dict.
- `is_destroyed()` boundary (health == 0).
- `get_stat_modifier()`:
    * returns 0 when debuffs table is empty,
    * returns the table value when the current injury level has an entry,
    * returns 0 when the current injury level isn't in the table.
- Hook methods (`get_injury_flavor`, `get_doppelganger_pain_cry`,
  `on_injury_change`, `on_destroyed`) return an empty string by default.
- The `BodyPart` import in ``Caldanai.lib.rpg.creatures.__init__`` is wired
  (item 1.3 uncomments it).
"""

from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class TestBodyPartExposureField:
    def test_default_exposure_has_all_four_reaches_at_1(self):
        part = BodyPart(name="arm", health_max=10)
        assert part.exposure[Reach.MELEE] == 1.0
        assert part.exposure[Reach.REACH] == 1.0
        assert part.exposure[Reach.THROWN] == 1.0
        assert part.exposure[Reach.RANGED] == 1.0

    def test_exposure_kwarg_overrides_default(self):
        part = BodyPart(
            name="head",
            health_max=10,
            exposure={Reach.MELEE: 0.05, Reach.RANGED: 1.0},
        )
        assert part.exposure[Reach.MELEE] == 0.05
        assert part.exposure[Reach.RANGED] == 1.0

    def test_missing_reach_keys_fall_back_to_one_at_lookup(self):
        """Per-design: missing reach keys default to 1.0 at lookup time."""
        part = BodyPart(
            name="head",
            health_max=10,
            exposure={Reach.MELEE: 0.05},
        )
        # The design uses `exposure.get(reach, 1.0)` at the call site, so
        # the dict is allowed to be sparse. Verify .get(..., 1.0) works.
        assert part.exposure.get(Reach.THROWN, 1.0) == 1.0
        assert part.exposure.get(Reach.RANGED, 1.0) == 1.0
        assert part.exposure.get(Reach.REACH, 1.0) == 1.0


class TestBodyPartDebuffsField:
    def test_default_debuffs_is_empty_dict(self):
        part = BodyPart(name="arm", health_max=10)
        assert part.debuffs == {}

    def test_debuffs_kwarg_overrides_default(self):
        table = {
            InjuryLevels.MINOR: {Stat.DODGE: -1},
            InjuryLevels.MODERATE: {Stat.DODGE: -3, Stat.ATTACK: -1},
        }
        part = BodyPart(name="leg", health_max=10, debuffs=table)
        assert part.debuffs is table


class TestBodyPartIsDestroyed:
    def test_not_destroyed_at_full_health(self):
        part = BodyPart(name="arm", health_max=10)
        assert part.is_destroyed() is False

    def test_not_destroyed_at_one_hp(self):
        part = BodyPart(name="arm", health_max=10)
        part.health = 1
        assert part.is_destroyed() is False

    def test_destroyed_at_zero_hp(self):
        part = BodyPart(name="arm", health_max=10)
        part.health = 0
        assert part.is_destroyed() is True

    def test_destroyed_at_negative_hp(self):
        part = BodyPart(name="arm", health_max=10)
        part.health = -3
        assert part.is_destroyed() is True


class TestBodyPartGetStatModifier:
    def test_returns_zero_when_debuffs_table_is_empty(self):
        part = BodyPart(name="arm", health_max=10)
        # NONE injury level, empty table → 0
        assert part.get_stat_modifier(Stat.DODGE, owner=None) == 0
        assert part.get_stat_modifier(Stat.ATTACK, owner=None) == 0

    def test_returns_debuff_value_at_current_injury_level(self):
        part = BodyPart(
            name="leg",
            health_max=10,
            debuffs={
                InjuryLevels.MINOR: {Stat.DODGE: -1},
                InjuryLevels.MODERATE: {Stat.DODGE: -3, Stat.ATTACK: -1},
            },
        )
        # Drop health into MODERATE band (0.30 <= % < 0.60)
        part.health = 4  # 40% → MODERATE
        assert part.get_injury_level() == InjuryLevels.MODERATE
        assert part.get_stat_modifier(Stat.DODGE, owner=None) == -3
        assert part.get_stat_modifier(Stat.ATTACK, owner=None) == -1

    def test_returns_zero_when_current_injury_level_not_in_table(self):
        part = BodyPart(
            name="leg",
            health_max=10,
            debuffs={
                InjuryLevels.SEVERE: {Stat.DODGE: -5},
                InjuryLevels.USELESS: {Stat.DODGE: -10},
            },
        )
        # Full health → NONE injury level, which is not in the table
        assert part.get_injury_level() == InjuryLevels.NONE
        assert part.get_stat_modifier(Stat.DODGE, owner=None) == 0

    def test_returns_zero_when_stat_not_in_level_entry(self):
        part = BodyPart(
            name="leg",
            health_max=10,
            debuffs={
                InjuryLevels.MINOR: {Stat.DODGE: -1},
            },
        )
        part.health = 7  # 70% → MINOR
        assert part.get_injury_level() == InjuryLevels.MINOR
        # DODGE is set, ATTACK is not → ATTACK should return 0
        assert part.get_stat_modifier(Stat.ATTACK, owner=None) == 0


class TestBodyPartHookDefaults:
    def test_get_injury_flavor_returns_empty_string(self):
        part = BodyPart(name="arm", health_max=10)
        for level in InjuryLevels:
            assert part.get_injury_flavor(level) == ""

    def test_get_doppelganger_pain_cry_returns_empty_string(self):
        part = BodyPart(name="arm", health_max=10)
        for level in InjuryLevels:
            assert part.get_doppelganger_pain_cry(level) == ""

    def test_on_injury_change_returns_empty_string(self):
        part = BodyPart(name="arm", health_max=10)
        assert (
            part.on_injury_change(
                creature=None,
                old_level=InjuryLevels.NONE,
                new_level=InjuryLevels.MINOR,
            )
            == ""
        )

    def test_on_destroyed_returns_empty_string(self):
        part = BodyPart(name="arm", health_max=10)
        assert part.on_destroyed(creature=None) == ""


class TestBodyPartConstructorCompat:
    def test_positional_and_existing_kwargs_still_work(self):
        """The existing positional/keyword args must remain supported."""
        part = BodyPart("arm", 10, is_critical=True, traits={})
        assert part.name == "arm"
        assert part.health_max == 10
        assert part.health == 10
        assert part.is_critical is True
        assert part.traits == {}

    def test_all_new_kwargs_accepted_together(self):
        part = BodyPart(
            name="head",
            health_max=8,
            is_critical=True,
            traits={},
            exposure={Reach.MELEE: 0.05},
            debuffs={InjuryLevels.MINOR: {Stat.HIT: -1}},
        )
        assert part.name == "head"
        assert part.is_critical is True
        assert part.exposure[Reach.MELEE] == 0.05
        assert part.debuffs[InjuryLevels.MINOR][Stat.HIT] == -1


class TestBodyPartImportWiring:
    def test_bodypart_importable_from_creatures_package(self):
        """Item 1.3 uncomments the BodyPart import in creatures/__init__.py."""
        from Caldanai.lib.rpg.creatures import BodyPart as ReexportedBodyPart

        assert ReexportedBodyPart is BodyPart


class TestBodyPartDisplayName:
    """Tests for the ``display_name`` property that converts codified
    dot-notation names to human-readable output."""

    def test_simple_name_unchanged(self):
        p = BodyPart(name="head", health_max=10)
        assert p.display_name == "head"

    def test_directional_qualifier_moves_before_base(self):
        p = BodyPart(name="arm.left", health_max=10)
        assert p.display_name == "left arm"

    def test_directional_right(self):
        p = BodyPart(name="leg.right", health_max=10)
        assert p.display_name == "right leg"

    def test_quadruped_foreleg(self):
        p = BodyPart(name="foreleg.left", health_max=10)
        assert p.display_name == "left foreleg"

    def test_quadruped_hindleg(self):
        p = BodyPart(name="hindleg.right", health_max=10)
        assert p.display_name == "right hindleg"

    def test_wing(self):
        p = BodyPart(name="wing.left", health_max=10)
        assert p.display_name == "left wing"

    def test_numeric_qualifier_stays_after_base(self):
        p = BodyPart(name="head.2", health_max=10)
        assert p.display_name == "head 2"

    def test_numeric_large_number(self):
        p = BodyPart(name="head.47", health_max=10)
        assert p.display_name == "head 47"

    def test_torso_no_qualifier(self):
        p = BodyPart(name="torso", health_max=10)
        assert p.display_name == "torso"

    def test_tail_no_qualifier(self):
        p = BodyPart(name="tail", health_max=10)
        assert p.display_name == "tail"
