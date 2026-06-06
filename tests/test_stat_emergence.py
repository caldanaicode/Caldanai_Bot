"""Tests for Q.5 Phase A — stat emergence from body parts.

Stats (dodge, defense, HIT) emerge from body-part functionality, creature
size, and core properties rather than flat base + debuff-modifier.
"""

from caldanai.lib.rpg.creatures import (
    Creature,
    GROUNDED_FLYER_DODGE_PENALTY,
    _functionality_ratio,
    _part_base_name,
)
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Size, Stat


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_creature(**kwargs) -> Creature:
    """Create a Creature with sensible defaults; kwargs override."""
    defaults = dict(
        name="test_creature",
        atk="1d4",
        defense=10,
        dodge=10,
        health_max=50,
        health=50,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


def _injure_to(part: BodyPart, level: InjuryLevels) -> None:
    """Drive a part to a specific injury level."""
    if level == InjuryLevels.NONE:
        part.health = part.health_max
    elif level == InjuryLevels.MINOR:
        part.health = int(part.health_max * 0.7)
    elif level == InjuryLevels.MODERATE:
        part.health = int(part.health_max * 0.45)
    elif level == InjuryLevels.SEVERE:
        part.health = int(part.health_max * 0.15)
    elif level == InjuryLevels.USELESS:
        part.health = 0


# ---------------------------------------------------------------------------
# _functionality_ratio
# ---------------------------------------------------------------------------


class TestFunctionalityRatio:
    def test_empty_list_returns_zero(self):
        assert _functionality_ratio([]) == 0.0

    def test_all_healthy_returns_one(self):
        parts = BodyPart.humanoid()
        assert _functionality_ratio(parts) == 1.0

    def test_all_destroyed_returns_zero(self):
        parts = BodyPart.humanoid()
        for p in parts:
            p.health = 0
        assert _functionality_ratio(parts) == 0.0

    def test_mixed_none_and_useless(self):
        """1 healthy + 1 destroyed → (1.0 + 0.0) / 2 = 0.5."""
        legs = [
            BodyPart.make("leg", name="leg.left"),
            BodyPart.make("leg", name="leg.right"),
        ]
        legs[1].health = 0  # USELESS
        assert _functionality_ratio(legs) == 0.5

    def test_minor_injury_weight(self):
        """A single part at MINOR → 0.8."""
        part = BodyPart.make("leg", name="leg.left")
        # Force a large health_max so rounding doesn't change the injury level.
        part.health_max = 100
        part.health = 100
        _injure_to(part, InjuryLevels.MINOR)
        assert part.get_injury_level() == InjuryLevels.MINOR
        assert _functionality_ratio([part]) == 0.8

    def test_moderate_injury_weight(self):
        """A single part at MODERATE → 0.5."""
        part = BodyPart.make("leg", name="leg.left")
        part.health_max = 100
        part.health = 100
        _injure_to(part, InjuryLevels.MODERATE)
        assert part.get_injury_level() == InjuryLevels.MODERATE
        assert _functionality_ratio([part]) == 0.5

    def test_severe_injury_weight(self):
        """A single part at SEVERE → 0.25."""
        part = BodyPart.make("leg", name="leg.left")
        part.health_max = 100
        part.health = 100
        _injure_to(part, InjuryLevels.SEVERE)
        assert part.get_injury_level() == InjuryLevels.SEVERE
        assert _functionality_ratio([part]) == 0.25


# ---------------------------------------------------------------------------
# Size enum
# ---------------------------------------------------------------------------


class TestSizeEnum:
    def test_all_six_sizes_exist(self):
        assert len(Size) == 6
        for name in ("TINY", "SMALL", "MEDIUM", "LARGE", "HUGE", "COLOSSAL"):
            assert hasattr(Size, name)

    def test_each_has_required_keys(self):
        for size in Size:
            assert "dodge_mod" in size.value
            assert "defense_mod" in size.value
            assert "hp_scale" in size.value

    def test_medium_is_neutral(self):
        m = Size.MEDIUM.value
        assert m["dodge_mod"] == 1.0
        assert m["defense_mod"] == 1.0
        assert m["hp_scale"] == 1.0

    def test_dodge_mod_decreases_with_size(self):
        sizes = [Size.TINY, Size.SMALL, Size.MEDIUM, Size.LARGE, Size.HUGE, Size.COLOSSAL]
        dodge_mods = [s.value["dodge_mod"] for s in sizes]
        for i in range(len(dodge_mods) - 1):
            assert dodge_mods[i] > dodge_mods[i + 1], (
                f"{sizes[i].name} dodge_mod ({dodge_mods[i]}) should be > "
                f"{sizes[i + 1].name} dodge_mod ({dodge_mods[i + 1]})"
            )

    def test_defense_mod_increases_with_size(self):
        sizes = [Size.TINY, Size.SMALL, Size.MEDIUM, Size.LARGE, Size.HUGE, Size.COLOSSAL]
        defense_mods = [s.value["defense_mod"] for s in sizes]
        for i in range(len(defense_mods) - 1):
            assert defense_mods[i] < defense_mods[i + 1], (
                f"{sizes[i].name} defense_mod ({defense_mods[i]}) should be < "
                f"{sizes[i + 1].name} defense_mod ({defense_mods[i + 1]})"
            )


# ---------------------------------------------------------------------------
# Dodge emergence
# ---------------------------------------------------------------------------


class TestDodgeEmergence:
    def test_no_body_parts_uses_flat_stat(self):
        """Legacy path: creature with no body parts returns raw dodge."""
        c = _make_creature(dodge=10)
        assert c.body_parts == []
        assert c.get_dodge() == 10

    def test_grounded_creature_uses_legs(self):
        """A grounded creature's dodge comes from legs."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.body_parts = BodyPart.humanoid()
        # All legs healthy → ratio 1.0, size mod 1.0 → dodge = 10
        dodge = c.get_dodge()
        assert dodge == 10

    def test_flying_creature_uses_wings(self):
        """A flying creature's dodge comes from wings, not legs."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.flags.add("flying")
        c.body_parts = BodyPart.quadruped_winged()
        # All wings healthy → ratio 1.0, size mod 1.0 → dodge = 10
        assert c.get_dodge() == 10

    def test_grounded_flyer_dodge_halved_by_penalty(self):
        """Regression (LIVE 2026-06-04): a winged creature on the ground
        keeps only ``GROUNDED_FLYER_DODGE_PENALTY`` of its leg-based
        dodge. Without this, grounded legs substitute for wings 1:1 and
        destroying every wing left dodge unchanged (the pixie stayed at
        31 with both wings gone)."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.body_parts = BodyPart.quadruped_winged()  # has wings, NOT flying
        # legs ratio 1.0, size 1.0, then × the grounded-flyer penalty.
        assert c.get_dodge() == int(10 * 1.0 * 1.0 * GROUNDED_FLYER_DODGE_PENALTY)

    def test_flying_dodge_is_double_grounded_for_a_flyer(self):
        """Same creature: airborne dodge exceeds grounded dodge purely
        because grounding triggers the flyer penalty (legs and wings are
        both at full functionality). This is what makes destroying a
        flyer's wings actually lower its dodge."""
        flying = _make_creature(dodge=10)
        flying.size = Size.MEDIUM
        flying.flags.add("flying")
        flying.body_parts = BodyPart.quadruped_winged()

        grounded = _make_creature(dodge=10)
        grounded.size = Size.MEDIUM
        grounded.body_parts = BodyPart.quadruped_winged()

        assert grounded.get_dodge() < flying.get_dodge()
        assert grounded.get_dodge() == int(
            flying.get_dodge() * GROUNDED_FLYER_DODGE_PENALTY
        )

    def test_grounded_non_flyer_not_penalized(self):
        """A creature with NO wings (humanoid) is not a flyer, so the
        grounded-flyer penalty must not touch its leg-based dodge."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.body_parts = BodyPart.humanoid()  # no wings
        assert c.get_dodge() == 10  # full, un-penalized

    def test_all_legs_destroyed_returns_core_agility(self):
        """When all legs are destroyed, dodge falls to core_agility."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.core_agility = 0
        c.body_parts = BodyPart.humanoid()
        for p in c.body_parts:
            if _part_base_name(p) == "leg":
                p.health = 0
        assert c.get_dodge() == 0

    def test_large_creature_dodge_modifier(self):
        """LARGE size applies 0.75x dodge modifier."""
        c = _make_creature(dodge=10)
        c.size = Size.LARGE
        c.body_parts = BodyPart.humanoid()
        # ratio 1.0, size mod 0.75 → int(10 * 1.0 * 0.75) + 0 = 7
        assert c.get_dodge() == 7

    def test_core_agility_adds_to_dodge(self):
        """core_agility is added on top of the ratio * size calculation."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.core_agility = 5
        c.body_parts = BodyPart.humanoid()
        # ratio 1.0, size 1.0 → int(10 * 1.0 * 1.0) + 5 = 15
        assert c.get_dodge() == 15

    def test_core_agility_nonzero_when_no_mobility_sources(self):
        """Creature with core_agility but no legs/wings still has dodge."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.core_agility = 5
        # Body parts with no legs or wings (just a torso and head)
        c.body_parts = [
            BodyPart.make("head", name="head"),
            BodyPart.make("torso", name="torso"),
        ]
        assert c.get_dodge() == 5

    def test_injured_legs_reduce_dodge(self):
        """Partially injured legs reduce dodge proportionally."""
        c = _make_creature(dodge=10)
        c.size = Size.MEDIUM
        c.body_parts = BodyPart.humanoid()
        legs = [p for p in c.body_parts if _part_base_name(p) == "leg"]
        # Destroy one leg, keep other healthy → ratio = (1.0 + 0.0) / 2 = 0.5
        legs[0].health = 0
        # int(10 * 0.5 * 1.0) + 0 = 5
        assert c.get_dodge() == 5

    def test_huge_creature_low_dodge_floors_at_one(self):
        """A healthy HUGE creature that rolled 1 on its dodge dice
        shouldn't end up with 0 dodge. ``int(1 * 1.0 * 0.5) = 0``
        without the floor — which surfaced at playtest as a giant
        with 0 dodge ("shouldn't be possible"). Floor kicks in when
        any mobility remains.
        """
        c = _make_creature(dodge=1)
        c.size = Size.HUGE
        c.body_parts = BodyPart.humanoid()
        assert c.get_dodge() == 1

    def test_colossal_creature_low_dodge_floors_at_one(self):
        """COLOSSAL (dodge_mod 0.25) can truncate to 0 on rolls 1-3
        of a 1d4. Floor guarantees at least 1 while mobile."""
        c = _make_creature(dodge=2)
        c.size = Size.COLOSSAL
        c.body_parts = BodyPart.humanoid()
        # int(2 * 1.0 * 0.25) = 0 without the floor; 1 with it.
        assert c.get_dodge() == 1

    def test_all_legs_destroyed_still_yields_zero(self):
        """The floor is conditional on mobility remaining. A creature
        with all legs destroyed still has 0 dodge — the floor only
        kicks in when ``_functionality_ratio`` is positive."""
        c = _make_creature(dodge=10)
        c.size = Size.HUGE
        c.body_parts = BodyPart.humanoid()
        for leg in [p for p in c.body_parts if _part_base_name(p) == "leg"]:
            leg.health = 0
        assert c.get_dodge() == 0


# ---------------------------------------------------------------------------
# Defense emergence
# ---------------------------------------------------------------------------


class TestDefenseEmergence:
    def test_no_body_parts_uses_flat_stat(self):
        c = _make_creature(defense=10)
        assert c.body_parts == []
        assert c.get_defense() == 10

    def test_healthy_torso_gives_full_defense(self):
        c = _make_creature(defense=10)
        c.size = Size.MEDIUM
        c.body_parts = BodyPart.humanoid()
        assert c.get_defense() == 10

    def test_large_creature_defense_modifier(self):
        """LARGE size applies 1.25x defense modifier."""
        c = _make_creature(defense=10)
        c.size = Size.LARGE
        c.body_parts = BodyPart.humanoid()
        # ratio 1.0, size mod 1.25 → int(10 * 1.0 * 1.25) + 0 = 12
        assert c.get_defense() == 12

    def test_small_creature_low_defense_floors_at_one(self):
        """SMALL (defense_mod 0.75) with a rolled defense of 1 would
        truncate to 0 without the floor. Mirrors the get_dodge fix —
        floor applies when any torso functionality remains."""
        c = _make_creature(defense=1)
        c.size = Size.SMALL
        c.body_parts = BodyPart.humanoid()
        # int(1 * 1.0 * 0.75) = 0 without the floor; 1 with it.
        assert c.get_defense() == 1

    def test_destroyed_torso_returns_core_toughness(self):
        c = _make_creature(defense=10)
        c.size = Size.MEDIUM
        c.core_toughness = 0
        c.body_parts = BodyPart.humanoid()
        for p in c.body_parts:
            if _part_base_name(p) == "torso":
                p.health = 0
        assert c.get_defense() == 0

    def test_no_torso_returns_core_toughness(self):
        """A creature with parts but no torso falls back to core_toughness."""
        c = _make_creature(defense=10)
        c.size = Size.MEDIUM
        c.core_toughness = 3
        c.body_parts = [
            BodyPart.make("head", name="head"),
            BodyPart.make("leg", name="leg.left"),
        ]
        assert c.get_defense() == 3

    def test_injured_torso_reduces_defense(self):
        c = _make_creature(defense=10)
        c.size = Size.MEDIUM
        c.body_parts = BodyPart.humanoid()
        torsos = [p for p in c.body_parts if _part_base_name(p) == "torso"]
        # Pin health_max to avoid integer-truncation flakiness with low dice rolls
        torsos[0].health_max = 100
        torsos[0].health = 100
        _injure_to(torsos[0], InjuryLevels.MODERATE)
        # ratio = 0.5, size 1.0 → int(10 * 0.5 * 1.0) + 0 = 5
        assert c.get_defense() == 5


# ---------------------------------------------------------------------------
# Part HP scaling
# ---------------------------------------------------------------------------


class TestPartHpScaling:
    """Q.6 body-HP-relative scaling. Critical parts:
    ``body_hp × size_scalar × def_scalar`` floored at ``body_hp × 0.5``.
    Non-critical parts: ``body_hp × part_fraction × size_scalar``.

    Unpaired parts (head, torso) isolate the scaling math from the
    pair-symmetrization step. See ``TestPairSymmetrization`` below
    for the symmetrization contract."""

    def _unpaired_parts(self):
        return [
            BodyPart.make("head", name="head"),
            BodyPart.make("torso", name="torso"),
        ]

    def test_medium_creature_scales_criticals_from_body_hp(self):
        """MEDIUM (0.8) × def-10-neutral (1.0) × body 50 = 40; floor
        ``body × 0.5 = 25`` doesn't activate. Applies equally to head
        and torso (both critical)."""
        c = _make_creature()  # defense=10, body 50
        c.size = Size.MEDIUM
        c.body_parts = self._unpaired_parts()
        c._scale_part_hp()
        for p in c.body_parts:
            assert p.health_max == 40
            assert p.health == p.health_max

    def test_large_creature_scales_criticals_to_body_hp(self):
        """LARGE (1.0) × def-10 (1.0) × body 50 = 50 — critical parts
        match body HP on LARGE neutral-defense creatures."""
        c = _make_creature()  # defense=10
        c.size = Size.LARGE
        c.body_parts = self._unpaired_parts()
        c._scale_part_hp()
        for p in c.body_parts:
            assert p.health_max == 50
            assert p.health == p.health_max

    def test_huge_creature_scales_criticals_above_body_hp(self):
        """HUGE (1.3) × def-10 (1.0) × body 50 = 65."""
        c = _make_creature()  # defense=10
        c.size = Size.HUGE
        c.body_parts = self._unpaired_parts()
        c._scale_part_hp()
        for p in c.body_parts:
            assert p.health_max == 65
            assert p.health == p.health_max

    def test_light_armor_critical_hp_bump(self):
        """defense<10 lands in the 1.5 band: MEDIUM (0.8) × 1.5 × 50 = 60."""
        c = _make_creature(defense=5)
        c.size = Size.MEDIUM
        c.body_parts = self._unpaired_parts()
        c._scale_part_hp()
        for p in c.body_parts:
            assert p.health_max == 60

    def test_heavy_armor_critical_hp_reduced_to_half_floor(self):
        """defense>=20 lands in the 0.7 band: MEDIUM (0.8) × 0.7 × 50 =
        28, but the ``body_hp × 0.5 = 25`` floor keeps it above the raw.
        Here raw 28 > floor 25 → 28."""
        c = _make_creature(defense=20)
        c.size = Size.MEDIUM
        c.body_parts = self._unpaired_parts()
        c._scale_part_hp()
        for p in c.body_parts:
            assert p.health_max == 28

    def test_critical_floor_activates_when_raw_underflows(self):
        """The floor ``body_hp × 0.5`` wins when raw
        ``body × size × def_scalar`` falls below it.

        Setup: defense=30 × TINY defense_mod 0.5 = ``get_defense()=15``
        (still in the 10-20 neutral band → def_scalar 1.0). TINY size
        (0.4) × 1.0 × body 50 = 20 raw, floor = 25. Floor wins."""
        c = _make_creature(defense=30)
        c.size = Size.TINY
        c.body_parts = self._unpaired_parts()
        c._scale_part_hp()
        for p in c.body_parts:
            assert p.health_max == 25

    def test_non_critical_scales_by_part_fraction(self):
        """Arm (fraction 0.20) on MEDIUM (0.8) × body 50 = 8."""
        c = _make_creature()  # defense=10
        c.size = Size.MEDIUM
        left = BodyPart.make("arm", name="arm.left")
        c.body_parts = [left]
        c._scale_part_hp()
        # 50 * 0.20 * 0.8 = 8.0
        assert left.health_max == 8

    def test_non_critical_leg_has_higher_fraction_than_arm(self):
        """Leg fraction (0.25) > arm fraction (0.20) so legs outscale
        arms at the same size/body-hp."""
        c = _make_creature()
        c.size = Size.LARGE
        leg = BodyPart.make("leg", name="leg")
        arm = BodyPart.make("arm", name="arm")
        c.body_parts = [leg, arm]
        c._scale_part_hp()
        assert leg.health_max > arm.health_max

    def test_non_critical_eye_is_fragile(self):
        """Eye fraction 0.05 yields a tiny HP pool even on LARGE."""
        c = _make_creature()
        c.size = Size.LARGE
        eye = BodyPart.make("eye", name="eye")
        c.body_parts = [eye]
        c._scale_part_hp()
        # 50 * 0.05 * 1.0 = 2.5 → 2
        assert eye.health_max == 2

    def test_minimum_one_hp(self):
        """Even with tiny scaling, HP never drops below 1."""
        c = _make_creature(health_max=2)
        c.size = Size.TINY
        c.body_parts = [BodyPart.make("toe", name="toe")]
        c._scale_part_hp()
        assert c.body_parts[0].health_max >= 1

    def test_colossal_with_huge_body_hp(self):
        """COLOSSAL emergence: defense=10 × defense_mod 2.0 =
        ``get_defense()=20``, def_scalar=0.7. COLOSSAL size (1.6) × 0.7
        × body 200 = 224 on a critical. Floor (100) doesn't bind."""
        c = _make_creature(health_max=200)  # defense=10
        c.size = Size.COLOSSAL
        c.body_parts = [BodyPart.make("torso", name="torso")]
        c._scale_part_hp()
        assert c.body_parts[0].health_max == 224


class TestPairSymmetrization:
    """``_scale_part_hp`` (and the standalone ``_symmetrize_paired_parts``
    hook) should sync ``<base>.left`` / ``<base>.right`` pairs to the
    larger of their two rolled values so a freshly-built creature
    doesn't have conspicuously mismatched left and right sides."""

    def test_left_right_pair_synced_to_pair_max(self):
        c = _make_creature()
        c.size = Size.MEDIUM
        left = BodyPart.make("arm", name="arm.left")
        right = BodyPart.make("arm", name="arm.right")
        left.health_max = 5
        left.health = 5
        right.health_max = 9
        right.health = 9
        c.body_parts = [left, right]

        c._symmetrize_paired_parts()

        # Both should be at the max of the pair (9).
        assert left.health_max == 9
        assert right.health_max == 9
        assert left.health == 9
        assert right.health == 9

    def test_unpaired_parts_untouched(self):
        c = _make_creature()
        head = BodyPart.make("head", name="head")
        head.health_max = 12
        head.health = 12
        c.body_parts = [head]
        c._symmetrize_paired_parts()
        assert head.health_max == 12

    def test_numbered_parts_are_not_paired(self):
        """``head.1`` / ``head.2`` (numbered heads on a hydra) are
        NOT symmetrized — only ``.left`` / ``.right`` siblings."""
        c = _make_creature()
        h1 = BodyPart.make("head", name="head.1")
        h2 = BodyPart.make("head", name="head.2")
        h1.health_max = 10
        h1.health = 10
        h2.health_max = 25
        h2.health = 25
        c.body_parts = [h1, h2]
        c._symmetrize_paired_parts()
        assert h1.health_max == 10
        assert h2.health_max == 25

    def test_scale_and_symmetrize_compose(self):
        """Q.6 scaling writes deterministic per-part HP (body-HP × part
        fraction × size scalar), so pair left/right collapse to the
        same value without symmetrization needing to pick a max.
        LARGE (1.0) × leg fraction (0.25) × body 50 = 12.5 → 12."""
        c = _make_creature()  # body 50, def 10
        c.size = Size.LARGE
        left = BodyPart.make("leg", name="leg.left")
        right = BodyPart.make("leg", name="leg.right")
        c.body_parts = [left, right]

        c._scale_part_hp()

        assert left.health_max == 12
        assert right.health_max == 12


# ---------------------------------------------------------------------------
# HIT modifier
# ---------------------------------------------------------------------------


class TestHitModifier:
    def test_no_body_parts_returns_zero(self):
        c = _make_creature()
        assert c.get_hit_modifier() == 0

    def test_full_health_eyes_return_zero(self):
        c = _make_creature()
        c.body_parts = BodyPart.humanoid()
        # Humanoid has no eye parts, just head — head is fallback
        # With healthy head: ratio = 1.0, (1.0 - 1.0) * 5 = 0
        assert c.get_hit_modifier() == 0

    def test_destroyed_eyes_give_negative_modifier(self):
        c = _make_creature()
        c.body_parts = [
            BodyPart.make("eye", name="eye.left"),
            BodyPart.make("eye", name="eye.right"),
        ]
        # Destroy both eyes
        for p in c.body_parts:
            p.health = 0
        # ratio = 0.0, (0.0 - 1.0) * 5 = -5
        assert c.get_hit_modifier() == -5

    def test_partially_injured_eyes(self):
        c = _make_creature()
        c.body_parts = [
            BodyPart.make("eye", name="eye.left"),
            BodyPart.make("eye", name="eye.right"),
        ]
        # Destroy one, keep other healthy → ratio = (1.0 + 0.0)/2 = 0.5
        c.body_parts[0].health = 0
        # (0.5 - 1.0) * 5 = -2.5 → int(-2.5) = -2
        assert c.get_hit_modifier() == -2

    def test_heads_used_as_fallback_when_no_eyes(self):
        c = _make_creature()
        c.body_parts = [BodyPart.make("head", name="head")]
        c.body_parts[0].health = 0  # destroyed head
        # ratio = 0.0, (0.0 - 1.0) * 5 = -5
        assert c.get_hit_modifier() == -5

    def test_no_eyes_or_heads_returns_zero(self):
        c = _make_creature()
        c.body_parts = [
            BodyPart.make("torso", name="torso"),
            BodyPart.make("leg", name="leg.left"),
        ]
        assert c.get_hit_modifier() == 0


# ---------------------------------------------------------------------------
# HIT wiring in resolve_attack
# ---------------------------------------------------------------------------


class TestHitWiring:
    def test_hit_modifier_applied_in_resolve_attack(self):
        """When attacker has injured eyes, their hit modifier is applied."""
        attacker = _make_creature(dodge=5)
        attacker.body_parts = [
            BodyPart.make("eye", name="eye.left"),
            BodyPart.make("eye", name="eye.right"),
        ]
        # Destroy both eyes for -5 hit modifier
        for p in attacker.body_parts:
            p.health = 0

        target = _make_creature(dodge=5, defense=5)
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        source = NaturalAttackSource(atk="1d4", dmg_type=None, label="test")
        atk_roll, dmg_roll = source.make_attack_rolls(attacker)
        original_bonus = atk_roll.skillBonus

        target.resolve_attack(attacker, source, atk_roll, dmg_roll)
        # The hit modifier should have been applied to skillBonus
        assert atk_roll.skillBonus == original_bonus + attacker.get_hit_modifier()

    def test_hit_modifier_affects_actual_outcome(self):
        """A HIT penalty large enough to drop below dodge must cause a miss.

        We construct a roll where natural_roll + skillBonus > dodge (would hit),
        but natural_roll + skillBonus + hit_mod < dodge (misses).
        """
        from unittest.mock import patch
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import AttackRoll

        attacker = _make_creature(dodge=5)
        attacker.body_parts = [
            BodyPart.make("eye", name="eye.left"),
            BodyPart.make("eye", name="eye.right"),
        ]
        # Destroy both eyes for -5 hit modifier
        for p in attacker.body_parts:
            p.health = 0
        assert attacker.get_hit_modifier() == -5

        # Target with dodge=10
        target = _make_creature(dodge=10, defense=0)

        source = NaturalAttackSource(atk="1d4", dmg_type=None, label="test")

        # Patch Dice so the d20 roll is 12 (natural roll).
        # skillBonus = 0, so result = 12. 12 >= 10 → would HIT.
        # After hit_mod -5: result = 7. 7 < 10 → MISS.
        from caldanai.lib.rpg.helpers.dice import Dice
        with patch.object(Dice, '__init__', lambda self, n, s: (
            setattr(self, 'rolls', (12,)) or
            setattr(self, 'sides', s) or
            setattr(self, 'value', 12)
        )):
            atk_roll = AttackRoll(skill_bonus=0)
            # Verify our setup: raw result 12 >= dodge 10 → would hit
            assert atk_roll.result == 12
            assert atk_roll.result >= 10

        dmg_roll = source.make_attack_rolls(attacker)[1]
        result = target.resolve_attack(attacker, source, atk_roll, dmg_roll)

        # After the -5 penalty, result should be 7 < dodge 10 → MISS
        assert atk_roll.result == 7
        assert result.combined.isMiss is True
        assert result.damage == 0


# ---------------------------------------------------------------------------
# Monster-specific sizes
# ---------------------------------------------------------------------------


class TestMonsterSizes:
    def test_sheep_is_small(self):
        from caldanai.lib.rpg.creatures.monsters.sheep import Sheep
        s = Sheep()
        assert s.size == Size.SMALL

    def test_goblin_is_small(self):
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        g = Goblin()
        assert g.size == Size.SMALL

    def test_toad_is_small_or_medium(self):
        from caldanai.lib.rpg.creatures.monsters.toad import Toad
        t = Toad()
        assert t.size in (Size.SMALL, Size.MEDIUM)

    def test_bandit_is_medium(self):
        from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
        b = Bandit()
        assert b.size == Size.MEDIUM

    def test_math_teacher_is_medium(self):
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        m = MathTeacher()
        assert m.size == Size.MEDIUM

    def test_math_teacher_has_core_agility(self):
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        m = MathTeacher()
        assert m.core_agility == 5

    def test_vampire_is_medium(self):
        from caldanai.lib.rpg.creatures.monsters.vampire import Vampire
        v = Vampire()
        assert v.size == Size.MEDIUM

    def test_doppelganger_is_medium(self):
        from caldanai.lib.rpg.creatures.monsters.doppelganger import Doppelganger
        d = Doppelganger()
        assert d.size == Size.MEDIUM

    def test_giant_size_in_age_variants(self):
        """Giants pick from SIZE_VARIANTS at spawn (age-variant scaling)."""
        from caldanai.lib.rpg.creatures.monsters.giant import Giant
        for _ in range(20):
            g = Giant()
            assert g.size in Giant.SIZE_VARIANTS

    def test_bearowl_is_large(self):
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        b = Bearowl()
        assert b.size == Size.LARGE

    def test_dragon_size_in_age_variants(self):
        """Dragons pick from SIZE_VARIANTS at spawn (young/mature/ancient)."""
        from caldanai.lib.rpg.creatures.monsters.dragon import Dragon
        for _ in range(20):
            d = Dragon()
            assert d.size in Dragon.SIZE_VARIANTS

    def test_hydra_size_in_age_variants(self):
        """Hydras pick from SIZE_VARIANTS at spawn (LARGE↔HUGE, no COLOSSAL)."""
        from caldanai.lib.rpg.creatures.monsters.hydra import Hydra
        for _ in range(20):
            h = Hydra()
            assert h.size in Hydra.SIZE_VARIANTS


# ---------------------------------------------------------------------------
# _part_base_name helper
# ---------------------------------------------------------------------------


class TestPartBaseName:
    def test_returns_leg_for_leg_plugin(self):
        part = BodyPart.make("leg", name="leg.left")
        assert _part_base_name(part) == "leg"

    def test_returns_head_for_head_plugin(self):
        part = BodyPart.make("head", name="head")
        assert _part_base_name(part) == "head"

    def test_returns_wing_for_wing_plugin(self):
        part = BodyPart.make("wing", name="wing.left")
        assert _part_base_name(part) == "wing"

    def test_returns_torso_for_torso_plugin(self):
        part = BodyPart.make("torso", name="torso")
        assert _part_base_name(part) == "torso"

    def test_returns_eye_for_eye_plugin(self):
        part = BodyPart.make("eye", name="eye.left")
        assert _part_base_name(part) == "eye"

    def test_returns_empty_for_plain_bodypart(self):
        """Plain BodyPart (no plugin class-level name) returns empty string."""
        part = BodyPart(name="mystery", health_max=10)
        assert _part_base_name(part) == ""
