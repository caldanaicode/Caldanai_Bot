"""Tests for the pipeline stage methods on ``Creature``.

Covers both the Phase 1 defaults (empty-anatomy creatures, inherited
``get_action_budget``, single-target assignment) and the Phase 2 real
logic: part-driven ``pick_actions``, budget-weighted selection,
multi-victim ``resolve``, injury-feedback aggregation, damage-summary
suppression on critical-part kills, and death-flavor dispatch.

Nothing is wired into ``Game.do_combat`` yet — tests are the validation
until Phase 4+ flips the runtime surface.
"""

import random

import pytest

from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.combat.block import (
    Anchor,
    Assignment,
    CombatBlock,
    ReactionEntry,
)
from caldanai.lib.rpg.combat.resolution import (
    MultiVictimResolutionResult,
    ResolutionResult,
)
from caldanai.lib.rpg.creatures import Creature, round_robin_assignment
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach


def _make_creature(name="goblin", health=20):
    return Creature(
        name=name, atk="1d4", defense=2, dodge=5,
        health_max=20, health=health, pronouns="she, her, hers, her",
    )


def _make_victim_with_arm(name="caels"):
    """Creature with a single arm part so ``resolve`` can route per-part."""
    victim = Creature(
        name=name, atk="1d4", defense=0, dodge=0,
        health_max=40, health=40, pronouns="he, him, his, his",
    )
    arm = BodyPart.make("arm", name="arm.left")
    victim.body_parts = [arm]
    return victim


class _TestHead(BodyPartPlugin):
    """Fixture-only head subclass with populated DEFAULT_ACTIONS."""

    name = "head"
    health_max = 15
    is_critical = False
    DEFAULT_ACTIONS = {
        "bite": {
            "cost": 1,
            "weight": 1.0,
            "dice": "1d6",
            "dmg_type": DamageTypes.PIERCING,
            "reach": Reach.MELEE,
            "label": "test bite",
            "narrative": ["@1D bites @2 on the @2p_target."],
        },
    }


class _TestLeg(BodyPartPlugin):
    name = "leg"
    health_max = 12
    is_critical = False
    DEFAULT_ACTIONS = {
        "kick": {
            "cost": 1,
            "weight": 1.0,
            "dice": "1d4",
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.MELEE,
            "label": "test kick",
        },
        "stomp": {
            "cost": 2,
            "weight": 0.01,  # very unlikely vs kick at equal budget
            "dice": "2d4",
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.MELEE,
            "label": "test stomp",
        },
    }


def _populated_attacker(name="test_monster", budget=2):
    cls = type(
        "_Attacker", (Creature,),
        {"ACTION_BUDGET": budget},
    )
    attacker = cls(
        name=name, atk="1d4", defense=2, dodge=5,
        health_max=20, health=20, pronouns="she, her, hers, her",
    )
    attacker.body_parts = [_TestHead(name="head"), _TestLeg(name="leg.left")]
    return attacker


class TestActionBudget:
    def test_default_is_two(self):
        assert Creature.ACTION_BUDGET == 2

    def test_instance_sees_class_default(self):
        c = _make_creature()
        assert c.ACTION_BUDGET == 2
        assert c.get_action_budget() == 2

    def test_subclass_override_takes_effect(self):
        class Heavy(Creature):
            ACTION_BUDGET = 5

        h = Heavy(
            name="giant", atk="1d8", defense=5, dodge=3,
            health_max=50, health=50, pronouns="he, him, his, his",
        )
        assert h.ACTION_BUDGET == 5
        assert h.get_action_budget() == 5

    def test_get_action_budget_method_override_wins(self):
        class Dynamic(Creature):
            ACTION_BUDGET = 2

            def get_action_budget(self):
                return 7

        d = Dynamic(
            name="boss", atk="1d6", defense=3, dodge=3,
            health_max=30, health=30, pronouns="she, her, hers, her",
        )
        assert d.get_action_budget() == 7


class TestPickActions:
    def test_partless_creature_returns_single_source_by_default(self):
        c = _make_creature()
        actions = c.pick_actions()
        assert len(actions) == 1
        assert isinstance(actions[0], AttackSource)

    def test_empty_default_actions_falls_back_to_get_attack_sources(self):
        attacker = _make_creature()
        attacker.body_parts = [BodyPart.make("arm", name="arm.left")]
        actions = attacker.pick_actions()
        assert len(actions) == 1
        assert isinstance(actions[0], AttackSource)

    def test_walks_parts_and_builds_sources_from_default_actions(self):
        attacker = _populated_attacker(budget=2)
        random.seed(1)
        actions = attacker.pick_actions()
        assert 1 <= len(actions) <= 2
        for source in actions:
            assert isinstance(source, AttackSource)
            assert source.damage_type in (
                DamageTypes.PIERCING, DamageTypes.BLUDGEONING,
            )

    def test_skips_destroyed_parts(self):
        attacker = _populated_attacker(budget=2)
        attacker.body_parts[0].health = 0  # head destroyed
        random.seed(0)
        actions = attacker.pick_actions()
        # Only the leg remains active — its single source is kick or stomp.
        assert all(src.damage_type is DamageTypes.BLUDGEONING for src in actions)

    def test_respects_budget_cap(self):
        attacker = _populated_attacker(budget=1)
        random.seed(0)
        actions = attacker.pick_actions()
        # At budget=1, only one 1-cost action fits.
        assert len(actions) == 1

    def test_respects_action_repertoire(self):
        attacker = _populated_attacker(budget=2)
        attacker.ACTION_REPERTOIRE = {
            "head": {
                "bite": {"label": "OVERRIDDEN", "dice": "5d5"},
            },
        }
        for seed in range(5):
            random.seed(seed)
            actions = attacker.pick_actions()
            for src in actions:
                if src.damage_type is DamageTypes.PIERCING:
                    assert src.label == "OVERRIDDEN"


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
    def test_empty_assignments_returns_empty_multi_victim(self):
        c = _make_creature()
        out = c.resolve([])
        assert isinstance(out, MultiVictimResolutionResult)
        assert out.per_victim == {}
        assert out.all_results == []
        assert out.any_critical_part_kill is False

    def test_single_assignment_populates_per_victim_bucket(self):
        attacker = _populated_attacker(budget=2)
        victim = _make_victim_with_arm()
        random.seed(2)
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [victim])
        random.seed(2)
        out = attacker.resolve(assignments)
        assert victim in out.per_victim
        assert len(out.all_results) == len(assignments)
        for result in out.all_results:
            assert isinstance(result, AttackResult)
            assert result.victim is victim

    def test_multi_victim_buckets_independently(self):
        attacker = _populated_attacker(budget=2)
        victim_a = _make_victim_with_arm(name="caels")
        victim_b = _make_victim_with_arm(name="serena")
        random.seed(3)
        actions = attacker.pick_actions()
        # Force multi-victim via round-robin helper (what hydra uses).
        assignments = round_robin_assignment(actions, [victim_a, victim_b])
        random.seed(3)
        out = attacker.resolve(assignments)
        assert set(out.per_victim.keys()) <= {victim_a, victim_b}

    def test_aggregates_body_damage_totals_per_victim(self):
        """resolve must report ``body_damage_total`` / ``num_hits`` per
        victim so callers can do the post-defense body-HP write."""
        attacker = _populated_attacker(budget=2)
        victim = _make_victim_with_arm(name="caels")
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.SLASHING, label="test",
        )
        assignments = [Assignment(source=source, target=victim)]
        # Seed so the roll yields a landing hit.
        for seed in range(50):
            random.seed(seed)
            mv = attacker.resolve(assignments)
            resolution = mv.per_victim.get(victim)
            if resolution and resolution.num_hits > 0:
                assert resolution.body_damage_total > 0
                break
        else:
            pytest.fail("no seed produced a landing hit")


class TestResolveNoLongerAppliesBodyHP:
    """Phase 6a contract: ``Creature.resolve`` is pure part-routing +
    aggregation. Body-HP application is the caller's responsibility
    (``Game.do_combat``, ``MonsterPlugin.attack_random``,
    ``Hydra.attack_random``). This pins that contract so future
    regressions double-apply body HP instead of silently undoing the
    refactor."""

    def test_parted_victim_body_hp_unchanged_after_resolve(self):
        attacker = _populated_attacker(budget=2)
        victim = _make_victim_with_arm(name="caels")
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.SLASHING, label="test",
        )
        assignments = [Assignment(source=source, target=victim)]
        start_hp = victim.health
        for seed in range(50):
            random.seed(seed)
            mv = attacker.resolve(assignments)
            resolution = mv.per_victim.get(victim)
            if resolution and resolution.num_hits > 0:
                # Body HP must be untouched even on a landing hit — the
                # caller will apply ``max(num_hits, total - defense)``.
                assert victim.health == start_hp
                return
        pytest.fail("no seed produced a landing hit")

    def test_partless_victim_body_hp_unchanged_after_resolve(self):
        attacker = _make_creature(name="bandit")
        victim = Creature(
            name="spirit", atk="1d4", defense=0, dodge=0,
            health_max=30, health=30, pronouns="they, them, theirs, their",
        )
        assert victim.body_parts == []
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.SLASHING, label="test",
        )
        assignments = [Assignment(source=source, target=victim)]
        start_hp = victim.health
        for seed in range(50):
            random.seed(seed)
            mv = attacker.resolve(assignments)
            resolution = mv.per_victim.get(victim)
            if resolution and resolution.num_hits > 0:
                assert victim.health == start_hp
                return
        pytest.fail("no seed produced a landing hit")


class TestNarrateAttempt:
    def test_empty_assignments_returns_none(self):
        c = _make_creature()
        assert c.narrate_attempt([]) is None

    def test_empty_narrative_pools_returns_none(self):
        """Phase 2 default — no body-part pools populated yet."""
        attacker = _populated_attacker(budget=2)
        victim = _make_victim_with_arm()
        # Clear the test leg's narrative so only the head has one.
        attacker.body_parts[1].DEFAULT_ACTIONS = {}
        attacker.body_parts[0].DEFAULT_ACTIONS = {
            "bite": {
                "cost": 1, "weight": 1.0, "dice": "1d6",
                "dmg_type": DamageTypes.PIERCING, "reach": Reach.MELEE,
                "label": "test bite",  # no "narrative" key
            },
        }
        random.seed(5)
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [victim])
        assert attacker.narrate_attempt(assignments) is None

    def test_populated_pool_produces_parsed_output(self):
        attacker = _populated_attacker(budget=2)
        victim = _make_victim_with_arm(name="caels")
        random.seed(6)
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [victim])
        # Only the head has a narrative pool in the fixture; if no head
        # action was picked this round, retry with another seed.
        for seed in range(10):
            random.seed(seed)
            actions = attacker.pick_actions()
            assignments = attacker.pick_targets(actions, [victim])
            has_head = any(
                getattr(a.source, "_action_name", None) == "bite"
                for a in assignments
            )
            if has_head:
                break
        out = attacker.narrate_attempt(assignments)
        assert out is not None
        assert "caels" in out.lower()


class TestRenderTable:
    def test_empty_results_returns_empty_string(self):
        c = _make_creature()
        assert c.render_table(MultiVictimResolutionResult()) == ""

    def test_populated_results_produce_diff_block(self):
        attacker = _populated_attacker(budget=2)
        victim = _make_victim_with_arm()
        random.seed(7)
        actions = attacker.pick_actions()
        assignments = attacker.pick_targets(actions, [victim])
        random.seed(7)
        results = attacker.resolve(assignments)
        out = attacker.render_table(results)
        assert "```ansi" in out


class TestNarrateResults:
    def test_empty_returns_empty_list(self):
        c = _make_creature()
        assert c.narrate_results(MultiVictimResolutionResult()) == []

    def test_collects_injury_feedback_per_victim(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        per_victim = {
            victim: ResolutionResult(
                body_damage_total=3,
                injury_feedback_lines=["   Caels's arm battered."],
                num_hits=1,
            ),
        }
        mv = MultiVictimResolutionResult(per_victim=per_victim)
        assert attacker.narrate_results(mv) == ["   Caels's arm battered."]


class TestSummarizeDamage:
    def test_empty_returns_none(self):
        c = _make_creature()
        assert c.summarize_damage(MultiVictimResolutionResult(), []) is None

    def test_critical_part_kill_suppresses_summary(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        per_victim = {
            victim: ResolutionResult(
                body_damage_total=5, num_hits=1, critical_part_kill=True,
            ),
        }
        mv = MultiVictimResolutionResult(
            per_victim=per_victim, any_critical_part_kill=True,
        )
        assert attacker.summarize_damage(mv, [victim]) is None

    def test_single_victim_emits_total_line(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels", health=15)
        per_victim = {
            victim: ResolutionResult(
                body_damage_total=5, num_hits=1,
            ),
        }
        mv = MultiVictimResolutionResult(per_victim=per_victim)
        out = attacker.summarize_damage(mv, [victim])
        assert out is not None
        assert "Total damage done vs Health" in out
        assert "15" in out  # max health

    def test_multi_victim_emits_per_victim_lines(self):
        attacker = _make_creature(name="hydra")
        victim_a = _make_creature(name="caels", health=15)
        victim_b = _make_creature(name="serena", health=10)
        per_victim = {
            victim_a: ResolutionResult(body_damage_total=3, num_hits=1),
            victim_b: ResolutionResult(body_damage_total=2, num_hits=1),
        }
        mv = MultiVictimResolutionResult(per_victim=per_victim)
        out = attacker.summarize_damage(mv, [victim_a, victim_b])
        assert out is not None
        assert "caels" in out.lower()
        assert "serena" in out.lower()

    def test_health_snapshots_override_live_max(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels", health=12)
        # Pretend victim was at 40/100 at round start, took 5 damage.
        victim.health = 35
        per_victim = {
            victim: ResolutionResult(body_damage_total=5, num_hits=1),
        }
        mv = MultiVictimResolutionResult(per_victim=per_victim)
        out = attacker.summarize_damage(
            mv, [victim], health_snapshots={victim: 40}
        )
        assert out is not None
        assert "vs 40" in out
        assert "35 health remaining" in out

    def test_missing_snapshot_falls_back_to_health_max(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels", health=15)  # health_max=20
        per_victim = {
            victim: ResolutionResult(body_damage_total=5, num_hits=1),
        }
        mv = MultiVictimResolutionResult(per_victim=per_victim)
        out = attacker.summarize_damage(mv, [victim], health_snapshots={})
        assert out is not None
        assert "vs 20" in out


class TestNarrateTargetDeath:
    def test_no_dead_returns_none(self):
        c = _make_creature()
        assert c.narrate_target_death([]) is None

    def test_monster_uses_death_attribute(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels", health=0)
        victim.death = "@1 falls to the ground, unmoving."
        out = attacker.narrate_target_death([victim])
        assert out is not None
        assert "caels" in out.lower()
        assert "unmoving" in out

    def test_partless_victim_uses_generic_crumple(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels", health=0)
        out = attacker.narrate_target_death([victim])
        assert out is not None
        assert "crumples" in out.lower()

    def test_critical_part_death_msg_from_results_wins_over_death_attr(self):
        """When apply_sequence_to_target captured a death message (a
        critical-part kill), narrate_target_death should surface it in
        preference to the creature's generic ``death`` attribute."""
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels", health=0)
        victim.death = "@1 falls to the ground, unmoving."
        per_victim = {
            victim: ResolutionResult(
                body_damage_total=20,
                num_hits=1,
                death_msg="@1np head is utterly destroyed!",
                critical_part_kill=True,
            ),
        }
        mv = MultiVictimResolutionResult(
            per_victim=per_victim, any_critical_part_kill=True,
        )
        out = attacker.narrate_target_death([victim], mv)
        assert out is not None
        assert "utterly destroyed" in out
        assert "unmoving" not in out


class TestReactions:
    def test_default_returns_empty_list(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        out = attacker.reactions(attacker, [victim], MultiVictimResolutionResult())
        assert out == []


class TestNarrateAttackerDeath:
    def test_live_attacker_returns_none(self):
        attacker = _make_creature(name="bandit")
        assert attacker.narrate_attacker_death(attacker, []) is None

    def test_dead_attacker_without_reactions_returns_none(self):
        """Only fire when the attacker died DURING reactions — a
        pre-existing corpse shouldn't resurrect into a death beat."""
        attacker = _make_creature(name="bandit", health=0)
        attacker.death = "@1 topples."
        assert attacker.narrate_attacker_death(attacker, []) is None

    def test_dead_attacker_with_reactions_emits_beat(self):
        attacker = _make_creature(name="bandit", health=0)
        attacker.death = "@1 topples."
        reactor = _make_creature(name="cactus")
        out = attacker.narrate_attacker_death(
            attacker, [ReactionEntry(reactor=reactor)],
        )
        assert out is not None
        assert "topples" in out


class TestRoundRobinAssignment:
    def test_fewer_actions_than_combatants_still_spreads(self):
        attacker = _make_creature(name="hydra")
        victim_a = _make_creature(name="caels")
        victim_b = _make_creature(name="serena")
        actions = attacker.pick_actions()
        out = round_robin_assignment(actions, [victim_a, victim_b])
        assert len(out) == len(actions)

    def test_wraps_via_modulo(self):
        attacker = _populated_attacker(budget=2)
        victim_a = _make_victim_with_arm(name="caels")
        random.seed(10)
        actions = attacker.pick_actions()
        # Force more actions than combatants via a third fake action.
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        actions = actions + [
            NaturalAttackSource(
                atk="1d4", dmg_type=DamageTypes.SLASHING, label="extra",
            ),
        ]
        out = round_robin_assignment(actions, [victim_a])
        assert all(a.target is victim_a for a in out)

    def test_empty_inputs_return_empty(self):
        assert round_robin_assignment([], []) == []
        assert round_robin_assignment(
            [], [_make_creature()],
        ) == []


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
