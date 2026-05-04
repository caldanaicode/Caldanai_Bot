"""Passerby spawn pipeline — pure functions that operate on a
game-like object so the state-machine logic is testable without
instantiating :class:`Game`.

State machine
-------------

A game can be in one of four passerby states:

1. **Idle** — ``game.passerby is None`` and
   ``game.pending_silhouette is None``. Default state.
2. **Present** — ``game.passerby is <NPC>`` and
   ``game.pending_silhouette is None``. NPC has arrived; players
   can interact via ``$wave`` / ``$nod`` / ``$greet``.
3. **Pending silhouette** — ``game.passerby is None`` and
   ``game.pending_silhouette is <NPC>``. NPC arrived during
   active combat; held in distance until combat resolves.
4. **(invalid)** — both fields populated. Should never happen;
   :func:`attempt_spawn` skips when either is set.

Transitions
-----------

- Idle → Present: :func:`attempt_spawn` while no combat.
- Idle → Pending: :func:`attempt_spawn` while combat is active.
- Pending → Present: :func:`drain_silhouette` after combat ends.
- Present → Idle: :func:`depart_passerby` (timer-driven or
  player-pushed).
- Pending → Idle: :func:`drain_silhouette` (always advances to
  Present on combat end; no pending-departure path).

Game integration is minimal: schedule
:func:`attempt_spawn` on a per-channel timer, call
:func:`drain_silhouette` from ``_finalize_combat`` (with the
combat outcome), and schedule :func:`depart_passerby` when an
NPC arrives. All three operate on a duck-typed game object —
tests use a :class:`SimpleNamespace` standing in.
"""

from random import choice, random
from typing import Any, Optional, Type

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.creatures.passersby.rendering import (
    render_combat_witness,
    render_npc_only,
)
from caldanai.lib.rpg.creatures.passersby.state import (
    get_state,
    mark_encounter,
)
from caldanai.lib.rpg.helpers.enums import TimesOfDay


# Outcome constants for :func:`drain_silhouette`.
OUTCOME_WON = "won"
OUTCOME_FLED = "fled"
OUTCOME_DEATH = "death"


def is_combat_active(game: Any) -> bool:
    """Combat is active when there's a living monster AND at
    least one combatant engaged. ``Game.monster`` may be set
    without combatants if a monster spawned but no players have
    joined yet — silhouette mode shouldn't fire just because a
    monster exists; it should fire when there's an actual fight
    in progress."""
    monster = getattr(game, "monster", None)
    if monster is None or monster.is_dead():
        return False
    combatants = getattr(game, "combatants", None) or []
    return bool(combatants)


def pick_npc(
    game: Any,
    *,
    registry: Optional[dict] = None,
    time_of_day: Optional[TimesOfDay] = None,
) -> Optional[Type[PasserbyPlugin]]:
    """Pick a passerby class to spawn this attempt.

    V1: uniform random across the loaded plugin registry,
    filtered by ``time_of_day`` against each plugin's
    ``time_partition``. A child errand-runner won't appear at
    midnight; a wagoneer won't be on the road at 02:00.

    ``time_of_day`` parameter overrides the game-clock lookup —
    handy for tests that want deterministic time. Production
    binding pulls from ``game.game_clock.get_time_of_day()``.

    V2 will additionally weight by NPC-toward-channel-warmth
    (cold-warmth NPCs choose safer routes, lowering their
    per-attempt probability) per Caels' design direction.
    """
    reg = registry if registry is not None else PasserbyPlugin._PLUGIN_REGISTRY
    if not reg:
        return None
    # Deduplicate on plugin class — registry keys include aliases,
    # but each class should have one chance per attempt.
    distinct = list(dict.fromkeys(reg.values()))

    # Time-of-day filter. Resolve from the game clock if not
    # explicitly passed. ``getattr`` cascade keeps the function
    # robust against test fixtures lacking a clock.
    if time_of_day is None:
        clock = getattr(game, "game_clock", None)
        get_time = getattr(clock, "get_time_of_day", None) if clock else None
        if get_time is not None:
            try:
                time_of_day = TimesOfDay[get_time().upper()]
            except (KeyError, AttributeError):
                time_of_day = None

    if time_of_day is not None:
        distinct = [
            c for c in distinct
            if bool(time_of_day & getattr(
                c, "time_partition",
                # Default to all-times-active when a class
                # doesn't declare a partition (defensive).
                TimesOfDay.DAWN | TimesOfDay.MORNING | TimesOfDay.NOON
                | TimesOfDay.AFTERNOON | TimesOfDay.EVENING
                | TimesOfDay.DUSK | TimesOfDay.NIGHT,
            ))
        ]

    return choice(distinct) if distinct else None


def attempt_spawn(game: Any) -> Optional[str]:
    """Attempt to spawn a passerby. Returns the arrival or
    silhouette flavor line for the dispatcher to send, or
    ``None`` if spawn skipped (already present, no NPCs loaded).

    State after the call:

    - **Idle → Present**: ``game.passerby`` set; arrival flavor
      returned. ``mark_encounter`` increments met_count for any
      players currently in the channel (V2; V1 leaves player-
      tracking to interaction time).
    - **Idle → Pending**: ``game.pending_silhouette`` set;
      silhouette flavor returned.
    - **Already busy**: returns ``None`` without state change.
    """
    if getattr(game, "passerby", None) is not None:
        return None
    if getattr(game, "pending_silhouette", None) is not None:
        return None

    npc_cls = pick_npc(game)
    if npc_cls is None:
        return None
    npc = npc_cls()

    if is_combat_active(game):
        game.pending_silhouette = npc
        pool = npc.SILHOUETTE_POOL or npc.ARRIVAL_POOL
    else:
        game.passerby = npc
        pool = npc.ARRIVAL_POOL

    if not pool:
        return None
    return render_npc_only(choice(pool), npc)


def drain_silhouette(
    game: Any,
    outcome: str,
    *,
    witness: Optional[Any] = None,
    collection: Optional[Any] = None,
) -> Optional[str]:
    """Promote a pending-silhouette NPC to present, and return the
    outcome-aware approach flavor.

    ``outcome`` is one of :data:`OUTCOME_WON` /
    :data:`OUTCOME_FLED` / :data:`OUTCOME_DEATH`, mapping to the
    NPC's three combat-resolved reaction pools.

    ``witness`` is a representative party member referenced as
    ``@2`` in the reaction line — the killing-blow dealer for WON,
    a still-alive party member for FLED, the fallen for DEATH.
    Optional; if omitted, the line renders without an explicit
    target (useful when the outcome doesn't cleanly map to one
    party member, or for fallback rendering).

    Returns the flavor line, or ``None`` if no silhouette was
    pending.
    """
    npc = getattr(game, "pending_silhouette", None)
    if npc is None:
        return None
    game.pending_silhouette = None
    game.passerby = npc

    pool = {
        OUTCOME_WON: npc.COMBAT_WON_REACTIONS,
        OUTCOME_FLED: npc.COMBAT_FLED_REACTIONS,
        OUTCOME_DEATH: npc.PARTY_DEATH_REACTIONS,
    }.get(outcome, [])

    if not pool:
        # No reaction pool for this outcome — fall through to a
        # generic arrival rather than fail silently.
        pool = npc.ARRIVAL_POOL
    if not pool:
        return None

    line = choice(pool)
    if witness is None:
        return render_npc_only(line, npc)

    # Read NPC-toward-witness state so the StrangerActor-vs-real-
    # name decision uses the right acquaintance level.
    npc_stem = type(npc).__name__.lower()
    state = get_state(
        game.channel_id, npc_stem, witness.user_id, collection=collection,
    )
    return render_combat_witness(
        line, npc, witness,
        acquainted=state.acquainted, naming_bias=npc.NAMING_BIAS,
    )


def depart_passerby(game: Any) -> Optional[str]:
    """Send the present passerby on their way. Returns the
    departure flavor for the dispatcher; sets ``game.passerby``
    to ``None``. Idempotent — safe to call when no NPC is
    present (returns ``None``).
    """
    npc = getattr(game, "passerby", None)
    if npc is None:
        return None
    game.passerby = None
    pool = npc.DEPARTURE_POOL
    if not pool:
        return None
    return render_npc_only(choice(pool), npc)


def flee_from_attack(
    game: Any,
    attacker: Any,
    *,
    collection: Optional[Any] = None,
) -> Optional[str]:
    """Run the attack-response path: NPC flees, NPC-toward-attacker
    warmth drops one tier (floored at COLD), state-machine returns
    to Idle. Returns the flee flavor line; ``None`` if no NPC was
    present to attack.

    Acquaintance level is read for the actor-rendering (the
    attacker may or may not be a known face) — the flee line
    uses ``@2`` for the attacker, so the StrangerActor wrap
    applies based on the NPC's prior knowledge of them.
    """
    from caldanai.lib.rpg.creatures.passersby.rendering import render_actor_npc
    from caldanai.lib.rpg.creatures.passersby.state import degrade_warmth

    npc = getattr(game, "passerby", None)
    if npc is None:
        return None

    npc_stem = type(npc).__name__.lower()

    # Read state for line-rendering acquaintance, then apply the
    # warmth degrade. Order matters slightly: we want the line to
    # render with the PRE-attack acquaintance (so the NPC's
    # parting flavor still uses the attacker's name if known —
    # the attacker EARNS the cold; the flavor reads "Caels — no
    # — easy now —" rather than "traveler — no —" if they were
    # acquainted).
    state = get_state(
        game.channel_id, npc_stem, attacker.user_id, collection=collection,
    )
    pool = npc.FLEE_FROM_ATTACK_POOL
    line = (
        render_actor_npc(
            choice(pool), attacker, npc,
            acquainted=state.acquainted, naming_bias=npc.NAMING_BIAS,
        )
        if pool else None
    )

    degrade_warmth(
        game.channel_id, npc_stem, attacker.user_id, collection=collection,
    )
    game.passerby = None
    return line


def overhear_mentions(
    game: Any,
    message: Any,
    *,
    collection: Optional[Any] = None,
) -> "list[int]":
    """When a player posts an in-channel message that ``<@!id>``-
    mentions other players, and a passerby is present (or
    waiting in silhouette), the NPC learns the mentioned
    players' names.

    Returns the list of player ids newly marked as acquainted by
    this call. Callers (the cog ``on_message`` listener) use the
    list to dispatch the ACQUAINTANCE_CUE_POOL beat per learned
    player, surfacing the otherwise-silent learning channel.

    Side-effects: calls :func:`mark_acquainted` for each
    mentioned player who isn't already known to this NPC.
    Idempotent — already-acquainted players are no-ops.
    """
    from caldanai.lib.rpg.creatures.passersby.state import (
        get_state, mark_acquainted,
    )

    npc = (
        getattr(game, "passerby", None)
        or getattr(game, "pending_silhouette", None)
    )
    if npc is None:
        return []
    mentions = getattr(message, "mentions", None) or []
    if not mentions:
        return []

    npc_stem = type(npc).__name__.lower()

    # Pull the player roster for membership filtering — the NPC
    # only learns names of *game players*, not bystanders or the
    # bot itself. Filtering on player_manager.players keeps
    # mention-bombs against random Discord users from leaking
    # acquaintance.
    pm = getattr(game, "player_manager", None)
    player_pool = getattr(pm, "players", {}) if pm else {}

    # Set-intersect mention ids against the player_pool BEFORE any
    # Mongo round-trip — caps the per-message work at the smaller
    # of (mentions, players) and short-circuits @everyone-style
    # mention bombs without paying a find_one per non-player id.
    mention_ids = {
        m.id for m in mentions
        if getattr(m, "id", None) is not None
        and not getattr(m, "bot", False)
    }
    candidate_ids = mention_ids & player_pool.keys()

    newly_acquainted: list[int] = []
    for mid in candidate_ids:
        # Check current state to count only first-time
        # acquaintances; mark_acquainted itself is idempotent.
        prior = get_state(
            game.channel_id, npc_stem, mid, collection=collection,
        )
        if prior.acquainted:
            continue
        mark_acquainted(
            game.channel_id, npc_stem, mid, "mention",
            collection=collection,
        )
        newly_acquainted.append(mid)
    return newly_acquainted
