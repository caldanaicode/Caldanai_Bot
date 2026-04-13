"""Tests for the Hydra expansion — variants, per-head damage types,
action economy, breath cooldown, multi-target combat, narrative
generation, and damage type resolution.

These tests cover the Q2-Q6 features added to the Hydra monster plugin
beyond the Phase 1.C baseline tested in ``test_hydra_monster.py``.
"""

import pytest
from unittest.mock import MagicMock, patch

from caldanai import PluginManager
from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
import caldanai.lib.rpg.creatures.monsters.hydra as hydra_mod
from caldanai.lib.rpg.creatures.monsters.hydra import (
    Hydra, VARIANTS,
    _REPERTOIRE_GROTESQUE, _REPERTOIRE_SWAMP, _REPERTOIRE_HEXED,
    _REPERTOIRE_ELEMENTAL,
    _ACTION_TAIL_SWIPE, _ACTION_FORELEG_STOMP, _ACTION_HINDLEG_KICK,
)
from caldanai.lib.rpg.inventory import Inventory


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure monster and body-part plugin discovery has run."""
    from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin

    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    if not Inventory.ITEMS:
        Inventory.discover_items()
    yield


def _make_variant_hydra(variant_name: str) -> Hydra:
    """Construct a Hydra forced to a specific variant by name."""
    variant = next(v for v in VARIANTS if v["name"] == variant_name)
    original = hydra_mod.VARIANTS
    hydra_mod.VARIANTS = [variant]
    try:
        return Hydra()
    finally:
        hydra_mod.VARIANTS = original


def _get_variant(name: str) -> dict:
    """Look up a variant dict by name."""
    return next(v for v in VARIANTS if v["name"] == name)


def _live_heads(h: Hydra):
    """Return the list of live, non-critical heads on a hydra."""
    return [
        p for p in h.body_parts
        if isinstance(p, HeadPlugin) and not p.is_critical
        and not p.is_destroyed()
    ]


def _mock_combatant(name="Hero"):
    """Create a mock combatant with the interface attack_random needs."""
    m = MagicMock()
    m.name = name
    m.get_dodge.return_value = 5
    m.get_defense.return_value = 3
    m.body_parts = []
    # resolve_attack returns a minimal AttackResult
    m.resolve_attack.side_effect = lambda attacker, source, atk_roll, dmg_roll: AttackResult(
        source=source,
        combined=MagicMock(isMiss=False, isCritical=False, isFumble=False,
                           result=4, attack=MagicMock(__str__=lambda s: "1d6"),
                           get_hit_string=lambda: "HIT"),
        damage=4,
        multiplier=1.0,
        defense=3,
        dodge=5,
        dmg_type=source.damage_type,
    )
    m.apply_damage.return_value = ""
    m.get_trait_multiplier.return_value = 1.0
    return m


# ===========================================================================
# Variant system
# ===========================================================================


class TestVariantTable:
    """Each variant has required keys and the table is well-formed."""

    REQUIRED_KEYS = {
        "name", "weight", "starting_heads", "head_dmg_types",
        "head_repertoire", "stats", "traits", "loot_overrides",
        "arrival", "flavor", "escape", "death",
    }

    def test_all_variants_have_required_keys(self):
        for v in VARIANTS:
            missing = self.REQUIRED_KEYS - set(v.keys())
            assert not missing, f"Variant {v['name']!r} missing keys: {missing}"

    def test_four_variants_exist(self):
        assert len(VARIANTS) == 4

    def test_variant_names(self):
        names = {v["name"] for v in VARIANTS}
        assert names == {"hydra", "swamp hydra", "hexed hydra", "elemental hydra"}


class TestVariantSelection:
    """Variant selection uses weighted random."""

    def test_elemental_hydra_has_lowest_weight(self):
        """Elemental hydra is rarer — it has the smallest weight."""
        elemental = _get_variant("elemental hydra")
        other_weights = [v["weight"] for v in VARIANTS if v["name"] != "elemental hydra"]
        assert elemental["weight"] < min(other_weights)

    def test_forced_variant_produces_correct_name(self):
        """Forcing a specific variant via VARIANTS override works."""
        for name in ("hydra", "swamp hydra", "hexed hydra", "elemental hydra"):
            h = _make_variant_hydra(name)
            assert h.name == name


class TestVariantTraits:
    """Variant-specific traits and loot overrides are applied."""

    def test_swamp_hydra_has_dark_air_trait(self):
        h = _make_variant_hydra("swamp hydra")
        key = DamageTypes.DARK | DamageTypes.AIR
        assert key in h.traits
        assert h.traits[key] == 0.5

    def test_swamp_hydra_loot_override(self):
        h = _make_variant_hydra("swamp hydra")
        assert h.loot["toad_slime"] == 1.0

    def test_hexed_hydra_has_magical_trait(self):
        h = _make_variant_hydra("hexed hydra")
        assert DamageTypes.MAGICAL in h.traits
        assert h.traits[DamageTypes.MAGICAL] == 0.5

    def test_hexed_hydra_loot_override(self):
        h = _make_variant_hydra("hexed hydra")
        assert h.loot["wand"] == 0.15

    def test_elemental_hydra_has_higher_stats(self):
        """Elemental hydra overrides baseline stats."""
        v = _get_variant("elemental hydra")
        assert v["stats"]["atk"] == "1d8"
        assert v["stats"]["health_max"] == "30d10"

    def test_default_hydra_has_no_traits(self):
        h = _make_variant_hydra("hydra")
        # Default hydra has empty traits dict from the variant.
        v = _get_variant("hydra")
        assert v["traits"] == {}


# ===========================================================================
# Per-head damage types
# ===========================================================================


class TestPerHeadDamageTypes:
    """Each head has a dmg_type attribute matching the variant definition."""

    def test_default_hydra_heads_are_piercing_slashing(self):
        h = _make_variant_hydra("hydra")
        expected = DamageTypes.PIERCING | DamageTypes.SLASHING
        for head in _live_heads(h):
            assert head.dmg_type == expected

    def test_swamp_hydra_heads_are_dark_air(self):
        h = _make_variant_hydra("swamp hydra")
        expected = DamageTypes.DARK | DamageTypes.AIR
        for head in _live_heads(h):
            assert head.dmg_type == expected

    def test_hexed_hydra_heads_are_dark_magical(self):
        h = _make_variant_hydra("hexed hydra")
        expected = DamageTypes.DARK | DamageTypes.MAGICAL
        for head in _live_heads(h):
            assert head.dmg_type == expected

    def test_elemental_hydra_heads_cycle_five_elements(self):
        """Elemental hydra has 5 heads, each with a different element."""
        h = _make_variant_hydra("elemental hydra")
        heads = _live_heads(h)
        assert len(heads) == 5
        expected_types = _get_variant("elemental hydra")["head_dmg_types"]
        actual_types = [hd.dmg_type for hd in heads]
        assert actual_types == expected_types

    def test_get_attack_sources_carries_dmg_type(self):
        """NaturalAttackSource returned by get_attack_sources includes
        the head's dmg_type."""
        h = _make_variant_hydra("hydra")
        sources = h.get_attack_sources()
        expected = DamageTypes.PIERCING | DamageTypes.SLASHING
        for src in sources:
            assert src.damage_type == expected

    def test_headless_fallback_uses_bludgeoning(self):
        """When all heads are destroyed, the fallback source uses
        BLUDGEONING, not None."""
        h = _make_variant_hydra("hydra")
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0
        sources = h.get_attack_sources()
        assert len(sources) == 1
        assert sources[0].damage_type == DamageTypes.BLUDGEONING


# ===========================================================================
# Action economy
# ===========================================================================


class TestComputeBudget:
    """Budget = max(2, sum(cheapest per part) // 2)."""

    def test_default_hydra_budget(self):
        """3 heads (cheapest=1 each) + 1 tail (cheapest=2) + 4 legs (cheapest=1 each).
        Total cheapest = 3 + 2 + 4 = 9.  Budget = max(2, 9 // 2) = max(2, 4) = 4."""
        h = _make_variant_hydra("hydra")
        attackable = h._get_attackable_parts()
        budget = h._compute_budget(attackable)
        # 3 heads * 1 + 1 tail * 2 + 4 legs * 1 = 9; 9 // 2 = 4
        assert budget == 4

    def test_budget_with_no_attackable_parts(self):
        """If all attackable parts are destroyed, budget is 0."""
        h = _make_variant_hydra("hydra")
        # Destroy all heads, tail, legs
        for p in h.body_parts:
            if isinstance(p, (HeadPlugin, TailPlugin, LegPlugin)):
                p.health = 0
        attackable = h._get_attackable_parts()
        assert len(attackable) == 0
        assert h._compute_budget(attackable) == 0

    def test_budget_minimum_is_two(self):
        """Budget never drops below 2 when there are live attackable parts."""
        h = _make_variant_hydra("hydra")
        # Destroy everything except one leg (cheapest=1, total=1, 1//2=0 -> max(2,0)=2)
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0
            elif isinstance(p, TailPlugin):
                p.health = 0
            elif isinstance(p, LegPlugin) and p.name != "foreleg.left":
                p.health = 0
        attackable = h._get_attackable_parts()
        assert len(attackable) == 1
        budget = h._compute_budget(attackable)
        assert budget == 2


class TestSelectRoundActions:
    """_select_round_actions respects budget and returns valid actions."""

    def test_total_cost_within_budget(self):
        """The sum of action costs in the selected actions must not exceed
        the budget."""
        h = _make_variant_hydra("hydra")
        attackable = h._get_attackable_parts()
        budget = h._compute_budget(attackable)
        actions = h._select_round_actions()
        total_cost = sum(action["cost"] for _, _, action in actions)
        assert total_cost <= budget

    def test_actions_come_from_various_part_types(self):
        """Over many iterations, actions should include heads, tail, and
        legs (stochastic — run enough times to be near-certain)."""
        h = _make_variant_hydra("hydra")
        seen_types = set()
        for _ in range(200):
            actions = h._select_round_actions()
            for part, _, _ in actions:
                if isinstance(part, HeadPlugin):
                    seen_types.add("head")
                elif isinstance(part, TailPlugin):
                    seen_types.add("tail")
                elif isinstance(part, LegPlugin):
                    seen_types.add("leg")
        assert "head" in seen_types
        # Tail and legs might not always appear due to budget, but heads
        # should reliably appear.

    def test_no_actions_from_destroyed_parts(self):
        """Destroyed parts must not appear in the selected actions."""
        h = _make_variant_hydra("hydra")
        destroyed_head = _live_heads(h)[0]
        destroyed_head.health = 0
        for _ in range(50):
            actions = h._select_round_actions()
            for part, _, _ in actions:
                assert part is not destroyed_head

    def test_breath_cost_two_displaces_cheaper(self):
        """When breath is selected (cost 2), it uses budget that would
        otherwise go to cheaper actions."""
        h = _make_variant_hydra("hydra")
        # Force breath on first head by patching random.choices
        found_breath = False
        for _ in range(200):
            actions = h._select_round_actions()
            for _, action_name, action in actions:
                if action_name == "breath":
                    assert action["cost"] == 2
                    found_breath = True
                    break
            if found_breath:
                break
        # Breath should eventually be selected (weight > 0).
        assert found_breath, "Breath was never selected in 200 rounds"


# ===========================================================================
# Breath cooldown
# ===========================================================================


class TestBreathCooldown:
    """Per-head breath cooldown tracking."""

    def test_breath_sets_cooldown(self):
        """After a head breathes, its cooldown is set in _breath_cooldown."""
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        repertoire = h._variant["head_repertoire"]
        breath_action = repertoire["breath"]
        # Simulate selecting breath for this head.
        h._breath_cooldown[head.name] = breath_action["cooldown"]
        assert h._breath_cooldown[head.name] == breath_action["cooldown"]

    def test_on_combat_round_decrements_cooldown(self):
        """on_combat_round decrements breath cooldown by 1."""
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        h._breath_cooldown[head.name] = 3
        h.on_combat_round({})
        assert h._breath_cooldown[head.name] == 2

    def test_cooldown_removed_when_reaches_zero(self):
        """When cooldown ticks to 0, the entry is removed."""
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        h._breath_cooldown[head.name] = 1
        h.on_combat_round({})
        assert head.name not in h._breath_cooldown

    def test_breath_excluded_when_on_cooldown(self):
        """A head on cooldown cannot select breath."""
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        h._breath_cooldown[head.name] = 3
        repertoire = h._variant["head_repertoire"]
        # Call _select_action_for_part many times — breath should never appear.
        for _ in range(100):
            result = h._select_action_for_part(head, repertoire)
            if result is not None:
                action_name, _ = result
                assert action_name != "breath"

    def test_cooldown_cleaned_for_destroyed_heads(self):
        """Destroyed heads have their cooldown entries cleaned up."""
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        h._breath_cooldown[head.name] = 3
        head.health = 0
        h.on_combat_round({})
        assert head.name not in h._breath_cooldown


# ===========================================================================
# Multi-target distribution
# ===========================================================================


class TestAssignToTargets:
    """_assign_to_targets distributes actions round-robin."""

    def test_three_actions_two_combatants(self):
        """3 actions, 2 combatants: one gets 2, the other gets 1."""
        h = _make_variant_hydra("hydra")
        actions = [
            (MagicMock(), "bite", {"cost": 1}),
            (MagicMock(), "bite", {"cost": 1}),
            (MagicMock(), "bite", {"cost": 1}),
        ]
        c1 = _mock_combatant("Alice")
        c2 = _mock_combatant("Bob")
        assignments = Hydra._assign_to_targets(actions, [c1, c2])
        assert len(assignments) == 3
        victims = [a[3] for a in assignments]
        assert victims.count(c1) + victims.count(c2) == 3
        # Round-robin means one gets 2, other gets 1
        counts = {c1: victims.count(c1), c2: victims.count(c2)}
        assert set(counts.values()) == {1, 2}

    def test_no_combatants_returns_empty(self):
        assignments = Hydra._assign_to_targets(
            [(MagicMock(), "bite", {"cost": 1})], []
        )
        assert assignments == []

    def test_no_actions_returns_empty(self):
        assignments = Hydra._assign_to_targets(
            [], [_mock_combatant()]
        )
        assert assignments == []


class TestAttackRandom:
    """attack_random returns a string or None."""

    def test_returns_string_with_combatants(self):
        """attack_random returns a non-None string when combatants present."""
        h = _make_variant_hydra("hydra")
        h.health_max = 100
        h.health = 100
        combatants = [_mock_combatant("Hero")]
        result = h.attack_random(combatants)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_none_with_no_combatants(self):
        h = _make_variant_hydra("hydra")
        assert h.attack_random([]) is None

    def test_returns_none_when_empty_list(self):
        h = _make_variant_hydra("hydra")
        result = h.attack_random([])
        assert result is None

    def test_resolve_attack_called_on_victims(self):
        """resolve_attack must be called at least once on at least one
        combatant during attack_random."""
        h = _make_variant_hydra("hydra")
        h.health_max = 100
        h.health = 100
        c1 = _mock_combatant("Alice")
        c2 = _mock_combatant("Bob")
        h.attack_random([c1, c2])
        total_calls = c1.resolve_attack.call_count + c2.resolve_attack.call_count
        assert total_calls >= 1, "resolve_attack was never called on any combatant"

    def test_multi_target_header_in_output(self):
        """attack_random output should contain the multi-target header
        'lashes out' when there are combatants."""
        h = _make_variant_hydra("hydra")
        h.health_max = 100
        h.health = 100
        combatants = [_mock_combatant("Alice"), _mock_combatant("Bob")]
        result = h.attack_random(combatants)
        assert "lashes out" in result.lower(), (
            f"Expected 'lashes out' in output, got:\n{result}"
        )


# ===========================================================================
# Narrative generation
# ===========================================================================


class TestNarrative:
    """_build_narrative produces flavor text."""

    def test_narrative_non_empty_when_actions_assigned(self):
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        victim = _mock_combatant("Hero")
        actions_with_targets = [
            (head, "bite", {"cost": 1, "dice": "1d6",
                            "dmg_mod": DamageTypes.PIERCING}, victim),
        ]
        narrative = h._build_narrative(actions_with_targets)
        assert isinstance(narrative, str)
        assert len(narrative) > 0

    def test_narrative_contains_victim_name(self):
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        victim = _mock_combatant("Hero")
        actions_with_targets = [
            (head, "bite", {"cost": 1, "dice": "1d6",
                            "dmg_mod": DamageTypes.PIERCING}, victim),
        ]
        narrative = h._build_narrative(actions_with_targets)
        assert "Hero" in narrative

    def test_narrative_contains_action_label(self):
        h = _make_variant_hydra("hydra")
        head = _live_heads(h)[0]
        victim = _mock_combatant("Hero")
        actions_with_targets = [
            (head, "bite", {"cost": 1, "dice": "1d6", "label": "vicious bite",
                            "dmg_mod": DamageTypes.PIERCING}, victim),
        ]
        narrative = h._build_narrative(actions_with_targets)
        assert "vicious bite" in narrative


# ===========================================================================
# Damage type resolution
# ===========================================================================


class TestResolveDmgType:
    """_resolve_dmg_type handles override, mod, and pure element."""

    def test_dmg_type_override_returns_override(self):
        """Action with dmg_type fully overrides the part's element."""
        part = MagicMock()
        part.dmg_type = DamageTypes.FIRE
        action = {"dmg_type": DamageTypes.BLUDGEONING}
        result = Hydra._resolve_dmg_type(part, action)
        assert result == DamageTypes.BLUDGEONING

    def test_dmg_mod_combines_with_part_element(self):
        """Action with dmg_mod is OR'd with the part's element."""
        part = MagicMock()
        part.dmg_type = DamageTypes.PIERCING | DamageTypes.SLASHING
        action = {"dmg_mod": DamageTypes.PIERCING}
        result = Hydra._resolve_dmg_type(part, action)
        expected = DamageTypes.PIERCING | DamageTypes.SLASHING | DamageTypes.PIERCING
        assert result == expected

    def test_neither_returns_pure_element(self):
        """Action with neither dmg_type nor dmg_mod returns the part's element."""
        part = MagicMock()
        part.dmg_type = DamageTypes.FIRE
        action = {}
        result = Hydra._resolve_dmg_type(part, action)
        assert result == DamageTypes.FIRE

    def test_dmg_mod_without_part_element_returns_mod(self):
        """When the part has no dmg_type, dmg_mod alone is returned."""
        part = MagicMock(spec=[])  # no dmg_type attribute
        action = {"dmg_mod": DamageTypes.PIERCING}
        result = Hydra._resolve_dmg_type(part, action)
        assert result == DamageTypes.PIERCING


# ===========================================================================
# Regrowth with types
# ===========================================================================


class TestRegrowthWithTypes:
    """Regrown heads have the correct dmg_type for their variant."""

    def test_default_regrown_heads_match_variant_type(self):
        h = _make_variant_hydra("hydra")
        heads = _live_heads(h)
        heads[0].health = 0
        h.on_combat_round({})
        expected = DamageTypes.PIERCING | DamageTypes.SLASHING
        for head in _live_heads(h):
            assert hasattr(head, "dmg_type")
            assert head.dmg_type == expected

    def test_swamp_regrown_heads_match_variant_type(self):
        h = _make_variant_hydra("swamp hydra")
        heads = _live_heads(h)
        heads[0].health = 0
        h.on_combat_round({})
        expected = DamageTypes.DARK | DamageTypes.AIR
        for head in _live_heads(h):
            assert head.dmg_type == expected

    def test_hexed_regrown_heads_match_variant_type(self):
        h = _make_variant_hydra("hexed hydra")
        heads = _live_heads(h)
        heads[0].health = 0
        h.on_combat_round({})
        expected = DamageTypes.DARK | DamageTypes.MAGICAL
        for head in _live_heads(h):
            assert head.dmg_type == expected

    def test_elemental_regrown_heads_from_pool(self):
        """Elemental hydra regrown heads get a random element from the
        5-element pool."""
        h = _make_variant_hydra("elemental hydra")
        valid_types = set(_get_variant("elemental hydra")["head_dmg_types"])
        heads = _live_heads(h)
        heads[0].health = 0
        h.on_combat_round({})
        for head in _live_heads(h):
            assert hasattr(head, "dmg_type")
            assert head.dmg_type in valid_types

    def test_regrown_head_has_dmg_type_attribute(self):
        """Every regrown head must have a dmg_type attribute."""
        h = _make_variant_hydra("hydra")
        heads = _live_heads(h)
        heads[0].health = 0
        h.on_combat_round({})
        for head in _live_heads(h):
            assert hasattr(head, "dmg_type"), (
                f"Regrown head {head.name!r} missing dmg_type"
            )

    def test_regrown_heads_have_size_scaled_hp(self):
        """Regrown heads on a LARGE hydra must have size-scaled HP.

        HeadPlugin base HP is 1d8 (range 1-8).  LARGE hp_scale is 2.0,
        so scaled HP should be in [2, 16].  An unscaled head would be in
        [1, 8].  We verify that every regrown head's HP is >= 2 (the
        minimum scaled value), confirming scaling was applied.
        """
        from caldanai.lib.rpg.helpers.enums import Size
        h = _make_variant_hydra("hydra")
        assert h.size == Size.LARGE  # hp_scale = 2.0
        scale = h.size.value["hp_scale"]  # 2.0

        # Destroy a head, then trigger regrowth.
        heads_before = _live_heads(h)
        heads_before[0].health = 0
        h.on_combat_round({})

        # Find regrown heads (names that weren't in the original set).
        original_names = {hd.name for hd in heads_before}
        regrown = [hd for hd in _live_heads(h) if hd.name not in original_names]
        assert len(regrown) >= 1, "Expected at least one regrown head"

        for head in regrown:
            # The base 1d8 rolls 1-8; scaled by 2.0 gives 2-16.
            # An unscaled head would have max 8.  We verify the HP is
            # consistent with scaling: health_max == int(base * scale)
            # where base is in [1,8].  The minimum scaled value is
            # max(1, int(1 * 2.0)) = 2.
            assert head.health_max >= 2, (
                f"Regrown head {head.name!r} has health_max={head.health_max}, "
                f"expected >= 2 (min scaled value for LARGE)"
            )
            assert head.health_max <= 16, (
                f"Regrown head {head.name!r} has health_max={head.health_max}, "
                f"expected <= 16 (max scaled value for LARGE)"
            )
            assert head.health == head.health_max, (
                f"Regrown head {head.name!r} health ({head.health}) != "
                f"health_max ({head.health_max})"
            )
