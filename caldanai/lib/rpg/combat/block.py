"""Combat pipeline data types — per-attacker block + reaction entries.

The pipeline's stages (``pick_actions``, ``pick_targets``, ``resolve``,
``narrate_attempt``, ``render_table``, ``narrate_results``,
``summarize_damage``, ``narrate_target_death``, ``reactions``,
``narrate_attacker_death``) accumulate their outputs into a single
:class:`CombatBlock` per attacker per round. A pure-function renderer
composes blocks into the final Discord message — mechanical decisions
always upstream of narrative.

**Serializability invariant.** Every field on :class:`CombatBlock` and
everything it transitively references must round-trip through
``to_dict()`` to a JSON-compatible primitive (``dict`` / ``list`` /
``str`` / ``int`` / ``float`` / ``bool`` / ``None``). Actor refs are
replaced with a stable identity snapshot (name, pronouns, gender,
flags) so a future Claude-API-backed narrator (see
``memory/project_phase2_api_narration.md``) can consume a block
without the local ``Creature`` graph's circular pointers.

The inverse (``from_dict``) is not part of v1 — nothing needs to
rehydrate a serialized block today. Adding it later is straightforward
once a concrete consumer (replay-log debugger, offline narrator test
harness) exists.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union

if TYPE_CHECKING:
    from caldanai.lib.rpg.combat.attack_result import AttackResult
    from caldanai.lib.rpg.combat.attack_source import AttackSource
    from caldanai.lib.rpg.combat.resolution import MultiVictimResolutionResult
    from caldanai.lib.rpg.creatures import Creature
    from caldanai.lib.rpg.creatures.body_part import BodyPart


# Target shape used by :class:`Assignment`. Either a bare victim, or a
# ``(victim, part)`` tuple when the action coupled part selection with
# target selection (e.g. "the bite goes for the throat").
Target = Union["Creature", Tuple["Creature", "BodyPart"]]


class Anchor(Enum):
    """Reaction anchor — what sustains the reaction's fire conditions.

    See the "Reaction anchoring" table in ``combat-pipeline-refactor``.
    The default is :attr:`BODY` because passive-consequence reactions
    (thorns, spines, burn-on-touch) are the most common case.
    """

    BODY = "body"
    """Anchored to the reactor's physical body. Fires even when the
    reactor just died — the body still exists for the round. Example:
    thorns, spines."""

    DEATH = "death"
    """Triggered by the reactor's death itself. Fires exactly once,
    only when the reactor was just killed this block. Example:
    explode-on-death."""

    VICTIM = "victim"
    """Transplanted into the victim at contact time; reactor state is
    irrelevant afterward. Fires regardless of reactor state. Example:
    poison tick, bleed DoT."""

    REACTOR_LIFE = "reactor_life"
    """Sustained by the reactor's continued existence. Lapses when the
    reactor dies. Example: concentration-bound retaliation, mind-link
    debuff."""


def _actor_identity(actor: Optional[Any]) -> Optional[Dict[str, Any]]:
    """Snapshot a creature to a JSON-compatible identity dict.

    Used by the ``to_dict()`` paths to break ``Creature`` circular
    references (``Creature.body_parts`` → parts, parts would serialize
    back to the owner, etc.) while preserving the data a downstream
    renderer needs to name / pronoun / flag the actor.
    """
    if actor is None:
        return None
    name = getattr(actor, "name", "") or ""
    gender = getattr(actor, "gender", None)
    pronouns_raw = getattr(actor, "pronouns", {}) or {}
    # Pronouns is ``Dict[Pronouns, str]``; serialize via the enum's
    # ``.name`` (stable string) so the output is JSON-friendly.
    pronouns = {getattr(k, "name", str(k)): v for k, v in pronouns_raw.items()}
    flags_raw = getattr(actor, "flags", set()) or set()
    return {
        "name": name,
        "gender": gender,
        "pronouns": pronouns,
        "flags": sorted(flags_raw),
    }


def _target_to_dict(target: Optional[Target]) -> Optional[Dict[str, Any]]:
    if target is None:
        return None
    if isinstance(target, tuple):
        victim, part = target
        return {
            "victim": _actor_identity(victim),
            "part": getattr(part, "name", None) if part is not None else None,
        }
    return {"victim": _actor_identity(target), "part": None}


def _source_to_dict(source: Optional[Any]) -> Optional[Dict[str, Any]]:
    if source is None:
        return None
    dmg_type = getattr(source, "damage_type", None)
    reach = getattr(source, "reach", None)
    intended = getattr(source, "intended_target", None)
    return {
        "label": getattr(source, "label", "") or "",
        "skill": getattr(source, "skill", None),
        "damage_type": getattr(dmg_type, "name", None) if dmg_type is not None else None,
        "reach": getattr(reach, "name", None) if reach is not None else None,
        "intended_target": _actor_identity(intended),
    }


def _result_to_dict(result: Optional[Any]) -> Optional[Dict[str, Any]]:
    if result is None:
        return None
    combined = getattr(result, "combined", None)
    dmg_type = getattr(result, "dmg_type", None)
    part = getattr(result, "target_part", None)
    return {
        "source": _source_to_dict(getattr(result, "source", None)),
        "damage": getattr(result, "damage", 0),
        "multiplier": getattr(result, "multiplier", 1.0),
        "defense": getattr(result, "defense", 0),
        "dodge": getattr(result, "dodge", 0),
        "dmg_type": getattr(dmg_type, "name", None) if dmg_type is not None else None,
        "extra_text": getattr(result, "extra_text", "") or "",
        "auto_hit": bool(getattr(result, "auto_hit", False)),
        "target_part": getattr(part, "name", None) if part is not None else None,
        "victim": _actor_identity(getattr(result, "victim", None)),
        "is_miss": bool(getattr(combined, "isMiss", False)) if combined is not None else False,
        "is_critical": bool(getattr(combined, "isCritical", False)) if combined is not None else False,
        "is_fumble": bool(getattr(combined, "isFumble", False)) if combined is not None else False,
    }


@dataclass
class Assignment:
    """One ``(AttackSource, Target)`` pair produced by ``pick_targets``.

    Target follows the :data:`Target` alias — a bare :class:`Creature`
    when the part is picked at resolve time by exposure weighting, or a
    ``(Creature, BodyPart)`` tuple when the action coupled part
    selection with target selection.
    """

    source: "AttackSource"
    target: Target

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": _source_to_dict(self.source),
            "target": _target_to_dict(self.target),
        }


@dataclass
class ReactionEntry:
    """One out-of-turn effect produced by the ``reactions`` stage.

    Reactions mutate state in the live combat loop; the
    ``state_mutations`` field here is the *serialized record* of what
    the reaction did so a downstream renderer / replay consumer can
    reconstruct the effect without re-executing anything.
    """

    reactor: "Creature"
    anchor: Anchor = Anchor.BODY
    affected: List["Creature"] = field(default_factory=list)
    narrative: Optional[str] = None
    # Each mutation is a JSON-compatible dict. Shape is open — callers
    # describe "what happened" in whatever fields suit the effect
    # (e.g. ``{"kind": "thorns", "target": "Caels", "amount": 3}``).
    # No schema enforcement in v1.
    state_mutations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reactor": _actor_identity(self.reactor),
            "anchor": self.anchor.value,
            "affected": [_actor_identity(c) for c in self.affected],
            "narrative": self.narrative,
            "state_mutations": list(self.state_mutations),
        }


@dataclass
class CombatBlock:
    """Accumulator for one attacker's per-round stage output.

    Populated incrementally: earlier stages write fields, later stages
    read what's there. The renderer composes this into the final
    message shape (``AttackSequence.to_markdown`` is the closest
    reference — block-level composition is the same idea one layer up).
    """

    attacker: "Creature"
    actions: List["AttackSource"] = field(default_factory=list)
    assignments: List[Assignment] = field(default_factory=list)
    results: Optional["MultiVictimResolutionResult"] = None
    attempt_narrative: Optional[str] = None
    table: Optional[str] = None
    result_narratives: List[str] = field(default_factory=list)
    damage_summary: Optional[str] = None
    death_narratives: List[str] = field(default_factory=list)
    reactions: List[ReactionEntry] = field(default_factory=list)
    attacker_death_narrative: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attacker": _actor_identity(self.attacker),
            "actions": [_source_to_dict(a) for a in self.actions],
            "assignments": [a.to_dict() for a in self.assignments],
            "results": _multi_victim_to_dict(self.results),
            "attempt_narrative": self.attempt_narrative,
            "table": self.table,
            "result_narratives": list(self.result_narratives),
            "damage_summary": self.damage_summary,
            "death_narratives": list(self.death_narratives),
            "reactions": [r.to_dict() for r in self.reactions],
            "attacker_death_narrative": self.attacker_death_narrative,
        }


def _resolution_result_to_dict(rr: Optional[Any]) -> Optional[Dict[str, Any]]:
    if rr is None:
        return None
    return {
        "body_damage_total": getattr(rr, "body_damage_total", 0),
        "injury_feedback_lines": list(getattr(rr, "injury_feedback_lines", []) or []),
        "death_msg": getattr(rr, "death_msg", "") or "",
        "num_hits": getattr(rr, "num_hits", 0),
        "critical_part_kill": bool(getattr(rr, "critical_part_kill", False)),
    }


def _multi_victim_to_dict(mv: Optional[Any]) -> Optional[Dict[str, Any]]:
    if mv is None:
        return None
    per_victim_raw = getattr(mv, "per_victim", {}) or {}
    per_victim_serialized = []
    for victim, rr in per_victim_raw.items():
        per_victim_serialized.append(
            {
                "victim": _actor_identity(victim),
                "result": _resolution_result_to_dict(rr),
            }
        )
    return {
        "per_victim": per_victim_serialized,
        "all_results": [_result_to_dict(r) for r in (getattr(mv, "all_results", []) or [])],
        "any_critical_part_kill": bool(getattr(mv, "any_critical_part_kill", False)),
    }
