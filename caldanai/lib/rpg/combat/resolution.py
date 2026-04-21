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
  is invoked once per result with positive damage **when the target
  has body parts**. ``apply_damage`` is a pure damage-application
  primitive — it does not fire part hooks. The helper below is
  responsible for the coalesced fire so multi-source sequences don't
  produce duplicate side effects (wing grounding, doppelganger pain
  cries, etc.).
- For **partless targets** (e.g. Spirit), ``apply_damage`` is
  **skipped** — its legacy whole-body path would mutate body HP that
  the caller is already responsible for applying post-defense,
  producing double-damage. Body HP is the caller's sole owner across
  both partless and parts paths.
- ``part.on_injury_change`` fires exactly once per unique hit part
  whose injury level changed across the sequence — the "old" level is
  snapshotted before any hit lands, so multi-source sequences don't
  double-fire ("lightly battered" then "utterly destroyed" for one
  attack action).
- ``part.on_destroyed`` fires exactly once per part that transitioned
  into USELESS. Parts already USELESS entering the sequence are not
  fired on.
- ``attacker.on_target_part_destroyed`` fires when the attacker
  defines the hook. The helper auto-infers the attacker from
  ``sequence.attacker`` when ``attacker`` isn't passed, so future
  multi-victim overrides can't silently drop the hook by
  forgetting the kwarg. The player-attacks-monster asymmetry is
  preserved by ``hasattr`` — Players don't define the hook — so
  the auto-inferred player-as-attacker never fires it.

Why a free function (not a Creature method): one consumer (Hydra)
wants to interleave hook-firing with narrative paragraphs mid-sequence.
Composition keeps the loop reusable without forcing the callers into a
fixed overall output shape.
"""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from caldanai.lib.rpg.helpers.enums import InjuryLevels
from caldanai.lib.rpg.helpers.parser import parse

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
    - ``critical_part_kill``: ``True`` when the victim died because a
      critical body part (head, torso, etc.) was destroyed during
      this sequence. Distinguishes from body-HP-depletion death.
      Callers use this to suppress the redundant "Total damage done
      vs Health" summary (the "utterly destroyed" feedback + death
      message already tells the story) without inferring it from
      arithmetic, which false-positives against status-tick damage,
      magic-that-bypasses-body-HP, and any other future kill path
      that doesn't add to body-HP accumulators.
    """

    body_damage_total: int
    injury_feedback_lines: List[str] = field(default_factory=list)
    death_msg: str = ""
    num_hits: int = 0
    critical_part_kill: bool = False
    # Q.6 — the positive-damage results that contributed to this
    # victim's body_damage_total. Carried so the Q.6 body-HP formula
    # (``compute_body_hp_damage``) can iterate damage × part.bleed_rate
    # without re-threading the bucket through every caller.
    victim_results: "List[object]" = field(default_factory=list)


@dataclass
class MultiVictimResolutionResult:
    """Multi-victim aggregate over per-victim :class:`ResolutionResult`.

    Shape the pipeline's ``resolve`` stage produces once a block can
    attack several targets at once (hydra today, swarms + AoE magic
    later). Legacy single-victim callers continue to use
    ``apply_sequence_to_target`` / :class:`ResolutionResult` directly —
    this wrapper is additive.

    - ``per_victim`` — one ``ResolutionResult`` per distinct victim,
      keyed by the victim ``Creature``.
    - ``all_results`` — flat list of every :class:`AttackResult` in
      assignment order; the renderer's table iterates this.
    - ``any_critical_part_kill`` — sticky OR across ``per_victim`` so
      the damage-summary suppression gate reads one field.
    """

    per_victim: "Dict[Creature, ResolutionResult]" = field(default_factory=dict)
    all_results: "List[object]" = field(default_factory=list)
    any_critical_part_kill: bool = False


def compute_body_hp_damage(
    resolution: ResolutionResult,
    victim: "Creature",
    defense: int = 0,
    *,
    results: "Optional[List[object]]" = None,
) -> int:
    """Q.6.2 body-HP damage formula.

    Formula::

        body_hp_dmg = max(
            num_hits,
            int(sum(r.damage * r.target_part.bleed_rate) * victim.BLEED_MOD)
        )

    - ``num_hits`` remains the floor ("you connected").
    - Per-part ``bleed_rate`` tunes how much part-damage bleeds into
      body HP — torso is high, eye is low.
    - ``victim.BLEED_MOD`` is a creature-wide multiplier (default 1.0)
      that lets skeletons / golems / vampires tune feel without new
      structural classes.
    - **Defense is already applied per-hit** inside
      ``Creature.resolve_attack`` (Q.6.2 change from per-sum to
      per-hit). ``result.damage`` is post-defense. The ``defense``
      arg is accepted for call-site compatibility but ignored.

    ``results`` overrides the damage-contributing results — legacy
    callers that retain the old single-victim ``AttackSequence``
    shape pass ``sequence.results``; the pipeline path omits it and
    we pull ``victim_results`` off the per-victim
    :class:`ResolutionResult` via the helper arg.
    """
    num_hits = resolution.num_hits
    if num_hits <= 0:
        return 0
    iterable = results if results is not None else getattr(
        resolution, "victim_results", []
    )
    bleed_total = 0.0
    for r in iterable:
        damage = getattr(r, "damage", 0)
        if damage <= 0:
            continue
        part = getattr(r, "target_part", None)
        rate = getattr(part, "bleed_rate", 1.0) if part is not None else 1.0
        bleed_total += damage * rate
    bleed_mod = getattr(victim, "BLEED_MOD", 1.0)
    scaled = int(bleed_total * bleed_mod)
    return max(num_hits, scaled)


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
    :param attacker: Optional attacker override. When not supplied,
        the helper auto-infers from ``sequence.attacker`` so future
        multi-victim overrides can't silently drop the hook by
        forgetting the kwarg. The player-attacks-monster asymmetry
        is preserved by a ``hasattr`` gate on the hook call — Players
        don't define ``on_target_part_destroyed`` so the auto-
        inferred player-as-attacker never fires it. Pass an explicit
        value only to override the sequence's attacker (rare).
    :return: A :class:`ResolutionResult` with the aggregate damage
        figures, feedback lines, and any captured death message.
    """
    # Auto-infer attacker from the sequence when the caller didn't
    # pass one. Guards against future multi-victim overrides
    # forgetting ``attacker=self``.
    if attacker is None:
        attacker = getattr(sequence, "attacker", None)
    injury_feedback: List[str] = []
    death_msg = ""
    num_hits = 0
    body_damage_total = 0
    critical_part_kill = False

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

        # Partless targets (e.g. Spirit): ``Creature.apply_damage``'s
        # legacy path would mutate body HP here, and the caller
        # (``do_combat``) ALSO subtracts the post-defense body total
        # after this helper returns — that produces double-damage.
        # Skip ``apply_damage`` for partless targets; body HP is the
        # caller's sole responsibility in both paths, and the
        # partless-creature death flows through the caller's
        # ``monster.health == 0 and not death_msg: monster.death``
        # fallback rather than via ``MonsterPlugin.apply_damage``.
        if part is None and not target.body_parts:
            continue

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
        # Critical-part kill signal: when the victim died as a result
        # of this part-targeted ``apply_damage`` call, it was a
        # critical-part destruction (head, torso, etc. — see
        # ``Creature.apply_damage`` for the ``is_critical`` path).
        # Distinguishes from body-HP-depletion death, which only
        # materializes after the caller applies the post-defense
        # body total. Callers use this flag to suppress the
        # redundant HP-summary line.
        if d_msg and part is not None and target.is_dead():
            critical_part_kill = True

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
            # Prefix the owner so multi-target sequences (hydra now,
            # future AoE magic / ranged splash / swarm monsters) don't
            # produce anonymous "The left leg is…" streams where the
            # reader can't tell whose leg took the damage. Strip the
            # leading "the " so the possessive prefix doesn't read
            # "Caels's the left leg…".
            owner_prefix = parse("@1npc", target) if target is not None else ""
            if owner_prefix:
                if feedback[:4].lower() == "the ":
                    feedback = feedback[4:]
                feedback = f"{owner_prefix} {feedback}"
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
            # ``hasattr`` gate preserves the player-attacks-monster
            # asymmetry without requiring the caller to pass
            # ``attacker=None`` explicitly. Players don't define
            # ``on_target_part_destroyed``; monsters do (default
            # no-op on ``MonsterPlugin``, overridden where useful).
            if attacker is not None and hasattr(attacker, "on_target_part_destroyed"):
                attacker_msg = attacker.on_target_part_destroyed(target, part)
                if attacker_msg:
                    injury_feedback.append(f"   {attacker_msg}")

    return ResolutionResult(
        body_damage_total=body_damage_total,
        injury_feedback_lines=injury_feedback,
        death_msg=death_msg,
        num_hits=num_hits,
        critical_part_kill=critical_part_kill,
        victim_results=[r for r in sequence.results if r.damage > 0],
    )
