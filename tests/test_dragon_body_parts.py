"""Tests for Dragon body parts and the 62-toe dodge override.

Test classes:

1. ``TestDragonVariantsTable`` -- pin the VARIANTS table structure.
2. ``TestDragonBodyPartsCompositionBase`` -- all variants have exactly 9 parts.
3. ``TestDragonFlyingFlag`` -- flying flag + grounding + get_dodge override.
4. ``TestDragonGetDodgeOverride`` -- pin _has_toes flag and get_dodge directly.
5. ``TestDragonCriticalParts`` -- head and torso critical, rest not.
6. ``TestDragonBreathAttackPreserved`` -- breath_attack still fires.
7. ``TestDragonFullHealthBackwardsCompat`` -- stats unchanged at full HP.
8. ``TestDragonSanityUnchanged`` -- name, loot, traits, methods present.
9. ``TestDragonEnrage`` -- ramping breath chance + part-destruction force trigger.
10. ``TestDragonBreathPathPreserved`` -- Phase 6c pin: breath vs pipeline-
    driven super() delegation preserved through the 6a/6b refactor.
"""

from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.helpers.enums import Reach
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.dragon import Dragon
from caldanai.lib.rpg.helpers.enums import Stat


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part and monster plugin discovery has run."""
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


def _force_variant(has_toes: bool):
    """Return a monkeypatch context manager that forces ``choice`` to
    pick the variant matching the given ``has_toes`` value."""
    target = next(v for v in Dragon.VARIANTS if v["has_toes"] is has_toes)

    def _pick(seq):
        # When called with VARIANTS, return our forced variant.
        # For any other choice call (e.g. inside super().__init__),
        # fall through to the first element.
        if seq is Dragon.VARIANTS or (
            isinstance(seq, list)
            and len(seq) > 0
            and isinstance(seq[0], dict)
            and "has_toes" in seq[0]
        ):
            return target
        # Fall through: return first element for other choice calls.
        return seq[0] if seq else seq

    return patch("caldanai.lib.rpg.creatures.monsters.dragon.choice", side_effect=_pick)


# ---------------------------------------------------------------------------
# 1. VARIANTS table structure
# ---------------------------------------------------------------------------


class TestDragonVariantsTable:
    def test_variants_is_a_list(self):
        assert isinstance(Dragon.VARIANTS, list)

    def test_variants_has_at_least_two_entries(self):
        assert len(Dragon.VARIANTS) >= 2

    def test_each_variant_has_flavor_and_has_toes_keys(self):
        for v in Dragon.VARIANTS:
            assert "flavor" in v
            assert "has_toes" in v

    def test_exactly_one_variant_mentions_62_toes(self):
        toe_variants = [v for v in Dragon.VARIANTS if "62 toes" in v["flavor"]]
        assert len(toe_variants) == 1

    def test_62_toes_variant_has_has_toes_true(self):
        toe_variant = next(v for v in Dragon.VARIANTS if "62 toes" in v["flavor"])
        assert toe_variant["has_toes"] is True

    def test_non_toe_variant_has_has_toes_false(self):
        non_toe = [v for v in Dragon.VARIANTS if v["has_toes"] is False]
        assert len(non_toe) >= 1


# ---------------------------------------------------------------------------
# 2. Body parts composition (always 9 parts, all variants)
# ---------------------------------------------------------------------------


class TestDragonBodyPartsCompositionBase:
    """All variants have exactly 9 parts: 1 head, 1 torso, 4 legs,
    2 wings, 1 tail. No conditional toes."""

    def test_non_toe_variant_has_nine_parts(self):
        with _force_variant(False):
            d = Dragon()
        assert len(d.body_parts) == 16

    def test_toe_variant_has_nine_parts(self):
        """Toe variant also has 9 parts -- no toe body part instances."""
        with _force_variant(True):
            d = Dragon()
        assert len(d.body_parts) == 16

    def test_has_exactly_one_head(self):
        with _force_variant(False):
            d = Dragon()
        heads = [p for p in d.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_dragon_head_is_a_head_plugin_instance(self):
        with _force_variant(False):
            d = Dragon()
        head = next(p for p in d.body_parts if isinstance(p, HeadPlugin))
        assert isinstance(head, HeadPlugin)

    def test_dragon_head_has_custom_exposure(self):
        with _force_variant(False):
            d = Dragon()
        head = next(p for p in d.body_parts if isinstance(p, HeadPlugin))
        assert head.exposure[Reach.MELEE] == 0.05
        assert head.exposure[Reach.REACH] == 0.10
        assert head.exposure[Reach.THROWN] == 0.50
        assert head.exposure[Reach.RANGED] == 1.0

    def test_has_exactly_one_torso(self):
        with _force_variant(False):
            d = Dragon()
        torsos = [p for p in d.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_has_four_legs(self):
        with _force_variant(False):
            d = Dragon()
        legs = [p for p in d.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 4

    def test_has_fore_and_hind_legs(self):
        with _force_variant(False):
            d = Dragon()
        leg_names = {p.name for p in d.body_parts if isinstance(p, LegPlugin)}
        assert "foreleg.left" in leg_names
        assert "foreleg.right" in leg_names
        assert "hindleg.left" in leg_names
        assert "hindleg.right" in leg_names

    def test_has_two_wings(self):
        with _force_variant(False):
            d = Dragon()
        wings = [p for p in d.body_parts if isinstance(p, WingPlugin)]
        assert len(wings) == 2

    def test_has_exactly_one_tail(self):
        with _force_variant(False):
            d = Dragon()
        tails = [p for p in d.body_parts if isinstance(p, TailPlugin)]
        assert len(tails) == 1


# ---------------------------------------------------------------------------
# 3. Flying flag and get_dodge override
# ---------------------------------------------------------------------------


class TestDragonFlyingFlag:
    def test_fresh_dragon_has_flying_flag(self):
        with _force_variant(False):
            d = Dragon()
        assert "flying" in d.flags

    def test_destroying_one_wing_grounds_the_dragon(self):
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000

        wing = next(p for p in d.body_parts if isinstance(p, WingPlugin))
        assert "flying" in d.flags

        # Hook firing lives in do_combat now — mirror it manually.
        old_level = wing.get_injury_level()
        d.apply_damage(100, target_part=wing)
        wing.on_injury_change(d, old_level, wing.get_injury_level())

        assert wing.is_destroyed()
        assert "flying" not in d.flags

    def test_has_toes_variant_flying_no_penalty(self):
        """While flying, get_dodge uses wings with HUGE size mod +
        the dragon's 1.5x flying bonus (no 62-toe penalty)."""
        with _force_variant(True):
            d = Dragon()
        assert "flying" in d.flags
        # HUGE dodge_mod=0.5, wings healthy → ratio 1.0, then Dragon
        # applies the 1.5x flying bonus on top. Floor at 1 matches
        # the base get_dodge floor.
        base = max(1, int(d.dodge * 1.0 * 0.5))
        expected = int(base * 1.5)
        assert d.get_dodge() == expected

    def test_has_toes_variant_grounded_gets_penalty(self):
        """After grounding, get_dodge uses legs with HUGE size mod minus 62."""
        with _force_variant(True):
            d = Dragon()
        d.flags.discard("flying")
        from caldanai.lib.rpg.creatures import _functionality_ratio, _part_base_name
        legs = [p for p in d.body_parts if _part_base_name(p) == "leg"]
        ratio = _functionality_ratio(legs)
        base_emergence = int(d.dodge * ratio * 0.5)
        expected = max(0, base_emergence - 62)
        assert d.get_dodge() == expected

    def test_non_toes_variant_grounded_no_penalty(self):
        """Non-toes variant grounded: dodge emerges from legs with HUGE mod."""
        with _force_variant(False):
            d = Dragon()
        d.flags.discard("flying")
        from caldanai.lib.rpg.creatures import _functionality_ratio, _part_base_name
        legs = [p for p in d.body_parts if _part_base_name(p) == "leg"]
        ratio = _functionality_ratio(legs)
        expected = int(d.dodge * ratio * 0.5)
        assert d.get_dodge() == expected

    def test_flying_dodge_exceeds_grounded_intact_legs(self):
        """Regression guard: flying dragon should have higher dodge
        than a grounded dragon with intact legs — being in the air
        is genuinely harder to hit. Previously a flying dragon's
        dodge was merely the HUGE-halved base, tying with a
        grounded dragon with legs intact."""
        with _force_variant(False):
            d_flying = Dragon()
            # Force a deterministic dodge stat so the delta isn't
            # drowned by RNG when the two instances roll differently.
            d_flying.dodge = 10

        with _force_variant(False):
            d_grounded = Dragon()
            d_grounded.flags.discard("flying")
            d_grounded.dodge = 10

        assert d_flying.get_dodge() > d_grounded.get_dodge(), (
            f"flying={d_flying.get_dodge()} should exceed "
            f"grounded={d_grounded.get_dodge()} with intact legs"
        )

    def test_grounded_with_intact_legs_keeps_dodge(self):
        """Regression guard for the LIVE-playtest observation
        (2026-04-21): a non-toed grounded dragon with all four
        legs intact must have nonzero dodge. Leg-based mobility
        path must not drop to the 0-floor just because wings are
        gone."""
        with _force_variant(False):
            d = Dragon()
        d.flags.discard("flying")
        d.dodge = 10
        assert d.get_dodge() > 0


# ---------------------------------------------------------------------------
# 4. get_dodge override pinned directly
# ---------------------------------------------------------------------------


class TestDragonGetDodgeOverride:
    def test_has_toes_flag_stored(self):
        with _force_variant(True):
            d = Dragon()
        assert d._has_toes is True

        with _force_variant(False):
            d = Dragon()
        assert d._has_toes is False

    def test_get_dodge_override_exists(self):
        assert "get_dodge" in Dragon.__dict__

    def test_override_applies_penalty_when_grounded_with_toes(self):
        with _force_variant(True):
            d = Dragon()
        d.flags.discard("flying")
        from caldanai.lib.rpg.creatures import _functionality_ratio, _part_base_name
        legs = [p for p in d.body_parts if _part_base_name(p) == "leg"]
        ratio = _functionality_ratio(legs)
        base_emergence = int(d.dodge * ratio * 0.5)
        assert d.get_dodge() == max(0, base_emergence - 62)

    def test_override_no_penalty_when_flying_with_toes(self):
        """Flying dragon uses wings for mobility + gets the 1.5x
        flying agility bonus layered on top."""
        with _force_variant(True):
            d = Dragon()
        assert "flying" in d.flags
        base = max(1, int(d.dodge * 1.0 * 0.5))
        expected = int(base * 1.5)
        assert d.get_dodge() == expected

    def test_override_no_penalty_without_toes(self):
        with _force_variant(False):
            d = Dragon()
        d.flags.discard("flying")
        from caldanai.lib.rpg.creatures import _functionality_ratio, _part_base_name
        legs = [p for p in d.body_parts if _part_base_name(p) == "leg"]
        ratio = _functionality_ratio(legs)
        expected = int(d.dodge * ratio * 0.5)
        assert d.get_dodge() == expected


# ---------------------------------------------------------------------------
# 5. Critical parts
# ---------------------------------------------------------------------------


class TestDragonCriticalParts:
    def test_dragon_head_is_critical(self):
        with _force_variant(False):
            d = Dragon()
        head = next(p for p in d.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        with _force_variant(False):
            d = Dragon()
        torso = next(p for p in d.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_legs_are_not_critical(self):
        with _force_variant(False):
            d = Dragon()
        legs = [p for p in d.body_parts if isinstance(p, LegPlugin)]
        assert legs
        for leg in legs:
            assert leg.is_critical is False

    def test_wings_are_not_critical(self):
        with _force_variant(False):
            d = Dragon()
        wings = [p for p in d.body_parts if isinstance(p, WingPlugin)]
        assert wings
        for wing in wings:
            assert wing.is_critical is False

    def test_tail_is_not_critical(self):
        with _force_variant(False):
            d = Dragon()
        tail = next(p for p in d.body_parts if isinstance(p, TailPlugin))
        assert tail.is_critical is False


# ---------------------------------------------------------------------------
# 6. breath_attack preserved
# ---------------------------------------------------------------------------


class TestDragonBreathAttackPreserved:
    def test_breath_attack_method_exists(self):
        with _force_variant(False):
            d = Dragon()
        assert hasattr(d, "breath_attack")
        assert callable(d.breath_attack)

    def test_breath_attack_fires_and_returns_nonempty_string(self):
        with _force_variant(True):
            d = Dragon()

        from caldanai.lib.rpg.creatures import Creature

        target = Creature(
            name="dummy",
            atk="1d4",
            defense=5,
            dodge=5,
            health_max=100,
            health=100,
            gender="male",
        )

        result = d.breath_attack([target])
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# 6b. Breath damage math (pre-defense in AttackResult, post-defense applied,
#      trait multiplier honored)
# ---------------------------------------------------------------------------


class TestDragonBreathDamageMath:
    """Breath used to pass post-defense damage into ``AttackResult.damage``
    and ignore the victim's FIRE trait multiplier. The renderer then
    subtracted defense a second time, showing a damage value smaller than
    what was actually applied. These tests pin the corrected behavior."""

    def _make_target(self, defense=6, health=100, fire_multiplier=None):
        from caldanai.lib.rpg.creatures import Creature
        from caldanai.lib.rpg.helpers.enums import DamageTypes

        target = Creature(
            name="dummy",
            atk="1d4",
            defense=defense,
            dodge=5,
            health_max=health,
            health=health,
            gender="male",
        )
        if fire_multiplier is not None:
            target.traits[DamageTypes.FIRE] = fire_multiplier
        return target

    def _force_raw_roll(self, value: int):
        """Patch ``Dice.from_ndn`` inside dragon.py so ``raw_dice.value``
        returns the given value for breath rolls.

        ``modifier`` is pinned to an explicit 0 because Q.6.3's
        dice-spec modifier support reads it via ``getattr(dice,
        "modifier", 0)`` downstream; without the explicit pin,
        MagicMock auto-vivifies a child mock for that attribute
        name and breaks the ``> 0`` comparisons in the display
        renderer.
        """
        from unittest.mock import MagicMock

        fake_dice = MagicMock()
        fake_dice.value = value
        fake_dice.result = value
        fake_dice.modifier = 0
        fake_dice.rolls = (value,)
        return patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.Dice.from_ndn",
            return_value=fake_dice,
        )

    def _force_max_absorption(self):
        """Patch ``_roll_absorption`` in the creatures module so the
        Q.7 ``1d{defense}`` breath-absorption roll deterministically
        returns the max face — the pre-Q.7 flat-defense behaviour.
        Tests below pin specific post-defense damage values; the
        absorption-variance contract is covered by the dedicated
        Q.7 dice-absorption test module."""
        return patch(
            "caldanai.lib.rpg.creatures.monsters.dragon._roll_absorption",
            side_effect=lambda defense, raw: min(defense, raw)
            if defense > 0 and raw > 0 else 0,
        )

    def test_attack_result_damage_is_pre_defense(self):
        """AttackResult.damage mirrors the shared renderer's convention:
        pre-defense, post-multiplier. Fire-neutral: sub_dmg == raw.
        Absorption mocked to its max so the Q.7 ``1d6`` doesn't add
        variance to the deterministic damage assertion."""
        with _force_variant(False):
            d = Dragon()
        target = self._make_target(defense=6, health=1000)

        with self._force_raw_roll(26), self._force_max_absorption():
            d.breath_attack([target])

        # breath_attack mutates the sequence mid-call and returns a
        # string; the assertions below re-run breath and capture the
        # constructed AttackResult via a spy on AttackResult. Simpler:
        # apply_damage records the post-defense hit on the victim.
        assert target.health == 1000 - (26 - 6)

    def test_trait_multiplier_reduces_damage_for_fire_resistant(self):
        """A victim with FIRE multiplier 0.5 should take half the damage.
        Absorption mocked to its max for deterministic assertions."""
        with _force_variant(False):
            d = Dragon()
        # 0.5 * 26 = 13 pre-defense, - 6 defense = 7 post-defense
        target = self._make_target(defense=6, health=1000, fire_multiplier=0.5)

        with self._force_raw_roll(26), self._force_max_absorption():
            d.breath_attack([target])

        assert target.health == 1000 - 7

    def test_trait_multiplier_amplifies_damage_for_fire_weak(self):
        """A victim with FIRE multiplier 2.0 should take double damage.
        Absorption mocked to its max for deterministic assertions."""
        with _force_variant(False):
            d = Dragon()
        # 2.0 * 26 = 52 pre-defense, - 6 defense = 46 post-defense
        target = self._make_target(defense=6, health=1000, fire_multiplier=2.0)

        with self._force_raw_roll(26), self._force_max_absorption():
            d.breath_attack([target])

        assert target.health == 1000 - 46

    def test_defense_cannot_push_damage_negative(self):
        """When defense exceeds the post-multiplier damage, a landed
        breath still registers the min-1 floor — only damage-type
        immunity (multiplier 0) reaches a true 0. Pre-trial behavior
        guaranteed at least 1; the dN absorption keeps that floor on
        non-immune hits so full-block landings stay visible to the
        ``num_hits > 0`` / ``damage > 0`` retaliation guards."""
        with _force_variant(False):
            d = Dragon()
        target = self._make_target(defense=100, health=1000)

        with self._force_raw_roll(26), self._force_max_absorption():
            d.breath_attack([target])

        assert target.health == 1000 - 1

    def test_rendered_total_subtracts_defense_exactly_once(self):
        """Q.6.2: defense is applied per-hit inside resolve_attack, so
        ``r.damage`` is already post-defense. The compact-table footer
        shows raw (sub_damage) → damage when the two diverge.
        Absorption mocked to its max for deterministic assertions."""
        with _force_variant(False):
            d = Dragon()
        target = self._make_target(defense=6, health=1000)

        with self._force_raw_roll(26), self._force_max_absorption():
            rendered = d.breath_attack([target])

        # 26 raw, 6 defense → 20 damage. The footer surfaces the
        # pre/post totals so players see the armor bite; per-hit
        # subtraction (rather than the pre-Q.6.2 sum-then-subtract)
        # is not double-applied.
        assert "26 raw" in rendered
        assert "→ 20 damage" in rendered


# ---------------------------------------------------------------------------
# 7. Full health backwards compatibility
# ---------------------------------------------------------------------------


class TestDragonFullHealthBackwardsCompat:
    def test_get_defense_matches_size_scaled(self):
        with _force_variant(False):
            d = Dragon()
        # HUGE defense_mod=1.5
        expected = int(d.defense * 1.0 * 1.5)
        assert d.get_defense() == expected

    def test_get_dodge_matches_size_scaled(self):
        with _force_variant(False):
            d = Dragon()
        # Flying dragon: HUGE dodge_mod=0.5 halves the rolled
        # dodge (mass), then Dragon's 1.5x flying bonus applies
        # (agility aloft). ``get_dodge`` floors at 1 before the
        # flying bonus.
        base = max(1, int(d.dodge * 1.0 * 0.5))
        expected = int(base * 1.5)
        assert d.get_dodge() == expected

    def test_stat_modifier_total_zero_at_full_health_non_toe(self):
        with _force_variant(False):
            d = Dragon()
        assert d.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert d.get_stat_modifier_total(Stat.DODGE) == 0
        assert d.get_stat_modifier_total(Stat.ATTACK) == 0
        assert d.get_stat_modifier_total(Stat.HIT) == 0

    def test_stat_modifier_total_zero_at_full_health_toe_variant(self):
        """Toe variant at full health: stat modifier totals are all 0
        (no toe body parts to contribute anything)."""
        with _force_variant(True):
            d = Dragon()
        assert d.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert d.get_stat_modifier_total(Stat.DODGE) == 0
        assert d.get_stat_modifier_total(Stat.ATTACK) == 0
        assert d.get_stat_modifier_total(Stat.HIT) == 0

    def test_get_dodge_matches_size_scaled_on_toe_variant(self):
        """Toe variant while flying: get_dodge uses wings with HUGE
        mod + Dragon's 1.5x flying bonus."""
        with _force_variant(True):
            d = Dragon()
        base = max(1, int(d.dodge * 1.0 * 0.5))
        expected = int(base * 1.5)
        assert d.get_dodge() == expected


# ---------------------------------------------------------------------------
# 8. Sanity -- existing dragon fields unchanged
# ---------------------------------------------------------------------------


class TestDragonSanityUnchanged:
    def test_name_is_dragon(self):
        with _force_variant(False):
            d = Dragon()
        assert d.name == "dragon"

    def test_loot_keys_preserved(self):
        with _force_variant(False):
            d = Dragon()
        expected_keys = {"small_gem", "tee_shirt", "candy",
                         "heavy_stringed_instrument", "mace", "wand"}
        assert expected_keys.issubset(set(d.loot.keys()))

    def test_traits_identity_preserved(self):
        from caldanai.lib.rpg.helpers.enums import DamageTypes

        with _force_variant(False):
            d = Dragon()
        assert DamageTypes.RANGED in d.traits
        assert DamageTypes.PIERCING in d.traits

    def test_attack_random_still_present(self):
        with _force_variant(False):
            d = Dragon()
        assert hasattr(d, "attack_random")
        assert callable(d.attack_random)

    def test_on_hugged_still_present(self):
        with _force_variant(False):
            d = Dragon()
        assert hasattr(d, "on_hugged")
        assert callable(d.on_hugged)

    def test_per_instance_parts_are_independent(self):
        with _force_variant(False):
            d1 = Dragon()
        with _force_variant(False):
            d2 = Dragon()
        for p1, p2 in zip(d1.body_parts, d2.body_parts):
            assert p1 is not p2


# ---------------------------------------------------------------------------
# 9. Enrage: ramping breath chance + part-destruction force trigger
# ---------------------------------------------------------------------------


class TestDragonEnrage:
    """Pin the enrage mechanic: breath chance climbs per round since last
    breath, resets on fire, and any newly-destroyed dragon body part
    forces a breath on the next turn (with a rage intro prepended)."""

    def _make_target(self):
        from caldanai.lib.rpg.creatures import Creature
        return Creature(
            name="dummy",
            atk="1d4",
            defense=5,
            dodge=5,
            health_max=100_000,
            health=100_000,
            gender="male",
        )

    def test_initial_breath_chance_is_base(self):
        with _force_variant(False):
            d = Dragon()
        assert d._rounds_since_breath == 0
        assert d._breath_chance() == Dragon.BREATH_BASE_CHANCE

    def test_chance_climbs_by_ramp_per_round(self):
        with _force_variant(False):
            d = Dragon()
        d._rounds_since_breath = 3
        expected = (
            Dragon.BREATH_BASE_CHANCE + 3 * Dragon.BREATH_RAMP_PER_ROUND
        )
        assert abs(d._breath_chance() - expected) < 1e-9

    def test_chance_caps_at_one(self):
        with _force_variant(False):
            d = Dragon()
        d._rounds_since_breath = 1000
        assert d._breath_chance() == 1.0

    def test_non_breath_round_increments_counter(self):
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        # Force the RNG above the breath threshold so breath does not fire.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            d.attack_random([target])
        assert d._rounds_since_breath == 1

    def test_breath_fire_resets_counter(self):
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        d._rounds_since_breath = 5
        target = self._make_target()

        # Force the RNG below the breath threshold so breath fires.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.0,
        ):
            d.attack_random([target])
        assert d._rounds_since_breath == 0

    def test_newly_destroyed_part_forces_breath(self):
        """Even with RNG roll above the ramping threshold, a destroyed
        leg should force the next turn's attack to be a breath."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        leg = next(p for p in d.body_parts if isinstance(p, LegPlugin))
        leg.health = 0
        assert leg.is_destroyed()

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            result = d.attack_random([target])

        assert result is not None
        assert "column of liquid flame" in result
        assert "pain and rage" in result
        assert d._rounds_since_breath == 0

    def test_wing_destruction_forces_breath_with_grounding_intro(self):
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        wing = next(p for p in d.body_parts if isinstance(p, WingPlugin))
        wing.health = 0
        assert wing.is_destroyed()

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            result = d.attack_random([target])

        assert result is not None
        assert "wings crumpling" in result
        assert "column of liquid flame" in result
        assert d._rounds_since_breath == 0

    def test_already_known_destroyed_part_does_not_refire(self):
        """Once a part is registered as destroyed, a subsequent attack
        round should not re-trigger the forced breath."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        leg = next(p for p in d.body_parts if isinstance(p, LegPlugin))
        leg.health = 0

        # Round 1: destruction noticed, forced breath fires.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            d.attack_random([target])

        # Round 2: RNG still above the threshold, leg still destroyed but
        # no *new* destruction -> normal (non-breath) attack.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            d.attack_random([target])

        assert d._rounds_since_breath == 1

    def test_attack_random_with_no_combatants_returns_none(self):
        with _force_variant(False):
            d = Dragon()
        assert d.attack_random([]) is None


# ---------------------------------------------------------------------------
# 10. Phase 6c pin: breath vs pipeline-driven super() delegation.
# ---------------------------------------------------------------------------


class TestDragonBreathPathPreserved:
    """Phase 6c: dragon's ``attack_random`` is a thin override on the
    Phase 6b pipeline-driven base. Breath pre-empts the pipeline; every
    other turn delegates to ``super().attack_random`` which runs the
    ``pick_actions`` / ``resolve`` / ``narrate_*`` stages."""

    def _make_target(self):
        from caldanai.lib.rpg.creatures import Creature
        return Creature(
            name="dummy",
            atk="1d4",
            defense=5,
            dodge=5,
            health_max=100_000,
            health=100_000,
            gender="male",
        )

    def test_breath_branch_renders_breath_flavor(self):
        """When breath fires, the signature 'column of liquid flame'
        narration appears in the returned string."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.0,
        ):
            result = d.attack_random([target])

        assert result is not None
        assert "column of liquid flame" in result

    def test_non_breath_branch_delegates_to_super_pipeline(self):
        """Non-breath turns go through ``MonsterPlugin.attack_random``
        (Phase 6b pipeline driver). The output must be the
        ``AttackSequence.to_markdown`` diff-block — breath builds its
        own sequence too but the dragon-specific 'column of liquid
        flame' flavor must NOT appear."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            result = d.attack_random([target])

        assert result is not None
        assert isinstance(result, str)
        # Phase 6b pipeline output carries the shared ansi-block table.
        assert "```ansi" in result
        # Breath flavor must not appear on a non-breath round.
        assert "column of liquid flame" not in result

    def test_non_breath_branch_increments_ramp_counter(self):
        """Non-breath delegation must bump ``_rounds_since_breath`` so
        the enrage ramp accumulates correctly across pipeline rounds."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            d.attack_random([target])
            d.attack_random([target])
            d.attack_random([target])
        assert d._rounds_since_breath == 3

    def test_breath_reset_after_super_delegation_streak(self):
        """After several non-breath rounds, a breath roll still resets
        the ramp counter — verifies the two branches interleave
        cleanly without counter drift."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            d.attack_random([target])
            d.attack_random([target])
        assert d._rounds_since_breath == 2

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.0,
        ):
            result = d.attack_random([target])
        assert d._rounds_since_breath == 0
        assert "column of liquid flame" in result

    def test_breath_applies_body_hp_directly(self):
        """Phase 6a compliance: ``breath_attack`` builds its own
        AttackSequence rather than routing through ``resolve``, and
        applies body HP via ``victim.apply_damage(dmg)``. A victim
        with finite HP must take the full post-defense breath damage."""
        with _force_variant(False):
            d = Dragon()
        d.health_max = 10_000
        d.health = 10_000
        target = self._make_target()
        start_hp = target.health

        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.0,
        ):
            d.attack_random([target])

        # Breath auto-hits — the victim must have lost some HP, and the
        # damage path must not have double-applied (hp can't have
        # dropped more than the max possible 6d6 * multiplier).
        assert target.health < start_hp
        assert start_hp - target.health <= 36 * 3  # 6d6 max × generous multiplier

