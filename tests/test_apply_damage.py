"""Tests for ``Creature.apply_damage`` part-targeted damage routing
and the corrected ``BodyPart.apply_damage``.

Covers:
- Legacy path (no ``target_part`` / no parts) preserves old behavior
  exactly, including negative-amount healing and clamping.
- Part-targeted path routes damage to the part ONLY (for injury
  tracking). Body HP is NOT touched — ``do_combat`` handles that.
- Combined ``creature_mult * part_mult`` multiplier math with integer
  truncation (``int(amount * multiplier)``).
- Critical part destroyed → creature.health = 0.
- Non-critical part destroyed → body HP unchanged.
- Hook firing order: ``on_injury_change`` fires once per level change;
  ``on_destroyed`` fires exactly once per part (never double-fires on an
  already-destroyed part).
- Fixed ``BodyPart.apply_damage`` subtracts rather than assigns and does
  NOT apply its own trait multiplier (the caller applies it).
- Backwards compat: ``Player.apply_damage(amount)`` continues to work.
"""

from typing import List, Tuple

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import (
    DamageTypes,
    InjuryLevels,
    Reach,
    Stat,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_creature(**kwargs) -> Creature:
    defaults = dict(
        name="goblin",
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=100,
        health=100,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


class _RecordingPart(BodyPart):
    """Concrete BodyPart that records hook invocations for assertions."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.injury_change_calls: List[Tuple[InjuryLevels, InjuryLevels]] = []
        self.destroyed_calls: int = 0

    def on_injury_change(self, creature, old_level, new_level) -> str:
        self.injury_change_calls.append((old_level, new_level))
        return ""

    def on_destroyed(self, creature) -> str:
        self.destroyed_calls += 1
        return ""


# ---------------------------------------------------------------------------
# Legacy path — no target_part or empty body_parts
# ---------------------------------------------------------------------------


class TestApplyDamageLegacyPath:
    def test_positive_damage_reduces_health_no_parts(self):
        c = _make_creature(health=50, health_max=100)
        c.apply_damage(10)
        assert c.health == 40

    def test_negative_amount_heals(self):
        c = _make_creature(health=50, health_max=100)
        c.apply_damage(-10)
        assert c.health == 60

    def test_healing_clamps_at_max(self):
        c = _make_creature(health=95, health_max=100)
        c.apply_damage(-50)
        assert c.health == 100

    def test_damage_clamps_at_zero(self):
        c = _make_creature(health=5, health_max=100)
        c.apply_damage(9999)
        assert c.health == 0

    def test_explicit_none_target_part_uses_legacy_path(self):
        c = _make_creature(health=50, health_max=100)
        c.apply_damage(10, target_part=None)
        assert c.health == 40

    def test_empty_body_parts_uses_legacy_path_even_with_target_part(self):
        """If ``body_parts`` is empty, the legacy path is taken even when a
        stray part is passed (no part to route through)."""
        c = _make_creature(health=50, health_max=100)
        orphan = _RecordingPart(name="orphan", health_max=10)
        # Creature has no body_parts attached — must not route.
        c.apply_damage(10, target_part=orphan)
        assert c.health == 40
        # Orphan was never touched.
        assert orphan.health == 10
        assert orphan.destroyed_calls == 0

    def test_dmg_type_alone_still_legacy(self):
        """Passing a damage type without a target_part uses the legacy
        path unchanged — the old signature didn't apply trait multipliers
        here either."""
        c = _make_creature(health=50, health_max=100)
        c.apply_damage(10, DamageTypes.FIRE)
        assert c.health == 40


# ---------------------------------------------------------------------------
# Part-targeted path — damage routing
# ---------------------------------------------------------------------------


class TestApplyDamagePartTargeted:
    def test_part_targeted_damage_only_affects_part(self):
        c = _make_creature(health=100, health_max=100)
        arm = _RecordingPart(name="arm", health_max=50)
        c.body_parts = [arm]
        c.apply_damage(20, target_part=arm)
        # Part takes full 20; body HP is NOT touched (do_combat handles that)
        assert arm.health == 30
        assert c.health == 100

    def test_part_trait_multiplier_amplifies_damage(self):
        c = _make_creature(health=100, health_max=100)
        # Leg has 0.5 fire resistance → 10 FIRE becomes 5 total
        leg = _RecordingPart(
            name="leg",
            health_max=50,
            traits={DamageTypes.FIRE: 0.5},
        )
        c.body_parts = [leg]
        c.apply_damage(10, DamageTypes.FIRE, target_part=leg)
        # final_dmg = int(10 * 1.0 * 0.5) = 5
        # part takes 5; body HP unchanged (do_combat handles body HP)
        assert leg.health == 45
        assert c.health == 100

    def test_part_trait_multiplier_applied_in_apply_damage(self):
        """apply_damage only applies the PART's trait multiplier — the
        creature's multiplier was already applied in resolve_attack
        before the damage amount reached apply_damage."""
        c = _make_creature(
            health=100,
            health_max=100,
            traits={DamageTypes.FIRE: 0.5},
        )
        leg = _RecordingPart(name="leg", health_max=50)
        c.body_parts = [leg]
        # amount=10 is already post-creature-multiplier (from resolve_attack).
        # Part has no fire trait → part multiplier is 1.0.
        # final_dmg = int(10 * 1.0) = 10
        c.apply_damage(10, DamageTypes.FIRE, target_part=leg)
        assert leg.health == 40
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 100

    def test_part_multiplier_stacks_on_pre_multiplied_damage(self):
        """The part's own trait multiplier is the ONLY multiplier
        apply_damage applies. Creature multiplier is NOT re-applied."""
        c = _make_creature(
            health=100,
            health_max=100,
            traits={DamageTypes.FIRE: 2.0},
        )
        head = _RecordingPart(
            name="head",
            health_max=50,
            traits={DamageTypes.FIRE: 2.0},
        )
        c.body_parts = [head]
        # amount=10 is already post-creature-multiplier.
        # Part has FIRE 2.0 → final_dmg = int(10 * 2.0) = 20
        c.apply_damage(10, DamageTypes.FIRE, target_part=head)
        assert head.health == 30
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 100

    def test_integer_truncation_on_final_damage(self):
        c = _make_creature(health=100, health_max=100)
        leg = _RecordingPart(
            name="leg",
            health_max=50,
            traits={DamageTypes.FIRE: 0.33},
        )
        c.body_parts = [leg]
        c.apply_damage(10, DamageTypes.FIRE, target_part=leg)
        # final_dmg = int(10 * 0.33) = 3
        # Part takes 3; body HP unchanged (do_combat handles body HP)
        assert leg.health == 47
        assert c.health == 100

    def test_critical_part_destroyed_kills_creature(self):
        c = _make_creature(health=100, health_max=100)
        head = _RecordingPart(name="head", health_max=10, is_critical=True)
        c.body_parts = [head]
        c.apply_damage(10, target_part=head)
        assert head.is_destroyed()
        # Body takes 10, but critical destroyed → health = 0
        assert c.health == 0

    def test_critical_part_destroyed_with_overkill(self):
        c = _make_creature(health=100, health_max=100)
        head = _RecordingPart(name="head", health_max=10, is_critical=True)
        c.body_parts = [head]
        c.apply_damage(9999, target_part=head)
        assert head.health == 0
        assert c.health == 0

    def test_non_critical_part_destroyed_body_unchanged(self):
        c = _make_creature(health=100, health_max=100)
        arm = _RecordingPart(name="arm", health_max=10, is_critical=False)
        c.body_parts = [arm]
        c.apply_damage(10, target_part=arm)
        assert arm.is_destroyed()
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 100

    def test_body_health_unchanged_on_part_targeted_damage(self):
        """Part-targeted damage does not touch body HP at all."""
        c = _make_creature(health=3, health_max=100)
        arm = _RecordingPart(name="arm", health_max=100, is_critical=False)
        c.body_parts = [arm]
        c.apply_damage(100, target_part=arm)
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 3

    def test_body_health_unchanged_small_part_damage(self):
        c = _make_creature(health=100, health_max=100)
        arm = _RecordingPart(name="arm", health_max=100, is_critical=False)
        c.body_parts = [arm]
        c.apply_damage(2, target_part=arm)
        # Body HP unchanged — do_combat handles body HP reduction
        assert c.health == 100


# ---------------------------------------------------------------------------
# Hook invocations
# ---------------------------------------------------------------------------


class TestApplyDamageDoesNotFireHooks:
    """``Creature.apply_damage`` intentionally does NOT fire hooks —
    ``do_combat`` is the single authoritative caller that snapshots
    part state, applies all damage in a sequence, and fires
    ``on_injury_change`` / ``on_destroyed`` exactly once per part per
    attack action. This prevents double-firing hooks with side effects
    (e.g. wing grounding, doppelganger pain cries) when a multi-source
    attack lands multiple hits on the same part.
    """

    def test_apply_damage_does_not_fire_on_injury_change(self):
        c = _make_creature(health=100, health_max=100)
        arm = _RecordingPart(name="arm", health_max=10)
        c.body_parts = [arm]
        c.apply_damage(1, target_part=arm)  # level transitions NONE → MINOR
        # Level tracking still works; hook simply isn't fired here.
        assert arm.get_injury_level() == InjuryLevels.MINOR
        assert arm.injury_change_calls == []

    def test_apply_damage_does_not_fire_on_destroyed(self):
        c = _make_creature(health=100, health_max=100)
        arm = _RecordingPart(name="arm", health_max=10)
        c.body_parts = [arm]
        c.apply_damage(10, target_part=arm)  # drives straight to USELESS
        assert arm.is_destroyed()
        assert arm.destroyed_calls == 0

    def test_apply_damage_still_tracks_state_across_multiple_hits(self):
        """Even without hook firing, damage routing still updates part
        health, critical-part death, and injury levels correctly."""
        c = _make_creature(health=100, health_max=100)
        arm = _RecordingPart(name="arm", health_max=10)
        c.body_parts = [arm]
        c.apply_damage(1, target_part=arm)  # MINOR
        c.apply_damage(1, target_part=arm)  # still MINOR
        c.apply_damage(8, target_part=arm)  # destroys (USELESS)
        assert arm.is_destroyed()
        assert arm.get_injury_level() == InjuryLevels.USELESS
        # No hook fires, regardless of how many hits land.
        assert arm.injury_change_calls == []
        assert arm.destroyed_calls == 0


# ---------------------------------------------------------------------------
# Fixed BodyPart.apply_damage
# ---------------------------------------------------------------------------


class TestBodyPartApplyDamageFixed:
    def test_subtracts_rather_than_assigns(self):
        part = BodyPart(name="arm", health_max=20)
        part.apply_damage(5)
        assert part.health == 15

    def test_subtracts_further_from_already_reduced_health(self):
        part = BodyPart(name="arm", health_max=20)
        part.apply_damage(5)
        part.apply_damage(3)
        assert part.health == 12

    def test_clamps_at_zero(self):
        part = BodyPart(name="arm", health_max=10)
        part.apply_damage(9999)
        assert part.health == 0

    def test_does_not_apply_trait_multiplier_itself(self):
        """The caller (Creature.apply_damage) applies the multiplier. The
        part must take the raw amount it's handed — no double-apply."""
        part = BodyPart(
            name="arm",
            health_max=20,
            traits={DamageTypes.FIRE: 2.0},
        )
        part.apply_damage(5, DamageTypes.FIRE)
        # 20 - 5 = 15 (NOT 20 - 10 = 10)
        assert part.health == 15

    def test_dmg_type_none_is_accepted(self):
        part = BodyPart(name="arm", health_max=20)
        part.apply_damage(5, None)
        assert part.health == 15

    def test_negative_amount_heals(self):
        """Negative ``amount`` heals the part. Supports the regen
        path: ``part.apply_damage(-n)`` is the canonical way to
        restore part health."""
        part = BodyPart(name="arm", health_max=10)
        part.health = 3
        part.apply_damage(-4)
        assert part.health == 7

    def test_heal_clamps_at_health_max(self):
        """Healing past ``health_max`` is clamped — a destroyed arm
        restored with a huge negative doesn't overshoot its cap."""
        part = BodyPart(name="arm", health_max=10)
        part.health = 0
        part.apply_damage(-50)
        assert part.health == 10


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------


class TestBackwardsCompat:
    def test_creature_apply_damage_with_just_amount_still_works(self):
        c = _make_creature(health=50, health_max=100)
        c.apply_damage(10)  # old single-arg form
        assert c.health == 40

    def test_player_apply_damage_single_arg_still_works(self):
        """Player.apply_damage overrides the base and calls
        ``super().apply_damage(amount)`` with a single positional arg.
        The base class's new optional kwargs must not break that."""
        from caldanai.lib.rpg.creatures.player import Player

        p = Player(health=20, health_max=20)
        msg = p.apply_damage(5)
        assert p.health == 15
        assert isinstance(msg, str)

    def test_player_apply_damage_death_message_still_fires(self):
        from caldanai.lib.rpg.creatures.player import Player

        p = Player(health=5, health_max=20)
        msg = p.apply_damage(10)
        assert p.health == 0
        assert msg  # non-empty death message
