"""Per-sequence damage resolution — the authoritative hook-firing path.

``apply_sequence_to_target`` owns the inner loop that was previously
duplicated across ``Game.do_combat`` (player -> monster),
``MonsterPlugin.attack_random`` (monster -> player), and
``Hydra.attack_random`` (custom multi-target). Each caller:

1. builds an :class:`AttackSequence` (with possibly multiple per-hit
   results that target specific body parts),
2. hands the sequence to this helper to route per-hit damage and fire
   the part-side hooks exactly once per part per sequence, and
3. applies the post-defense body HP with a ``max(num_hits, total -
   defense)`` floor — the floor is explicitly the caller's
   responsibility so ``do_combat`` can write ``monster.health -= ...``
   directly while ``attack_random`` can route through
   ``victim.apply_damage(final)`` to get the Player's "crumples to the
   ground" death transition.

Hook-firing invariants (pinned in ``tests/test_combat_resolution.py``):

- ``target.apply_damage(result.damage, dmg_type=..., target_part=...)``
  is invoked once per result with positive damage. ``apply_damage`` is
  a pure damage-application primitive — it does not fire part hooks.
  The helper below is responsible for the coalesced fire so multi-
  source sequences don't produce duplicate side effects (wing
  grounding, doppelganger pain cries, etc.).
- ``part.on_injury_change`` fires exactly once per unique hit part
  whose injury level changed across the sequence — the "old" level is
  snapshotted before any hit lands, so multi-source sequences don't
  double-fire ("lightly battered" then "utterly destroyed" for one
  attack action).
- ``part.on_destroyed`` fires exactly once per part that transitioned
  into USELESS. Parts already USELESS entering the sequence are not
  fired on.
- ``attacker.on_target_part_destroyed`` fires **only when an attacker
  is explicitly passed**. The player-attacks-monster path passes
  nothing and therefore skips this hook — by design.

Why a free function (not a Creature method): one consumer (Hydra)
wants to interleave hook-firing with narrative paragraphs mid-sequence.
Composition keeps the loop reusable without forcing the callers into a
fixed overall output shape.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from caldanai.lib.rpg.helpers.enums import InjuryLevels

if TYPE_CHECKING:
    from caldanai.lib.rpg.combat.attack_result import AttackSequence
    from caldanai.lib.rpg.creatures import Creature
    from caldanai.lib.rpg.creatures.body_part import BodyPart


@dataclass
class ResolutionResult:
    """Per-sequence resolution output.

    Fields:

    - ``body_damage_total``: sum of ``result.damage`` across hits with
      positive damage — the raw pre-defense total. Callers apply the
      ``max(num_hits, total - defense)`` floor on top of this.
    - ``injury_feedback_lines``: fully-formatted feedback lines in the
      order the helper emitted them (one per part transition, optionally
      followed by non-empty hook returns).  Each line already carries
      the ``"   "`` prefix used inside the combat diff block.
    - ``death_msg``: the first non-empty death message produced by a
      per-part ``target.apply_damage`` call (e.g. a critical part
      destroying the victim). Empty string when nothing killed the
      victim during part-routing. Callers may augment this with a
      body-HP-reached-zero message after applying the floor.
    - ``num_hits``: count of results with ``damage > 0``. The body-HP
      floor uses this as the "minimum 1 HP per hit" term.
    """

    body_damage_total: int
    injury_feedback_lines: List[str] = field(default_factory=list)
    death_msg: str = ""
    num_hits: int = 0


def apply_sequence_to_target(
    sequence: "AttackSequence",
    target: "Creature",
    *,
    attacker: "Optional[Creature]" = None,
) -> ResolutionResult:
    """Resolve ``sequence`` against ``target`` — see module docstring.

    :param sequence: The :class:`AttackSequence` whose per-hit
        ``AttackResult`` entries carry ``damage`` and optional
        ``target_part`` references.
    :param target: The creature absorbing the sequence. Must expose
        ``apply_damage(amount, dmg_type=..., target_part=...)``.
    :param attacker: Optional attacker. When supplied,
        ``attacker.on_target_part_destroyed(target, part)`` fires once
        per part destroyed by the sequence (in addition to the part's
        own ``on_destroyed`` hook). When ``None`` (default),
        no attacker-side hook fires — preserving the player-attacks-
        monster path's intentional asymmetry.
    :return: A :class:`ResolutionResult` with the aggregate damage
        figures, feedback lines, and any captured death message.
    """
    injury_feedback: List[str] = []
    death_msg = ""
    num_hits = 0
    body_damage_total = 0

    # Snapshot each uniquely-hit part's starting injury level *once*
    # before any damage lands. This is the crux of the hook-coalescing
    # guarantee: a 3-source attack against the same arm records one
    # "old_level" (NONE), applies all hits, then fires a single
    # on_injury_change(NONE -> whatever-it-reached). Keyed by id(part)
    # so identity comparisons survive equality overrides.
    part_starting_levels: Dict[int, Tuple["BodyPart", InjuryLevels]] = {}

    for result in sequence.results:
        if result.damage <= 0:
            continue
        num_hits += 1
        body_damage_total += result.damage
        part = result.target_part
        if part is not None and id(part) not in part_starting_levels:
            part_starting_levels[id(part)] = (part, part.get_injury_level())

        # Pure damage application — ``apply_damage`` doesn't fire part
        # hooks. The helper snapshots old levels, applies all hits,
        # then fires each part's ``on_injury_change`` / ``on_destroyed``
        # exactly once below, so multi-source sequences produce a
        # single coalesced side-effect burst per part (wing grounding,
        # doppelganger pain cries, etc.).
        d_msg = target.apply_damage(
            result.damage,
            dmg_type=result.dmg_type,
            target_part=part,
        )
        if d_msg and not death_msg:
            death_msg = d_msg

    # Emit one injury message per unique hit part based on the
    # coalesced level transition. ``apply_damage`` intentionally does
    # NOT fire these hooks itself — this is the single authoritative
    # call site so hooks with side effects (wing grounding, pain cries)
    # fire exactly once per attack action per part.
    for part, old_level in part_starting_levels.values():
        new_level = part.get_injury_level()
        if new_level == old_level:
            continue

        if new_level != InjuryLevels.NONE:
            feedback = part.get_injury_string()
            injury_feedback.append(f"   {feedback[0].upper()}{feedback[1:]}")

        hook_msg = part.on_injury_change(target, old_level, new_level)
        if hook_msg:
            injury_feedback.append(f"   {hook_msg}")

        # First-time destruction: fire on_destroyed once, plus the
        # attacker-side hook when an attacker was supplied.
        if (
            new_level == InjuryLevels.USELESS
            and old_level != InjuryLevels.USELESS
        ):
            destroyed_msg = part.on_destroyed(target)
            if destroyed_msg:
                injury_feedback.append(f"   {destroyed_msg}")
            if attacker is not None:
                attacker_msg = attacker.on_target_part_destroyed(target, part)
                if attacker_msg:
                    injury_feedback.append(f"   {attacker_msg}")

    return ResolutionResult(
        body_damage_total=body_damage_total,
        injury_feedback_lines=injury_feedback,
        death_msg=death_msg,
        num_hits=num_hits,
    )
