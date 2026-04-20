"""Differential parity tests — Creature pipeline vs. hydra's legacy
multi-target combat code.

Hydra's ``_REPERTOIRE_*`` dicts / ``_select_round_actions`` /
``_assign_to_targets`` are the reference implementation the Phase 2
pipeline is lifted from. These tests wire each head's
``DEFAULT_ACTIONS`` from the variant's repertoire at test scope,
then run both paths with a seeded RNG and assert structural parity.

Hydra itself is not modified — Phase 4 deletes the legacy methods
once the pipeline is the live path. Until then, the duplication is
deliberate and these tests pin the shape match.
"""

import random
from typing import Dict, List, Tuple

import pytest

from caldanai.lib.rpg.combat.attack_source import AttackSource, NaturalAttackSource
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
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _wire_hydra_parts(hydra: Hydra) -> None:
    """Copy the hydra's per-variant repertoires onto each part's
    ``DEFAULT_ACTIONS`` as instance attributes.

    Test-scope only — instance-attr overrides of the class default.
    The wiring is undone when the hydra is garbage-collected after
    the test."""
    head_rep = hydra._variant["head_repertoire"]
    for part in hydra.body_parts:
        if isinstance(part, HeadPlugin) and not part.is_critical:
            part.DEFAULT_ACTIONS = dict(head_rep)
        elif isinstance(part, TailPlugin):
            part.DEFAULT_ACTIONS = dict(_ACTION_TAIL_SWIPE)
        elif isinstance(part, LegPlugin):
            if part.name.startswith("foreleg"):
                part.DEFAULT_ACTIONS = dict(_ACTION_FORELEG_STOMP)
            elif part.name.startswith("hindleg"):
                part.DEFAULT_ACTIONS = dict(_ACTION_HINDLEG_KICK)


@pytest.fixture
def wired_hydra():
    """Hydra with each part's ``DEFAULT_ACTIONS`` populated from the
    variant's repertoire, and ``get_action_budget`` monkey-patched to
    return hydra's legacy ``_compute_budget`` result so selection
    parity tests aren't gated on the phase-4 budget override."""
    hydra = Hydra()
    _wire_hydra_parts(hydra)

    attackable = hydra._get_attackable_parts()
    legacy_budget = hydra._compute_budget(attackable)
    hydra.get_action_budget = lambda: legacy_budget
    return hydra


# ---------------------------------------------------------------------------
# Structural equivalence helpers
# ---------------------------------------------------------------------------


def _legacy_action_signature(triple: Tuple) -> Tuple:
    """Shape-normalize a legacy ``(part, action_name, action)`` triple
    for set comparison."""
    part, action_name, action = triple
    return (
        part.name,
        action_name,
        action.get("dice"),
        action.get("cost"),
    )


def _source_action_signature(source: AttackSource) -> Tuple:
    """Shape-normalize a new-path ``AttackSource`` for set comparison."""
    part = getattr(source, "_part", None)
    action = getattr(source, "_action", {}) or {}
    return (
        part.name if part is not None else None,
        getattr(source, "_action_name", None),
        action.get("dice"),
        action.get("cost"),
    )


# ---------------------------------------------------------------------------
# Parity tests
# ---------------------------------------------------------------------------


class TestPickActionsParity:
    """Legacy ``_select_round_actions`` vs. new ``pick_actions``.

    Both paths pull from the same repertoire pools and respect the
    same budget. Exact selection order / count can differ because
    the legacy path shuffles parts within priority tiers (heads →
    tail → legs) whereas the new path walks ``body_parts`` in
    insertion order — which is what the design explicitly allows
    ("Hydra doesn't change"). What we pin here:

    - Every source the new path returns carries a valid
      ``(part, action)`` pair from the wired repertoire.
    - Total cost of the selection respects the budget.
    - Destroyed parts drop out of the new-path pool the same way
      they drop out of the legacy pool."""

    def test_new_path_respects_wired_repertoire(self, wired_hydra):
        random.seed(42)
        new_sources = wired_hydra.pick_actions()

        # Every source must originate from a live body part whose
        # DEFAULT_ACTIONS was wired from the hydra's repertoire.
        for source in new_sources:
            part = getattr(source, "_part", None)
            action_name = getattr(source, "_action_name", None)
            assert part is not None
            assert action_name is not None
            assert action_name in part.DEFAULT_ACTIONS

    def test_selection_total_cost_within_budget(self, wired_hydra):
        budget = wired_hydra.get_action_budget()
        random.seed(11)
        new_sources = wired_hydra.pick_actions()
        total_cost = sum(
            getattr(s, "_action", {}).get("cost", 1) for s in new_sources
        )
        assert total_cost <= budget

    def test_selection_respects_budget_cap(self, wired_hydra):
        wired_hydra.get_action_budget = lambda: 1
        random.seed(1)
        new_sources = wired_hydra.pick_actions()
        assert len(new_sources) <= 1

    def test_destroyed_heads_drop_out(self, wired_hydra):
        destroyed_name = None
        for part in wired_hydra.body_parts:
            if isinstance(part, HeadPlugin) and not part.is_critical:
                part.health = 0
                destroyed_name = part.name
                break

        random.seed(9)
        legacy = wired_hydra._select_round_actions()
        random.seed(9)
        new_sources = wired_hydra.pick_actions()

        assert not any(t[0].name == destroyed_name for t in legacy)
        assert not any(
            getattr(s, "_part").name == destroyed_name for s in new_sources
        )


class TestPickTargetsParity:
    """Hydra's ``_assign_to_targets`` vs. ``round_robin_assignment``.

    Legacy returns ``(part, action_name, action, victim)`` quads; the
    new helper returns ``Assignment`` objects wrapping ``AttackSource``.
    We compare the victim distribution — which is what the contract
    pins."""

    def test_same_action_list_yields_same_round_robin_order(self, wired_hydra):
        """Feed both paths an identical action list to isolate the
        round-robin distribution logic from upstream selection."""

        class _Dummy:
            def __init__(self, name):
                self.name = name

            def is_dead(self):
                return False

        combatants = [_Dummy("caels"), _Dummy("serena"), _Dummy("aldric")]

        # Fabricate an identical action list for both paths: one
        # ``(part, action_name, action)`` triple per head (legacy shape)
        # and a matching ``AttackSource`` per triple (new shape).
        live_heads = [
            p for p in wired_hydra.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and not p.is_destroyed()
        ]
        bite_action = live_heads[0].DEFAULT_ACTIONS["bite"]
        triples = [(h, "bite", bite_action) for h in live_heads]
        sources = [
            NaturalAttackSource(
                atk=bite_action["dice"],
                label=bite_action["label"],
                skill="natural",
            )
            for _ in triples
        ]

        random.seed(200)
        legacy_quads = Hydra._assign_to_targets(triples, combatants)
        random.seed(200)
        new_assignments = round_robin_assignment(sources, combatants)

        legacy_victims = [q[3].name for q in legacy_quads]
        new_victims = [a.target.name for a in new_assignments]
        assert legacy_victims == new_victims

    def test_fewer_victims_than_actions_wraps(self, wired_hydra):
        class _Dummy:
            def __init__(self, name):
                self.name = name

            def is_dead(self):
                return False

        combatants = [_Dummy("solo")]
        random.seed(50)
        sources = wired_hydra.pick_actions()
        out = round_robin_assignment(sources, combatants)
        assert all(a.target.name == "solo" for a in out)

    def test_empty_inputs_match(self):
        assert Hydra._assign_to_targets([], [object()]) == []
        assert round_robin_assignment([], [object()]) == []


class TestNarrateAttemptParity:
    """Shape-level parity: both paths produce a parsed paragraph
    (non-empty string) when pools are populated, ``None`` / empty
    when they're not.

    Exact string equality is out of scope because the hydra's
    legacy templates are module-level and use positional format
    args that the new-path templates don't — the point of Phase 3
    is to grow richer per-part narrative pools, not clone the
    hydra's 9 templates verbatim."""

    def test_empty_pools_produce_no_new_narrative(self, wired_hydra):
        # Strip narrative fields so the new-path has nothing to pull.
        for part in wired_hydra.body_parts:
            for action_name, action in (
                getattr(part, "DEFAULT_ACTIONS", {}) or {}
            ).items():
                action.pop("narrative", None)
        random.seed(7)
        sources = wired_hydra.pick_actions()
        # Build assignments against a single dummy combatant.
        from caldanai.lib.rpg.combat.block import Assignment
        victim = wired_hydra  # any Creature works for shape check
        assignments = [Assignment(source=s, target=victim) for s in sources]
        assert wired_hydra.narrate_attempt(assignments) is None

    def test_populated_pool_produces_parsed_text(self, wired_hydra):
        for part in wired_hydra.body_parts:
            for action in (getattr(part, "DEFAULT_ACTIONS", {}) or {}).values():
                action["narrative"] = [
                    "@1D strikes at @2.",
                ]
        random.seed(8)
        sources = wired_hydra.pick_actions()
        from caldanai.lib.rpg.combat.block import Assignment

        class _Dummy:
            name = "caels"
            uses_article = False
            plural_verbs = False

            def is_dead(self):
                return False

        assignments = [Assignment(source=s, target=_Dummy()) for s in sources]
        out = wired_hydra.narrate_attempt(assignments)
        if sources:
            assert out is not None
            assert "caels" in out
        else:
            assert out is None
