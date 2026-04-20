"""Tests for ``caldanai.lib.rpg.combat.block`` — pipeline data types.

Focus:

- Dataclass construction + field defaults.
- ``Anchor`` enum exposes the four anchor types from the design doc.
- ``to_dict()`` serialization round-trips every field to JSON-
  compatible primitives (no live ``Creature`` refs leaking through).
- Actor identity snapshot preserves name / gender / pronouns / flags.
"""

import json
from enum import Enum

from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.combat.attack_source import (
    AttackSource,
    NaturalAttackSource,
)
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
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach
from caldanai.lib.rpg.helpers.roll_data import (
    AttackRoll,
    CombinedRoll,
    DamageRoll,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_creature(name="goblin", **kwargs):
    defaults = dict(
        atk="1d4", defense=2, dodge=5, health_max=20, health=20,
        pronouns="she, her, hers, her",
    )
    defaults.update(kwargs)
    return Creature(name=name, **defaults)


class _Arm(BodyPart):
    def __init__(self):
        super().__init__(name="arm.left", health_max=10)


def _make_result(damage=5, victim=None, target_part=None, dmg_type=DamageTypes.SLASHING):
    atk = AttackRoll(skill_bonus=0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    combined = CombinedRoll(atk, dmg, dodge=5)
    source = NaturalAttackSource(atk="1d4", dmg_type=dmg_type, label="test")
    return AttackResult(
        source=source,
        combined=combined,
        damage=damage,
        multiplier=1.0,
        defense=0,
        dodge=5,
        dmg_type=dmg_type,
        target_part=target_part,
        victim=victim,
    )


def _assert_json_serializable(obj):
    """Round-trip through ``json`` to prove primitives only."""
    json.dumps(obj)


# ---------------------------------------------------------------------------
# Anchor enum
# ---------------------------------------------------------------------------


class TestAnchor:
    def test_four_anchor_types(self):
        assert Anchor.BODY.value == "body"
        assert Anchor.DEATH.value == "death"
        assert Anchor.VICTIM.value == "victim"
        assert Anchor.REACTOR_LIFE.value == "reactor_life"

    def test_is_enum(self):
        assert isinstance(Anchor.BODY, Enum)


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


class TestAssignment:
    def test_bare_creature_target(self):
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.SLASHING, label="swipe")
        a = Assignment(source=source, target=victim)
        assert a.source is source
        assert a.target is victim

    def test_tuple_target_with_part(self):
        victim = _make_creature(name="caels")
        arm = _Arm()
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.SLASHING, label="swipe")
        a = Assignment(source=source, target=(victim, arm))
        assert a.target == (victim, arm)

    def test_to_dict_bare(self):
        victim = _make_creature(name="caels")
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.SLASHING, label="swipe")
        out = Assignment(source=source, target=victim).to_dict()
        _assert_json_serializable(out)
        assert out["target"]["victim"]["name"] == "caels"
        assert out["target"]["part"] is None
        assert out["source"]["label"] == "swipe"

    def test_to_dict_tuple_records_part_name(self):
        victim = _make_creature(name="caels")
        arm = _Arm()
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.SLASHING, label="swipe")
        out = Assignment(source=source, target=(victim, arm)).to_dict()
        _assert_json_serializable(out)
        assert out["target"]["part"] == "arm.left"


# ---------------------------------------------------------------------------
# ReactionEntry
# ---------------------------------------------------------------------------


class TestReactionEntry:
    def test_defaults(self):
        reactor = _make_creature(name="cactus")
        r = ReactionEntry(reactor=reactor)
        assert r.anchor is Anchor.BODY
        assert r.affected == []
        assert r.narrative is None
        assert r.state_mutations == []

    def test_to_dict_round_trips(self):
        reactor = _make_creature(name="cactus")
        victim = _make_creature(name="caels")
        r = ReactionEntry(
            reactor=reactor,
            anchor=Anchor.DEATH,
            affected=[victim],
            narrative="The cactus bursts into spines.",
            state_mutations=[{"kind": "thorns", "target": "caels", "amount": 3}],
        )
        out = r.to_dict()
        _assert_json_serializable(out)
        assert out["anchor"] == "death"
        assert out["reactor"]["name"] == "cactus"
        assert out["affected"][0]["name"] == "caels"
        assert out["narrative"].startswith("The cactus")
        assert out["state_mutations"][0]["amount"] == 3

    def test_anchor_override(self):
        reactor = _make_creature(name="flame")
        r = ReactionEntry(reactor=reactor, anchor=Anchor.REACTOR_LIFE)
        assert r.anchor is Anchor.REACTOR_LIFE


# ---------------------------------------------------------------------------
# CombatBlock — construction + serialization round-trip
# ---------------------------------------------------------------------------


class TestCombatBlockBasics:
    def test_defaults(self):
        attacker = _make_creature(name="bandit")
        block = CombatBlock(attacker=attacker)
        assert block.actions == []
        assert block.assignments == []
        assert block.results is None
        assert block.attempt_narrative is None
        assert block.table is None
        assert block.result_narratives == []
        assert block.damage_summary is None
        assert block.death_narratives == []
        assert block.reactions == []
        assert block.attacker_death_narrative is None

    def test_to_dict_empty_block_is_json_serializable(self):
        attacker = _make_creature(name="bandit")
        out = CombatBlock(attacker=attacker).to_dict()
        _assert_json_serializable(out)
        assert out["attacker"]["name"] == "bandit"

    def test_to_dict_populated_block_is_json_serializable(self):
        attacker = _make_creature(name="hydra")
        victim_a = _make_creature(name="caels")
        victim_b = _make_creature(name="serena")
        arm = _Arm()
        source = NaturalAttackSource(
            atk="1d6", dmg_type=DamageTypes.PIERCING, label="head-1", reach=Reach.MELEE,
        )
        r_a = _make_result(damage=7, victim=victim_a, target_part=arm)
        r_b = _make_result(damage=3, victim=victim_b)
        per_victim = {
            victim_a: ResolutionResult(
                body_damage_total=7, injury_feedback_lines=["   Arm battered."],
                death_msg="", num_hits=1, critical_part_kill=False,
            ),
            victim_b: ResolutionResult(
                body_damage_total=3, injury_feedback_lines=[],
                death_msg="Serena crumples.", num_hits=1, critical_part_kill=True,
            ),
        }
        mv = MultiVictimResolutionResult(
            per_victim=per_victim,
            all_results=[r_a, r_b],
            any_critical_part_kill=True,
        )
        block = CombatBlock(
            attacker=attacker,
            actions=[source],
            assignments=[
                Assignment(source=source, target=victim_a),
                Assignment(source=source, target=(victim_b, arm)),
            ],
            results=mv,
            attempt_narrative="The hydra rears back.",
            table="```diff\nfake table\n```\n",
            result_narratives=["   Caels's arm battered."],
            damage_summary="Total damage done: 10 vs Health 20.",
            death_narratives=["Serena crumples lifelessly."],
            reactions=[
                ReactionEntry(
                    reactor=attacker,
                    anchor=Anchor.BODY,
                    affected=[victim_a],
                    narrative="Acid splatters back.",
                    state_mutations=[{"kind": "splash", "amount": 2}],
                ),
            ],
            attacker_death_narrative=None,
        )
        out = block.to_dict()
        _assert_json_serializable(out)
        assert out["attacker"]["name"] == "hydra"
        assert len(out["actions"]) == 1
        assert out["actions"][0]["label"] == "head-1"
        assert len(out["assignments"]) == 2
        assert out["assignments"][1]["target"]["part"] == "arm.left"
        assert out["results"]["any_critical_part_kill"] is True
        assert len(out["results"]["per_victim"]) == 2
        assert len(out["results"]["all_results"]) == 2
        assert out["results"]["all_results"][0]["damage"] == 7
        assert out["reactions"][0]["anchor"] == "body"
        assert out["death_narratives"] == ["Serena crumples lifelessly."]

    def test_actor_identity_carries_pronouns_and_flags(self):
        attacker = _make_creature(name="dragon")
        attacker.flags.add("flying")
        attacker.gender = "female"
        block = CombatBlock(attacker=attacker)
        out = block.to_dict()
        _assert_json_serializable(out)
        ident = out["attacker"]
        assert ident["name"] == "dragon"
        assert ident["gender"] == "female"
        assert "flying" in ident["flags"]
        assert ident["pronouns"]["SUBJECTIVE"] == "she"

    def test_actor_identity_does_not_leak_live_creature(self):
        """Serialized output must not contain ``Creature`` instances
        (guards against the circular-reference forward-compat hazard)."""
        attacker = _make_creature(name="bandit")
        victim = _make_creature(name="caels")
        source = NaturalAttackSource(atk="1d4", dmg_type=DamageTypes.SLASHING, label="jab")
        block = CombatBlock(
            attacker=attacker,
            assignments=[Assignment(source=source, target=victim)],
        )

        def _walk(o):
            if isinstance(o, dict):
                for v in o.values():
                    _walk(v)
            elif isinstance(o, list):
                for v in o:
                    _walk(v)
            else:
                assert not isinstance(o, Creature), f"Live Creature leaked: {o!r}"
                assert not isinstance(o, AttackResult), f"Live AttackResult leaked: {o!r}"
                assert not isinstance(o, AttackSource), f"Live AttackSource leaked: {o!r}"

        _walk(block.to_dict())
