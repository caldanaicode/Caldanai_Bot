"""Tests for Creature stat-modifier aggregation across body parts (item 1.10).

This item wires ``Creature.get_defense`` and ``Creature.get_dodge`` to
aggregate ``part.get_stat_modifier(stat, owner=self)`` across **all** body
parts (including destroyed/USELESS parts), and introduces a reusable helper
``Creature.get_stat_modifier_total(stat)`` that performs the aggregation.

Load-bearing architectural points pinned by these tests:

1. **USELESS debuffs still apply.** A destroyed part (health <= 0) is at
   ``InjuryLevels.USELESS`` — the *most severe* row of the debuffs table.
   Filtering destroyed parts out of the aggregation would erase the
   maximum-severity debuff at the exact moment it should matter most.
   ``get_stat_modifier_total`` iterates ``self.body_parts`` directly (NOT
   ``get_targetable_parts()``) to preserve this.

2. **``owner=self`` is passed through.** State-dependent parts (dragon
   toes, blocking arms, etc.) override ``get_stat_modifier`` to read
   flags/state off the owner. Every caller in the aggregation path must
   forward the creature instance so those overrides can see it.

3. **Backwards compatibility.** Creatures with no body parts (every
   currently-migrated creature) return ``get_defense()`` / ``get_dodge()``
   unchanged from their raw ``self.defense`` / ``self.dodge`` values.
"""

from typing import List, Optional

from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.helpers.enums import InjuryLevels, Stat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_creature(**kwargs) -> Creature:
    """Create a Creature with sensible defaults; kwargs override."""
    defaults = dict(
        name="goblin",
        atk="1d4",
        defense=10,
        dodge=5,
        health_max=20,
        health=20,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


class _RecordingPart(BodyPart):
    """BodyPart subclass that records every ``get_stat_modifier`` call.

    Used to pin the ``owner=self`` pass-through contract: callers of the
    aggregator must forward the owning creature instance so future
    state-dependent parts (e.g. dragon toes that read ``owner.flags``)
    can see it.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls: List[tuple] = []  # (stat, owner) pairs

    def get_stat_modifier(self, stat: Stat, owner: "Creature") -> int:
        self.calls.append((stat, owner))
        return super().get_stat_modifier(stat, owner)


class _FlagDependentPart(BodyPart):
    """Standalone test fixture: contributes -1 dodge only while the
    owner is **not** flying. Pins the ``owner=self`` contract end-to-end
    for any flag-dependent body part pattern.
    """

    def get_stat_modifier(self, stat: Stat, owner: "Creature") -> int:
        if stat != Stat.DODGE:
            return 0
        if "flying" in owner.flags:
            return 0
        return -1


def _destroy(part: BodyPart) -> None:
    """Drive a part to USELESS by zeroing its health directly.

    We don't route through ``Creature.apply_damage`` here — these tests
    care about the stat-aggregation contract, not the damage pipeline.
    """
    part.health = 0
    assert part.is_destroyed()
    assert part.get_injury_level() == InjuryLevels.USELESS


# ---------------------------------------------------------------------------
# get_stat_modifier_total helper
# ---------------------------------------------------------------------------


class TestGetStatModifierTotal:
    def test_returns_zero_when_no_body_parts(self):
        c = _make_creature()
        assert c.body_parts == []
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert c.get_stat_modifier_total(Stat.ATTACK) == 0

    def test_returns_zero_when_no_parts_have_entry_for_stat(self):
        c = _make_creature()
        # Two parts, both with DODGE debuffs but neither with DEFENSE.
        c.body_parts = [
            BodyPart(
                name="leg 1",
                health_max=10,
                debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
            ),
            BodyPart(
                name="leg 2",
                health_max=10,
                debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
            ),
        ]
        # Drive both to MINOR so their DODGE entry is active.
        for p in c.body_parts:
            p.health = 7  # 70% -> MINOR
        assert c.get_stat_modifier_total(Stat.DEFENSE) == 0

    def test_sums_across_multiple_parts(self):
        c = _make_creature()
        c.body_parts = [
            BodyPart(
                name="leg 1",
                health_max=10,
                debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
            ),
            BodyPart(
                name="leg 2",
                health_max=10,
                debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
            ),
        ]
        # Drive both to MINOR (70% health).
        for p in c.body_parts:
            p.health = 7
        assert c.get_stat_modifier_total(Stat.DODGE) == -2

    def test_destroyed_part_useless_debuff_still_applies(self):
        """Load-bearing: iterating ALL parts (not just targetable) means a
        destroyed part's USELESS debuff row still contributes.
        """
        c = _make_creature()
        useless_part = BodyPart(
            name="severed arm",
            health_max=10,
            debuffs={
                InjuryLevels.MINOR: {Stat.ATTACK: -1},
                InjuryLevels.MODERATE: {Stat.ATTACK: -2},
                InjuryLevels.SEVERE: {Stat.ATTACK: -3},
                InjuryLevels.USELESS: {Stat.ATTACK: -5},
            },
        )
        _destroy(useless_part)
        c.body_parts = [useless_part]

        # Sanity: the destroyed part is NOT in the targetable pool, but
        # IS still in body_parts — this is the exact case the design
        # calls out.
        assert useless_part not in c.get_targetable_parts()
        assert useless_part in c.body_parts

        # The USELESS row must still contribute.
        assert c.get_stat_modifier_total(Stat.ATTACK) == -5

    def test_destroyed_and_living_parts_aggregate_together(self):
        c = _make_creature()
        destroyed = BodyPart(
            name="severed leg",
            health_max=10,
            debuffs={InjuryLevels.USELESS: {Stat.DODGE: -10}},
        )
        _destroy(destroyed)
        living = BodyPart(
            name="bruised leg",
            health_max=10,
            debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
        )
        living.health = 7  # MINOR
        c.body_parts = [destroyed, living]
        assert c.get_stat_modifier_total(Stat.DODGE) == -11

    def test_passes_owner_self_through_to_parts(self):
        c = _make_creature()
        part = _RecordingPart(name="arm", health_max=10)
        c.body_parts = [part]
        c.get_stat_modifier_total(Stat.DEFENSE)
        assert len(part.calls) == 1
        stat, owner = part.calls[0]
        assert stat == Stat.DEFENSE
        assert owner is c


# ---------------------------------------------------------------------------
# get_defense
# ---------------------------------------------------------------------------


class TestGetDefense:
    def test_returns_base_when_no_parts(self):
        c = _make_creature(defense=10)
        assert c.get_defense() == 10

    def test_applies_negative_part_modifier(self):
        c = _make_creature(defense=10)
        part = BodyPart(
            name="arm",
            health_max=10,
            debuffs={InjuryLevels.MINOR: {Stat.DEFENSE: -3}},
        )
        part.health = 7  # MINOR
        c.body_parts = [part]
        assert c.get_defense() == 7

    def test_clamps_at_zero(self):
        c = _make_creature(defense=5)
        part = BodyPart(
            name="arm",
            health_max=10,
            debuffs={InjuryLevels.MINOR: {Stat.DEFENSE: -10}},
        )
        part.health = 7  # MINOR
        c.body_parts = [part]
        assert c.get_defense() == 0

    def test_compounds_across_multiple_parts(self):
        c = _make_creature(defense=10)
        parts = [
            BodyPart(
                name=f"arm {i}",
                health_max=10,
                debuffs={InjuryLevels.MINOR: {Stat.DEFENSE: -2}},
            )
            for i in range(3)
        ]
        for p in parts:
            p.health = 7
        c.body_parts = parts
        assert c.get_defense() == 10 - 6

    def test_destroyed_part_useless_debuff_still_reduces_defense(self):
        c = _make_creature(defense=10)
        part = BodyPart(
            name="shield arm",
            health_max=10,
            debuffs={InjuryLevels.USELESS: {Stat.DEFENSE: -4}},
        )
        _destroy(part)
        c.body_parts = [part]
        assert c.get_defense() == 6


# ---------------------------------------------------------------------------
# get_dodge
# ---------------------------------------------------------------------------


class TestGetDodge:
    def test_returns_base_when_no_parts(self):
        c = _make_creature(dodge=5)
        assert c.get_dodge() == 5

    def test_applies_negative_part_modifier(self):
        c = _make_creature(dodge=5)
        part = BodyPart(
            name="leg",
            health_max=10,
            debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
        )
        part.health = 7  # MINOR
        c.body_parts = [part]
        assert c.get_dodge() == 4

    def test_clamps_at_zero(self):
        c = _make_creature(dodge=3)
        part = BodyPart(
            name="leg",
            health_max=10,
            debuffs={InjuryLevels.MINOR: {Stat.DODGE: -10}},
        )
        part.health = 7  # MINOR
        c.body_parts = [part]
        assert c.get_dodge() == 0

    def test_compounds_across_multiple_parts(self):
        c = _make_creature(dodge=10)
        parts = [
            BodyPart(
                name=f"leg {i}",
                health_max=10,
                debuffs={InjuryLevels.MINOR: {Stat.DODGE: -1}},
            )
            for i in range(4)
        ]
        for p in parts:
            p.health = 7
        c.body_parts = parts
        assert c.get_dodge() == 6

    def test_destroyed_part_useless_debuff_still_reduces_dodge(self):
        c = _make_creature(dodge=10)
        part = BodyPart(
            name="severed leg",
            health_max=10,
            debuffs={InjuryLevels.USELESS: {Stat.DODGE: -10}},
        )
        _destroy(part)
        c.body_parts = [part]
        assert c.get_dodge() == 0


# ---------------------------------------------------------------------------
# State-dependent debuffs via owner=self pass-through
# ---------------------------------------------------------------------------


class TestStateDependentDebuff:
    """Tests the flag-dependent body part pattern: a part that reads
    ``owner.flags`` to decide its contribution. Pins the ``owner=self``
    contract end-to-end through ``get_dodge``.
    """

    def test_flag_toggles_aggregate_modifier(self):
        c = _make_creature(dodge=10)
        c.flags.add("flying")
        parts = [_FlagDependentPart(name=f"part {i}", health_max=1) for i in range(5)]
        c.body_parts = parts

        # Airborne: the parts see ``"flying" in owner.flags`` and
        # contribute nothing.
        assert c.get_stat_modifier_total(Stat.DODGE) == 0
        assert c.get_dodge() == 10

        # Ground the creature: each part now contributes -1 dodge.
        c.flags.discard("flying")
        assert c.get_stat_modifier_total(Stat.DODGE) == -5
        assert c.get_dodge() == 5

    def test_adding_flag_midway_changes_aggregated_total(self):
        c = _make_creature(dodge=10)
        part = _FlagDependentPart(name="flag_part", health_max=1)
        c.body_parts = [part]
        # No flag set: grounded → contributes -1.
        assert c.get_dodge() == 9
        # Add the flying flag: airborne → contributes 0.
        c.flags.add("flying")
        assert c.get_dodge() == 10
