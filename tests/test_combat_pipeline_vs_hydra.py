"""Post-Phase-4 parity tests — the ``Hydra`` plugin using the base
Creature pipeline.

Phase 4 wired hydra's per-variant repertoires into each head's
``DEFAULT_ACTIONS`` at spawn, overrode ``pick_targets`` with
round-robin distribution, and collapsed ``attack_random`` into a thin
driver over :class:`Creature`'s pipeline stages. The legacy helpers
(``_select_round_actions``, ``_assign_to_targets``, ``_build_narrative``,
``_NARRATIVE_TEMPLATES``) are gone — the tests below validate the
invariants those helpers used to pin, now expressed against the
pipeline.
"""

import random

import pytest

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.combat.block import Assignment
from caldanai.lib.rpg.creatures import round_robin_assignment
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.monsters.hydra import (
    Hydra,
    _ACTION_FORELEG_STOMP,
    _ACTION_HINDLEG_KICK,
    _ACTION_TAIL_SWIPE,
    _REPERTOIRE_GROTESQUE,
    _REPERTOIRE_SWAMP,
    _REPERTOIRE_HEXED,
    _REPERTOIRE_ELEMENTAL,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def hydra():
    """A fresh hydra with Phase-4 spawn-time wiring applied."""
    return Hydra()


# ---------------------------------------------------------------------------
# Phase-4 invariants
# ---------------------------------------------------------------------------


class TestDefaultActionsWiring:
    """Every attackable part carries instance-level ``DEFAULT_ACTIONS``
    pulled from the variant's repertoire pools."""

    def test_every_head_carries_variant_repertoire_keys(self, hydra):
        variant_keys = set(hydra._variant["head_repertoire"].keys())
        for part in hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                assert set(part.DEFAULT_ACTIONS.keys()) == variant_keys

    def test_every_leg_and_tail_carry_shared_actions(self, hydra):
        for part in hydra.body_parts:
            if isinstance(part, TailPlugin):
                assert set(part.DEFAULT_ACTIONS.keys()) == set(
                    _ACTION_TAIL_SWIPE.keys()
                )
            elif isinstance(part, LegPlugin):
                if part.name.startswith("foreleg"):
                    assert set(part.DEFAULT_ACTIONS.keys()) == set(
                        _ACTION_FORELEG_STOMP.keys()
                    )
                elif part.name.startswith("hindleg"):
                    assert set(part.DEFAULT_ACTIONS.keys()) == set(
                        _ACTION_HINDLEG_KICK.keys()
                    )

    def test_wiring_is_per_instance_not_class(self, hydra):
        """Hydra's spawn-time wiring sets instance-level
        ``DEFAULT_ACTIONS`` via ``__dict__`` — the class-level default
        on ``HeadPlugin`` is untouched (inspect ``__dict__`` directly
        since attribute access would see the instance override)."""
        for part in hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                assert "DEFAULT_ACTIONS" in part.__dict__
        # HeadPlugin's own class-dict should still hold ONLY its generic
        # bite/headbutt keys — no hydra-variant keys like "ram" / "breath".
        class_keys = set(HeadPlugin.DEFAULT_ACTIONS.keys())
        assert class_keys == {"bite", "headbutt"}

    def test_head_entries_carry_resolved_dmg_type(self, hydra):
        """Each head's bite should carry the variant's damage type
        resolution — the per-head element (with ``dmg_mod`` OR'd in
        for the grotesque variant)."""
        for part in hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                entry = part.DEFAULT_ACTIONS["bite"]
                assert entry["dmg_type"] is not None

    def test_head_entries_carry_narrative_pool(self, hydra):
        for part in hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                for entry in part.DEFAULT_ACTIONS.values():
                    pool = entry.get("narrative") or []
                    assert pool, "every wired action should carry a narrative"


class TestPickActionsUsesWiredRepertoire:
    """``Creature.pick_actions`` on hydra pulls from the wired
    ``DEFAULT_ACTIONS`` and respects the budget / destroyed-part
    invariants."""

    def test_selection_comes_from_wired_repertoire(self, hydra):
        random.seed(42)
        sources = hydra.pick_actions()
        for source in sources:
            part = getattr(source, "_part", None)
            action_name = getattr(source, "_action_name", None)
            assert part is not None
            assert action_name in part.DEFAULT_ACTIONS

    def test_total_cost_within_hydra_budget(self, hydra):
        random.seed(11)
        budget = hydra.get_action_budget()
        sources = hydra.pick_actions()
        total_cost = sum(
            getattr(s, "_action", {}).get("cost", 1) for s in sources
        )
        assert total_cost <= budget

    def test_budget_one_caps_selection(self, hydra):
        hydra.get_action_budget = lambda: 1
        random.seed(1)
        sources = hydra.pick_actions()
        assert len(sources) <= 1

    def test_destroyed_heads_drop_out(self, hydra):
        destroyed_name = None
        for part in hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                part.health = 0
                destroyed_name = part.name
                break
        random.seed(9)
        sources = hydra.pick_actions()
        assert not any(
            getattr(s, "_part").name == destroyed_name for s in sources
        )

    def test_breath_filtered_when_on_cooldown(self, hydra):
        """The ``is_available`` gate baked into breath entries at spawn
        filters them out while the per-head cooldown is non-zero."""
        for part in hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                hydra._breath_cooldown[part.name] = 3
        random.seed(13)
        for _ in range(100):
            sources = hydra.pick_actions()
            for source in sources:
                assert getattr(source, "_action_name", None) != "breath"


class TestPickTargetsRoundRobin:
    """``Hydra.pick_targets`` distributes actions round-robin."""

    def test_override_uses_round_robin(self, hydra):
        class _Dummy:
            def __init__(self, name):
                self.name = name

            def is_dead(self):
                return False

        combatants = [_Dummy("caels"), _Dummy("serena"), _Dummy("aldric")]
        bite = next(iter(hydra.body_parts[-1].DEFAULT_ACTIONS.values()))
        sources = [
            NaturalAttackSource(
                atk=bite["dice"], label=bite["label"], skill="natural",
            )
            for _ in range(3)
        ]
        random.seed(200)
        helper_out = round_robin_assignment(sources, combatants)
        random.seed(200)
        override_out = hydra.pick_targets(sources, combatants)
        helper_victims = [a.target.name for a in helper_out]
        override_victims = [a.target.name for a in override_out]
        assert helper_victims == override_victims

    def test_fewer_victims_than_actions_wraps(self, hydra):
        class _Dummy:
            def __init__(self, name):
                self.name = name

            def is_dead(self):
                return False

        random.seed(50)
        sources = hydra.pick_actions()
        assignments = hydra.pick_targets(sources, [_Dummy("solo")])
        assert all(a.target.name == "solo" for a in assignments)

    def test_empty_inputs_return_empty(self, hydra):
        assert hydra.pick_targets([], [object()]) == []
        source = NaturalAttackSource(atk="1d6", label="bite", skill="natural")
        assert hydra.pick_targets([source], []) == []


class TestNarrateAttemptUsesWiredPool:
    """Shape check: ``Creature.narrate_attempt`` produces a parsed
    paragraph when hydra's wired narrative pool is populated."""

    def test_produces_parsed_text(self, hydra):
        class _Dummy:
            name = "caels"
            uses_article = False
            plural_verbs = False

            def is_dead(self):
                return False

        random.seed(8)
        sources = hydra.pick_actions()
        assignments = [Assignment(source=s, target=_Dummy()) for s in sources]
        out = hydra.narrate_attempt(assignments)
        if sources:
            assert out is not None
            assert "caels" in out
        else:
            assert out is None


class TestPerVariantWiring:
    """Each variant wires its own head repertoire keys onto the spawned
    hydra's heads. Exercise all four variants by forcing the
    weighted-variant roll via ``VARIANTS`` override.
    """

    def _make_variant_hydra(self, variant_name: str) -> Hydra:
        import caldanai.lib.rpg.creatures.monsters.hydra as hydra_mod
        variant = next(
            v for v in hydra_mod.VARIANTS if v["name"] == variant_name
        )
        original = hydra_mod.VARIANTS
        hydra_mod.VARIANTS = [variant]
        try:
            return Hydra()
        finally:
            hydra_mod.VARIANTS = original

    def test_grotesque_wiring(self):
        h = self._make_variant_hydra("hydra")
        expected = set(_REPERTOIRE_GROTESQUE.keys())
        for part in h.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                assert set(part.DEFAULT_ACTIONS.keys()) == expected

    def test_swamp_wiring_includes_spit(self):
        h = self._make_variant_hydra("swamp hydra")
        for part in h.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                assert "spit" in part.DEFAULT_ACTIONS

    def test_hexed_wiring_includes_hex(self):
        h = self._make_variant_hydra("hexed hydra")
        for part in h.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                assert "hex" in part.DEFAULT_ACTIONS

    def test_elemental_wiring_includes_sweep(self):
        h = self._make_variant_hydra("elemental hydra")
        for part in h.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                assert "sweep" in part.DEFAULT_ACTIONS

    def test_regrown_head_inherits_variant_wiring(self):
        h = self._make_variant_hydra("hydra")
        expected = set(_REPERTOIRE_GROTESQUE.keys())
        live = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
        ]
        live[0].health = 0
        h.on_combat_round({})
        for part in h.body_parts:
            if (isinstance(part, HeadPlugin) and not part.is_critical
                    and not part.is_destroyed()):
                assert set(part.DEFAULT_ACTIONS.keys()) == expected


class TestHydraBudgetOverride:
    """``Hydra.get_action_budget`` mirrors the legacy
    ``_compute_budget`` formula and adapts as parts are destroyed."""

    def test_matches_legacy_formula_at_spawn(self, hydra):
        attackable = hydra._get_attackable_parts()
        assert hydra.get_action_budget() == hydra._compute_budget(attackable)

    def test_budget_floor_is_two_with_any_live_part(self):
        import caldanai.lib.rpg.creatures.monsters.hydra as hydra_mod
        original = hydra_mod.VARIANTS
        hydra_mod.VARIANTS = [
            next(v for v in original if v["name"] == "hydra"),
        ]
        try:
            h = Hydra()
        finally:
            hydra_mod.VARIANTS = original
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0
            elif isinstance(p, TailPlugin):
                p.health = 0
            elif isinstance(p, LegPlugin) and p.name != "foreleg.left":
                p.health = 0
        assert h.get_action_budget() == 2


class TestVariantRepertoireModuleExports:
    """The legacy ``_REPERTOIRE_*`` module-level dicts remain exported —
    hydra still references them via ``_variant["head_repertoire"]`` and
    external tools / render-flavor probes consume them."""

    def test_all_grotesque_actions_present(self):
        assert set(_REPERTOIRE_GROTESQUE.keys()) == {"bite", "ram", "breath"}

    def test_swamp_adds_spit(self):
        assert "spit" in _REPERTOIRE_SWAMP

    def test_hexed_adds_hex(self):
        assert "hex" in _REPERTOIRE_HEXED

    def test_elemental_adds_sweep(self):
        assert "sweep" in _REPERTOIRE_ELEMENTAL
