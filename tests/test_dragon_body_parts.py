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
        assert len(d.body_parts) == 9

    def test_toe_variant_has_nine_parts(self):
        """Toe variant also has 9 parts -- no toe body part instances."""
        with _force_variant(True):
            d = Dragon()
        assert len(d.body_parts) == 9

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
        """While flying, get_dodge uses wings with HUGE size mod (no 62-toe penalty)."""
        with _force_variant(True):
            d = Dragon()
        assert "flying" in d.flags
        # HUGE dodge_mod=0.5, wings healthy → ratio 1.0
        expected = int(d.dodge * 1.0 * 0.5)
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
        with _force_variant(True):
            d = Dragon()
        assert "flying" in d.flags
        # Flying: uses wings, HUGE dodge_mod=0.5
        expected = int(d.dodge * 1.0 * 0.5)
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
        # Flying, HUGE dodge_mod=0.5
        expected = int(d.dodge * 1.0 * 0.5)
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
        """Toe variant while flying: get_dodge uses wings with HUGE mod."""
        with _force_variant(True):
            d = Dragon()
        expected = int(d.dodge * 1.0 * 0.5)
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
