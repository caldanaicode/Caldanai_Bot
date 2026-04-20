"""Tests for the Phase 1 pipeline stage methods on ``Creature``.

These stages are scaffolding — nothing wires them into ``Game.do_combat``
yet — so the tests just pin the documented defaults. Override-level
behavior lands in later phases and gets its own tests then.
"""

from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.combat.block import (
    Anchor,
    Assignment,
    CombatBlock,
    ReactionEntry,
)
from caldanai.lib.rpg.combat.resolution import MultiVictimResolutionResult
from caldanai.lib.rpg.creatures import Creature


def _make_creature(name="goblin", health=20):
    return Creature(
        name=name, atk="1d4", defense=2, dodge=5,
        health_max=20, health=health, pronouns="she, her, hers, her",
    )


class TestActionBudget:
    def test_default_is_two(self):
        assert Creature.ACTION_BUDGET == 2

    def test_instance_sees_class_default(self):
        c = _make_creature()
        assert c.ACTION_BUDGET == 2

    def test_subclass_override_takes_effect(self):
        class Heavy(Creature):
            ACTION_BUDGET = 5

        h = Heavy(
            name="giant", atk="1d8", defense=5, dodge=3,
            health_max=50, health=50, pronouns="he, him, his, his",
        )
        assert h.ACTION_BUDGET == 5


class TestPickActions:
    def test_returns_single_source_by_default(self):
        c = _make_creature()
        actions = c.pick_actions()
        assert len(actions) == 1
        assert isinstance(actions[0], AttackSource)


class TestPickTargets:
    def test_empty_actions_returns_empty(self):
        c = _make_creature()
        assert c.pick_targets([], [_make_creature(name="caels")]) == []

    def test_single_target_against_first_living_combatant(self):
        attacker = _make_creature(name="bandit")
        victim_a = _make_creature(name="caels")
        victim_b = _make_creature(name="serena")
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [victim_a, victim_b])
        assert len(assignments) == 1
        assert isinstance(assignments[0], Assignment)
        assert assignments[0].target is victim_a

    def test_skips_dead_combatants_for_default_target(self):
        attacker = _make_creature(name="bandit")
        dead_player = _make_creature(name="caels", health=0)
        alive_player = _make_creature(name="serena")
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [dead_player, alive_player])
        assert assignments[0].target is alive_player

    def test_honors_intended_target_on_source(self):
        attacker = _make_creature(name="bandit")
        preferred = _make_creature(name="caels")
        fallback = _make_creature(name="serena")
        actions = attacker.pick_actions()
        actions[0].intended_target = preferred
        assignments = attacker.pick_targets(actions, [fallback])
        assert assignments[0].target is preferred


class TestResolve:
    def test_returns_empty_multi_victim_result(self):
        c = _make_creature()
        out = c.resolve([])
        assert isinstance(out, MultiVictimResolutionResult)
        assert out.per_victim == {}
        assert out.all_results == []
        assert out.any_critical_part_kill is False


class TestNarrateAttempt:
    def test_default_returns_none(self):
        c = _make_creature()
        assert c.narrate_attempt([]) is None


class TestRenderTable:
    def test_default_returns_empty_string(self):
        c = _make_creature()
        assert c.render_table(MultiVictimResolutionResult()) == ""


class TestNarrateResults:
    def test_default_returns_empty_list(self):
        c = _make_creature()
        assert c.narrate_results(MultiVictimResolutionResult()) == []


class TestSummarizeDamage:
    def test_default_returns_none(self):
        c = _make_creature()
        assert c.summarize_damage(MultiVictimResolutionResult(), []) is None


class TestNarrateTargetDeath:
    def test_default_returns_none(self):
        c = _make_creature()
        assert c.narrate_target_death([]) is None


class TestReactions:
    def test_default_returns_empty_list(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        out = attacker.reactions(attacker, [victim], MultiVictimResolutionResult())
        assert out == []


class TestNarrateAttackerDeath:
    def test_default_returns_none(self):
        attacker = _make_creature(name="bandit")
        assert attacker.narrate_attacker_death(attacker, []) is None


class TestStageOutputsCompose:
    """Smoke test: the outputs of each default stage type-check as the
    fields ``CombatBlock`` expects. No mechanics, just shape."""

    def test_default_block_from_default_stages(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [victim])
        results = attacker.resolve(assignments)
        block = CombatBlock(
            attacker=attacker,
            actions=actions,
            assignments=assignments,
            results=results,
            attempt_narrative=attacker.narrate_attempt(assignments),
            table=attacker.render_table(results) or None,
            result_narratives=attacker.narrate_results(results),
            damage_summary=attacker.summarize_damage(results, [victim]),
            death_narratives=list(
                filter(None, [attacker.narrate_target_death([])]),
            ),
            reactions=attacker.reactions(attacker, [victim], results),
            attacker_death_narrative=attacker.narrate_attacker_death(attacker, []),
        )
        # to_dict() round-trips to JSON-compatible primitives.
        import json
        json.dumps(block.to_dict())


class TestReactionEntryAnchorSmoke:
    def test_anchor_default_is_body(self):
        reactor = _make_creature(name="cactus")
        entry = ReactionEntry(reactor=reactor)
        assert entry.anchor is Anchor.BODY
