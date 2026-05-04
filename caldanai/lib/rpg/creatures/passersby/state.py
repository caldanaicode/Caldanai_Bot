"""Per-channel passerby NPC state — warmth, acquaintance, and
encounter accumulation, persisted to MongoDB.

Schema
------

One document per ``(channel_id, npc_stem)`` pair. Each NPC is one
entity in the world; players' relationships with that NPC live as
a ``players`` sub-mapping keyed by Discord ``user_id`` (string,
since Mongo dict keys are always strings).

.. code-block:: python

    {
        "_id":         <ObjectId>,
        "channel_id":  <int>,                # Discord channel where this NPC lives
        "npc_stem":    <str>,                # plugin filename stem ("wagoneer", "wren", ...)
        "players": {
            "<player_id>": {                 # str(int) — Mongo key form
                "warmth_credits":            <int>,         # Source of truth — tier derived from this
                "warmth":                    <str>,         # Cached tier (re-derived on every write)
                "acquainted":                <bool>,        # NPC knows what to call this player
                "acquainted_via":            <str | None>,  # "greet" | "mention" | "osmosis"
                "met_count":                 <int>,         # encounters total on this channel
                "first_met":                 <datetime>,
                "last_seen":                 <datetime>,

                # Per-visit interaction tracking. Reset on each NPC
                # arrival so that "first warm verb of the visit gives
                # +5; second of the same verb gives 0" works without
                # the schema lying about state.
                "visit_arrived_at":          <datetime | None>,
                "tier_at_visit_start":       <str>,         # for the per-visit one-tier-shift clamp
                "visit_warm_verbs":          <list[str]>,
                "visit_cold_verbs":          <list[str]>,
                "visit_witnessed_kill_count":<int>,
                "visit_credits_delta":       <int>,
            },
            # ... one slice per player who has interacted
        },
        # Future: NPC-level state can land here (last_seen_in_channel,
        # spawn_count_total, NPC's own moods, etc.) without restructuring.
    }

Why one doc per NPC (rather than per (channel, npc, player) triple
as before): the shepherd is one entity in the world. Three players
acquainted with the shepherd are three relationships, not three
shepherds. Inspection reads as one ``find_one`` per NPC. Future
NPC-level state has a home. Concurrent player writes use
dotted-path atomic ``$set: {f"players.{pid}": <slice>}`` so two
players' updates can't clobber each other.

Why every mutator writes the FULL per-player slice: a previous
shape persisted only the fields the mutator was changing
(``mark_encounter`` wrote met_count + acquainted but never wrote
warmth). Result: warmth lived only in memory and never landed in
Mongo, so inspection-via-Compass showed half-state. Every write
now serializes the full slice via :func:`_upsert_player_slice`,
ensuring the persisted shape always matches the in-memory truth.

Acquaintance learning events (set ``acquainted_via`` to the
matching tag and flip ``acquainted=True``):

- ``"greet"`` — the player ran ``$greet <NPC>`` directly.
- ``"mention"`` — another in-channel player @mentioned this
  player while the NPC was present.
- ``"osmosis"`` — passive accumulation: ``met_count >= 3`` with
  ``warmth >= NEUTRAL``. Set automatically by
  :func:`mark_encounter` when threshold is crossed.

Warmth model
------------

The five-tier ``Warmth`` enum is the player-facing concept (COLD →
COOL → NEUTRAL → WARM → HOT). The actual source of truth on disk
is ``warmth_credits``, an int conceptually in ``[-100, +100]``.
Tier is derived per :data:`WARMTH_TIERS`:

- HOT:     +40 .. +100
- WARM:    +20 .. +39
- NEUTRAL: -19 ..  +19
- COOL:    -39 ..  -20
- COLD:   -100 ..  -40

Credits change via :func:`apply_credits` (per-verb +5 / +2 / -2 /
-5 by tier classification of the verb), :func:`witness_kill`
(+10 for non-passive kills, configurable penalty for passive),
and :func:`apply_decay` (-1 per missed visit). Per-visit clamp
limits one full tier shift up or down per NPC visit even if many
positive or negative events stack.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Union

from pymongo import UpdateOne

from caldanai.db import DB
from caldanai.lib.rpg.helpers.warmth import Warmth


# Threshold for time-based osmosis acquaintance.
_OSMOSIS_MET_COUNT = 3


# Warmth tier ordering for the degrade/promote step helpers. Index
# 0 = COLD (lowest); index 4 = HOT (highest). Steps are clamped to
# the [0, 4] range so a single attack drop from COLD stays at COLD
# rather than wrapping or erroring.
_WARMTH_LADDER = (
    Warmth.COLD,
    Warmth.COOL,
    Warmth.NEUTRAL,
    Warmth.WARM,
    Warmth.HOT,
)


# Tier → (low_inclusive, high_inclusive) credit range. Order
# matters: low → high. Used for both tier derivation and the
# per-visit one-tier-shift clamp.
WARMTH_TIERS: Tuple[Tuple[Warmth, int, int], ...] = (
    (Warmth.COLD,    -100, -40),
    (Warmth.COOL,     -39, -20),
    (Warmth.NEUTRAL,  -19,  19),
    (Warmth.WARM,      20,  39),
    (Warmth.HOT,       40, 100),
)

WARMTH_CREDITS_FLOOR: int = -100
WARMTH_CREDITS_CEIL: int = 100

# Per-verb credit deltas, keyed by the tier classification of the
# verb (from ``warmth.SYSTEM_DEFAULTS``). HOT/WARM verbs (hug,
# comfort) earn +5; NEUTRAL verbs (nod, salute, fistbump) earn
# +2 (engagement is warmer than ignoring, but less than tender);
# COOL verbs (poke, tickle) lose -2; COLD verbs (glare, shank,
# taunt) lose -5.
VERB_CREDIT_DELTA_BY_TIER = {
    Warmth.HOT:     +5,
    Warmth.WARM:    +5,
    Warmth.NEUTRAL: +2,
    Warmth.COOL:    -2,
    Warmth.COLD:    -5,
}

# Explicit $greet bonus — the introduction always counts as a warm
# beat, even though $greet isn't a "warmth-aware" verb in the
# SYSTEM_DEFAULTS sense.
GREET_CREDIT_DELTA: int = +5

# Witnessed-monster-death credits applied to each combatant who
# survived to claim loot. Default for non-passive kills is +10
# ("you protected the clearing"). Default for passive kills is
# -10 ("most people don't want to see you slaughter helpless
# things"); per-NPC ``PASSIVE_KILL_PENALTY`` overrides can raise
# the magnitude or replace with the special ``"tier_drop"``
# sentinel that drops a full tier instead.
WITNESS_NON_PASSIVE_KILL_CREDIT: int = +10
WITNESS_PASSIVE_KILL_DEFAULT_CREDIT: int = -10
TIER_DROP_SENTINEL: str = "tier_drop"

# Decay applied per NPC visit where the player had a slice (was
# known to this NPC) but didn't interact at all this visit. Tiny
# per-visit amount lets relationships slowly cool over absence
# without punishing one missed visit.
DECAY_PER_NO_INTERACTION_DEPART: int = -1


def warmth_from_credits(credits: int) -> Warmth:
    """Derive the canonical warmth tier from credits. Defensive
    against out-of-band values: above +100 → HOT, below -100 → COLD.
    """
    for tier, lo, hi in WARMTH_TIERS:
        if lo <= credits <= hi:
            return tier
    return Warmth.HOT if credits > 0 else Warmth.COLD


def _credits_from_warmth_tier(tier: Warmth) -> int:
    """Representative midpoint credit value for a tier — used to
    upgrade legacy slices that have a stored ``warmth`` field but
    no ``warmth_credits``. Picks a value safely inside the tier
    range so the migrated player doesn't sit on a tier boundary.
    """
    return {
        Warmth.HOT:     50,
        Warmth.WARM:    25,
        Warmth.NEUTRAL:  0,
        Warmth.COOL:   -25,
        Warmth.COLD:   -50,
    }.get(tier, 0)


def _per_visit_credit_bounds(start_tier: Warmth) -> Tuple[int, int]:
    """Compute the (min, max) credit values this visit can land at,
    enforcing at most one full tier shift in either direction
    relative to the tier the player held when the NPC arrived.

    Player at NEUTRAL → can go up to top of WARM (+39) or down to
    bottom of COOL (-39). Player at HOT can't go higher (cap at
    +100); player at COLD can't go lower (floor at -100).
    """
    tiers = [t for t, _, _ in WARMTH_TIERS]
    try:
        idx = tiers.index(start_tier)
    except ValueError:
        idx = tiers.index(Warmth.NEUTRAL)
    if idx + 1 < len(tiers):
        max_credit = WARMTH_TIERS[idx + 1][2]
    else:
        max_credit = WARMTH_CREDITS_CEIL
    if idx - 1 >= 0:
        min_credit = WARMTH_TIERS[idx - 1][1]
    else:
        min_credit = WARMTH_CREDITS_FLOOR
    return (min_credit, max_credit)


@dataclass
class PasserbyState:
    """In-memory representation of a single per-(channel, npc, player)
    relationship slice. Defaults match a "first encounter" record:
    NEUTRAL warmth (credits=0), not acquainted, met_count 0.

    The dataclass carries the channel/npc/player triple even though
    the persisted slice doesn't store them — those identify *which*
    slice the in-memory state belongs to, but they're keyed via
    the parent doc + sub-mapping key on disk."""

    channel_id: int
    npc_stem: str
    player_id: int

    # Source of truth for relationship strength. Tier is derived.
    warmth_credits: int = 0
    warmth: Warmth = Warmth.NEUTRAL

    acquainted: bool = False
    acquainted_via: Optional[str] = None
    met_count: int = 0
    first_met: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_seen: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Per-visit tracking. Reset on each NPC arrival via
    # :func:`mark_visit_arrival`. Each warm/cold verb counts at
    # most once per visit; the per-visit credit-delta sum is the
    # input to the one-tier-shift clamp.
    visit_arrived_at: Optional[datetime] = None
    tier_at_visit_start: Warmth = Warmth.NEUTRAL
    visit_warm_verbs: List[str] = field(default_factory=list)
    visit_cold_verbs: List[str] = field(default_factory=list)
    visit_witnessed_kill_count: int = 0
    visit_credits_delta: int = 0

    def __post_init__(self) -> None:
        """Always sync the cached ``warmth`` tier from credits so the
        derived value never drifts from its source. Subclasses /
        callers that mutate ``warmth_credits`` directly should call
        :meth:`_recompute_warmth` to keep the cached field honest."""
        self._recompute_warmth()

    def _recompute_warmth(self) -> None:
        """Re-derive ``warmth`` from ``warmth_credits``. Called
        automatically by helpers that mutate credits."""
        self.warmth = warmth_from_credits(self.warmth_credits)

    def had_interaction_this_visit(self) -> bool:
        """True iff any verb was used or any kill was witnessed in
        the current visit. Drives the decay-on-no-interaction
        decision at depart time."""
        return bool(
            self.visit_warm_verbs
            or self.visit_cold_verbs
            or self.visit_witnessed_kill_count
        )

    def to_slice_doc(self) -> dict:
        """Serialize the persistable slice (per-player fields only).
        Channel / NPC / player triple is identified by parent doc +
        sub-mapping key, not embedded in the slice itself."""
        d = asdict(self)
        d["warmth"] = str(self.warmth)
        d["tier_at_visit_start"] = str(self.tier_at_visit_start)
        # Strip the identity triple — it lives in the parent doc
        # key + the players-sub-mapping key.
        d.pop("channel_id", None)
        d.pop("npc_stem", None)
        d.pop("player_id", None)
        return d

    @classmethod
    def from_slice_doc(
        cls,
        slice_data: dict,
        *,
        channel_id: int,
        npc_stem: str,
        player_id: int,
    ) -> "PasserbyState":
        """Inverse of :meth:`to_slice_doc`. Tolerant of stale /
        partial slices — missing fields fall back to dataclass
        defaults rather than raising.

        Legacy migration: if a slice has a ``warmth`` tier but no
        ``warmth_credits``, derive credits from the tier midpoint
        (preserves the player's relationship across the schema
        change rather than resetting them to NEUTRAL)."""
        raw_credits = slice_data.get("warmth_credits")
        if raw_credits is None:
            legacy_warmth = (
                Warmth.from_str(slice_data.get("warmth")) or Warmth.NEUTRAL
            )
            credits = _credits_from_warmth_tier(legacy_warmth)
        else:
            credits = int(raw_credits)
        # Hard clamp on read — defends against any out-of-band
        # values that may have landed in the doc.
        credits = max(WARMTH_CREDITS_FLOOR, min(WARMTH_CREDITS_CEIL, credits))

        return cls(
            channel_id=int(channel_id),
            npc_stem=str(npc_stem).lower(),
            player_id=int(player_id),
            warmth_credits=credits,
            warmth=warmth_from_credits(credits),
            acquainted=bool(slice_data.get("acquainted", False)),
            acquainted_via=slice_data.get("acquainted_via"),
            met_count=int(slice_data.get("met_count", 0)),
            first_met=slice_data.get("first_met") or datetime.now(timezone.utc),
            last_seen=slice_data.get("last_seen") or datetime.now(timezone.utc),
            visit_arrived_at=slice_data.get("visit_arrived_at"),
            tier_at_visit_start=(
                Warmth.from_str(slice_data.get("tier_at_visit_start"))
                or warmth_from_credits(credits)
            ),
            visit_warm_verbs=list(slice_data.get("visit_warm_verbs") or []),
            visit_cold_verbs=list(slice_data.get("visit_cold_verbs") or []),
            visit_witnessed_kill_count=int(
                slice_data.get("visit_witnessed_kill_count", 0)
            ),
            visit_credits_delta=int(slice_data.get("visit_credits_delta", 0)),
        )


def _npc_key(channel_id: int, npc_stem: str) -> dict:
    """Compound key for the parent NPC doc — one doc per
    (channel, npc)."""
    return {
        "channel_id": int(channel_id),
        "npc_stem": str(npc_stem).lower(),
    }


def _player_slice_path(player_id: int) -> str:
    """Mongo dotted path into the players sub-mapping for a given
    Discord user_id. Mongo stores dict keys as strings always, so
    int player_ids land as their str() form."""
    return f"players.{int(player_id)}"


def get_state(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    collection=None,
) -> PasserbyState:
    """Fetch the per-player relationship slice for this triple.
    Returns a fresh default-shaped :class:`PasserbyState` when the
    NPC doc doesn't exist yet OR the doc exists but has no slice
    for this player — callers don't have to handle either missing
    case separately, just read fields off the dataclass.
    """
    coll = collection if collection is not None else DB._passerby_state
    doc = coll.find_one(_npc_key(channel_id, npc_stem))
    if doc:
        slice_data = (doc.get("players") or {}).get(str(int(player_id)))
        if slice_data:
            return PasserbyState.from_slice_doc(
                slice_data,
                channel_id=channel_id,
                npc_stem=npc_stem,
                player_id=player_id,
            )
    return PasserbyState(
        channel_id=int(channel_id),
        npc_stem=str(npc_stem).lower(),
        player_id=int(player_id),
    )


def _upsert_player_slice(
    coll,
    channel_id: int,
    npc_stem: str,
    player_id: int,
    state: PasserbyState,
) -> None:
    """Queue an atomic per-player slice write via the existing DB
    write-buffer pattern.

    Writes the FULL slice every time — used by lifecycle hooks
    (:func:`mark_visit_arrival`, :func:`mark_visit_depart`,
    :func:`set_warmth`, :func:`degrade_warmth`,
    :func:`promote_warmth`) where many fields change at once and a
    coherent snapshot is the natural shape.

    For per-call mutators that only touch a few fields
    (:func:`mark_encounter`, :func:`mark_acquainted`,
    :func:`apply_verb_credits`, :func:`apply_greet_credits`,
    :func:`witness_kill`), prefer :func:`_upsert_player_fields` so
    concurrent helpers in the same code path don't overwrite each
    other's changes via stale-read-and-replace-whole-slice. The
    bug that motivated the split: ``$greet`` queued three full-
    slice writes back-to-back; the second and third read stale
    state because the queue hadn't drained between them, then
    their writes wiped out fields the first write had set.
    """
    state.last_seen = state.last_seen or datetime.now(timezone.utc)
    state._recompute_warmth()
    DB._queues[coll].put(
        UpdateOne(
            _npc_key(channel_id, npc_stem),
            {"$set": {_player_slice_path(player_id): state.to_slice_doc()}},
            upsert=True,
        )
    )


def _upsert_player_fields(
    coll,
    channel_id: int,
    npc_stem: str,
    player_id: int,
    set_fields: Optional[dict] = None,
    addtoset_fields: Optional[dict] = None,
) -> None:
    """Queue a per-field upsert that only writes the listed fields,
    leaving sibling fields on the slice intact.

    Use this for mutators that change a small subset of fields —
    e.g. ``mark_acquainted`` only touches ``acquainted`` /
    ``acquainted_via`` / ``last_seen``. Compared to writing the
    whole slice, this preserves any changes made by other helpers
    whose writes are still queued — ``mark_encounter`` setting
    ``met_count=1`` survives even if ``mark_acquainted`` reads a
    stale slice and would otherwise have written ``met_count=0``
    via :func:`_upsert_player_slice`.

    ``set_fields`` keys are slice-relative names (e.g.
    ``"acquainted"``); they're rewritten to the dotted Mongo path
    ``"players.<pid>.acquainted"`` automatically.

    ``addtoset_fields`` uses Mongo's ``$addToSet`` semantics for
    list fields where idempotent-append is the right semantics
    (e.g. recording that a verb was used this visit).
    """
    if not set_fields and not addtoset_fields:
        return
    pid = int(player_id)
    update: dict = {}
    if set_fields:
        update["$set"] = {
            f"players.{pid}.{k}": v for k, v in set_fields.items()
        }
    if addtoset_fields:
        update["$addToSet"] = {
            f"players.{pid}.{k}": v for k, v in addtoset_fields.items()
        }
    DB._queues[coll].put(
        UpdateOne(
            _npc_key(channel_id, npc_stem),
            update,
            upsert=True,
        )
    )


def mark_encounter(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    collection=None,
) -> PasserbyState:
    """Increment ``met_count`` and update ``last_seen`` for this
    triple. Auto-promotes ``acquainted = True`` via osmosis when
    ``met_count >= _OSMOSIS_MET_COUNT`` and warmth is at or above
    NEUTRAL.

    Returns the updated state (post-increment, post-osmosis-check)
    so the caller can render arrival flavor with current data
    without a second read.
    """
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    state.met_count += 1
    state.last_seen = datetime.now(timezone.utc)
    set_fields = {
        "met_count": state.met_count,
        "last_seen": state.last_seen,
    }

    # Osmosis check — passive acquaintance when the NPC and player
    # have crossed paths enough times with at-or-above-neutral
    # warmth. NEUTRAL is the gate: a hostile (cool/cold) history
    # doesn't earn name-knowledge no matter how many encounters.
    if (
        not state.acquainted
        and state.met_count >= _OSMOSIS_MET_COUNT
        and _warmth_index(state.warmth) >= _warmth_index(Warmth.NEUTRAL)
    ):
        state.acquainted = True
        state.acquainted_via = "osmosis"
        set_fields["acquainted"] = True
        set_fields["acquainted_via"] = "osmosis"

    _upsert_player_fields(coll, channel_id, npc_stem, player_id, set_fields)
    return state


def mark_acquainted(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    via: str,
    *,
    collection=None,
) -> PasserbyState:
    """Flip ``acquainted = True`` and stamp the via-tag describing
    HOW the NPC learned. Idempotent — safe to call repeatedly.
    Re-acquaintance keeps the original via-tag (the FIRST learning
    event is the canonical story) unless ``acquainted`` is False
    going in.
    """
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    if state.acquainted:
        return state  # Already known; no overwrite of the via-tag.
    state.acquainted = True
    state.acquainted_via = via
    state.last_seen = datetime.now(timezone.utc)
    _upsert_player_fields(
        coll, channel_id, npc_stem, player_id,
        {
            "acquainted": True,
            "acquainted_via": via,
            "last_seen": state.last_seen,
        },
    )
    return state


def set_warmth(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    warmth: Warmth,
    *,
    collection=None,
) -> PasserbyState:
    """Set warmth to a specific tier by writing the tier's
    representative credit value. Used by tests / admin overrides;
    gameplay normally goes through :func:`apply_credits` /
    :func:`witness_kill` which step the credits."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    state.warmth_credits = _credits_from_warmth_tier(warmth)
    state._recompute_warmth()
    state.last_seen = datetime.now(timezone.utc)
    _upsert_player_slice(coll, channel_id, npc_stem, player_id, state)
    return state


def degrade_warmth(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    steps: int = 1,
    collection=None,
) -> PasserbyState:
    """Drop warmth ``steps`` tiers. Implemented atop the credits
    model: lands the player at the midpoint of the destination
    tier so subsequent fine-grained credit changes have headroom
    in either direction. Floors at COLD."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    new_idx = max(0, _warmth_index(state.warmth) - steps)
    new_warmth = _WARMTH_LADDER[new_idx]
    if new_warmth != state.warmth:
        state.warmth_credits = _credits_from_warmth_tier(new_warmth)
        state._recompute_warmth()
        state.last_seen = datetime.now(timezone.utc)
        _upsert_player_slice(coll, channel_id, npc_stem, player_id, state)
    return state


def promote_warmth(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    steps: int = 1,
    collection=None,
) -> PasserbyState:
    """Raise warmth ``steps`` tiers. Implemented atop the credits
    model: lands the player at the midpoint of the destination
    tier. Caps at HOT."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    new_idx = min(len(_WARMTH_LADDER) - 1, _warmth_index(state.warmth) + steps)
    new_warmth = _WARMTH_LADDER[new_idx]
    if new_warmth != state.warmth:
        state.warmth_credits = _credits_from_warmth_tier(new_warmth)
        state._recompute_warmth()
        state.last_seen = datetime.now(timezone.utc)
        _upsert_player_slice(coll, channel_id, npc_stem, player_id, state)
    return state


# ---------------------------------------------------------------------------
# Credit-application primitives
# ---------------------------------------------------------------------------

def _apply_credits_in_memory(state: PasserbyState, delta: int) -> int:
    """Apply a credit delta to a state in memory, with the
    per-visit one-tier-shift clamp and the hard ±100 floor/ceiling.

    Returns the actual delta applied (which may be smaller than
    requested when the per-visit clamp absorbs the excess, e.g. a
    NEUTRAL player who's already gained +20 this visit can't pick
    up another +5 from a fifth warm verb — they're already at the
    top of WARM).
    """
    if delta == 0:
        return 0
    min_visit, max_visit = _per_visit_credit_bounds(state.tier_at_visit_start)
    target = state.warmth_credits + delta
    clamped = max(min_visit, min(max_visit, target))
    clamped = max(WARMTH_CREDITS_FLOOR, min(WARMTH_CREDITS_CEIL, clamped))
    actual = clamped - state.warmth_credits
    state.warmth_credits = clamped
    state.visit_credits_delta += actual
    state._recompute_warmth()
    return actual


def apply_verb_credits(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    verb: str,
    verb_warmth_tier: Warmth,
    *,
    collection=None,
) -> Tuple[PasserbyState, int]:
    """Apply per-visit warm/cold credit for a social verb.

    The same verb fires credits at most once per visit — second
    invocation of `$hug` in the same wagoneer-stay yields 0 delta.
    Different warm verbs each count once: `$hug` then `$comfort`
    then `$nod` accumulate.

    Magnitude is read from :data:`VERB_CREDIT_DELTA_BY_TIER`,
    keyed by the warmth-tier classification of the verb in
    ``warmth.SYSTEM_DEFAULTS``.

    Returns ``(updated_state, actual_delta_applied)``. A 0 delta
    return means either the verb has no associated credit shift
    (NEUTRAL by absence in the table) or the per-visit clamp
    absorbed it (already capped this visit).
    """
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    delta = VERB_CREDIT_DELTA_BY_TIER.get(verb_warmth_tier, 0)
    if delta == 0:
        return state, 0

    is_warm = delta > 0
    bucket = state.visit_warm_verbs if is_warm else state.visit_cold_verbs
    bucket_field = "visit_warm_verbs" if is_warm else "visit_cold_verbs"
    if verb in bucket:
        return state, 0
    bucket.append(verb)

    actual = _apply_credits_in_memory(state, delta)
    state.last_seen = datetime.now(timezone.utc)
    _upsert_player_fields(
        coll, channel_id, npc_stem, player_id,
        set_fields={
            "warmth_credits": state.warmth_credits,
            "warmth": str(state.warmth),
            "visit_credits_delta": state.visit_credits_delta,
            "last_seen": state.last_seen,
        },
        addtoset_fields={bucket_field: verb},
    )
    return state, actual


def apply_greet_credits(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    collection=None,
) -> Tuple[PasserbyState, int]:
    """Apply the explicit ``$greet`` credit bump (+5). Treated as
    a once-per-visit warm verb — uses the same dedup bucket as
    real warm verbs so a player can't $greet then $hug then $greet
    again to double-dip.
    """
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    if "greet" in state.visit_warm_verbs:
        return state, 0
    state.visit_warm_verbs.append("greet")
    actual = _apply_credits_in_memory(state, GREET_CREDIT_DELTA)
    state.last_seen = datetime.now(timezone.utc)
    _upsert_player_fields(
        coll, channel_id, npc_stem, player_id,
        set_fields={
            "warmth_credits": state.warmth_credits,
            "warmth": str(state.warmth),
            "visit_credits_delta": state.visit_credits_delta,
            "last_seen": state.last_seen,
        },
        addtoset_fields={"visit_warm_verbs": "greet"},
    )
    return state, actual


def witness_kill(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    is_passive: bool,
    monster_stem: Optional[str] = None,
    passive_kill_penalty: Optional[dict] = None,
    collection=None,
) -> Tuple[PasserbyState, int]:
    """Apply credits to a player who killed a monster while this
    NPC was present.

    Non-passive kill: +10 credits ("you protected the clearing").
    Passive kill: ``passive_kill_penalty`` lookup keyed by
    ``monster_stem`` (with ``"*"`` fallback). If the value is the
    sentinel :data:`TIER_DROP_SENTINEL` (``"tier_drop"``), the
    player drops one full warmth tier (lands at the top of the
    next-colder tier, floored at COLD); otherwise it's a numeric
    credit delta. Default (no override) is
    :data:`WITNESS_PASSIVE_KILL_DEFAULT_CREDIT` (-10).

    Returns ``(updated_state, actual_delta_applied)``. Tier drops
    return the credit-difference they applied so the caller can
    surface "wagoneer's warmth dropped two tiers" style narration
    if desired.
    """
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    state.visit_witnessed_kill_count += 1

    if is_passive:
        penalty = _resolve_passive_penalty(
            passive_kill_penalty or {}, monster_stem
        )
        if penalty == TIER_DROP_SENTINEL:
            actual = _apply_tier_drop_in_memory(state)
        else:
            actual = _apply_credits_in_memory(state, int(penalty))
    else:
        actual = _apply_credits_in_memory(state, WITNESS_NON_PASSIVE_KILL_CREDIT)

    state.last_seen = datetime.now(timezone.utc)
    _upsert_player_fields(
        coll, channel_id, npc_stem, player_id,
        set_fields={
            "warmth_credits": state.warmth_credits,
            "warmth": str(state.warmth),
            "visit_witnessed_kill_count": state.visit_witnessed_kill_count,
            "visit_credits_delta": state.visit_credits_delta,
            "last_seen": state.last_seen,
        },
    )
    return state, actual


def _resolve_passive_penalty(
    penalty_map: dict,
    monster_stem: Optional[str],
) -> Union[int, str]:
    """Look up the passive-kill penalty for this monster stem.
    Per-monster entry wins; ``"*"`` is the wildcard fallback;
    final fallback is the system-wide default credit penalty.
    """
    if monster_stem and monster_stem in penalty_map:
        return penalty_map[monster_stem]
    if "*" in penalty_map:
        return penalty_map["*"]
    return WITNESS_PASSIVE_KILL_DEFAULT_CREDIT


def _apply_tier_drop_in_memory(state: PasserbyState) -> int:
    """Drop the player's warmth one tier: land at the TOP of the
    next-colder tier so the player keeps room within the new tier
    rather than collapsing to its floor. Floors at COLD.

    Tier drops bypass the per-visit clamp — they're a punctual
    consequence ("you killed a sheep in front of the shepherd"),
    not a slow accumulation, and the sentinel exists precisely
    because the user wanted a sharp moment. The per-visit
    delta accumulator still records the magnitude so subsequent
    in-visit credit changes don't compound on top.
    """
    current_idx = _warmth_index(state.warmth)
    if current_idx == 0:  # already COLD
        return 0
    next_tier = _WARMTH_LADDER[current_idx - 1]
    # Top of the next-colder tier = high boundary of that tier
    # in WARMTH_TIERS.
    target_credits = next(
        hi for tier, lo, hi in WARMTH_TIERS if tier == next_tier
    )
    actual = target_credits - state.warmth_credits
    state.warmth_credits = target_credits
    state.visit_credits_delta += actual
    state._recompute_warmth()
    return actual


# ---------------------------------------------------------------------------
# Per-visit lifecycle hooks — fired by the spawn pipeline on
# arrival and depart
# ---------------------------------------------------------------------------

def mark_visit_arrival(
    channel_id: int,
    npc_stem: str,
    *,
    collection=None,
) -> int:
    """Reset per-visit interaction tracking on every existing
    player slice for this NPC. Captures ``tier_at_visit_start``
    fresh from the player's current credits so the per-visit
    one-tier-shift clamp is anchored to "where the player was
    when the NPC walked in" rather than "where they were when
    they last interacted."

    Returns the count of slices reset (for tests / inspection).
    Players who've never interacted with this NPC have no slice
    and are unaffected.
    """
    coll = collection if collection is not None else DB._passerby_state
    doc = coll.find_one(_npc_key(channel_id, npc_stem))
    if not doc:
        return 0
    players = doc.get("players") or {}
    if not players:
        return 0

    now = datetime.now(timezone.utc)
    operations = []
    for pid_str, slice_data in players.items():
        try:
            player_id = int(pid_str)
        except (TypeError, ValueError):
            continue
        state = PasserbyState.from_slice_doc(
            slice_data,
            channel_id=channel_id,
            npc_stem=npc_stem,
            player_id=player_id,
        )
        state.visit_arrived_at = now
        state.tier_at_visit_start = state.warmth
        state.visit_warm_verbs = []
        state.visit_cold_verbs = []
        state.visit_witnessed_kill_count = 0
        state.visit_credits_delta = 0
        state.last_seen = now
        operations.append(UpdateOne(
            _npc_key(channel_id, npc_stem),
            {"$set": {_player_slice_path(player_id): state.to_slice_doc()}},
            upsert=True,
        ))

    for op in operations:
        DB._queues[coll].put(op)
    return len(operations)


def mark_visit_depart(
    channel_id: int,
    npc_stem: str,
    *,
    apply_decay: bool = True,
    collection=None,
) -> int:
    """End-of-visit hook: apply decay to every player slice that
    saw the NPC visit but didn't interact at all this visit.

    Players who DID interact (any verb, any witnessed kill) reset
    the visit-tracking fields without applying decay. Players who
    didn't interact get -1 credit applied (per
    :data:`DECAY_PER_NO_INTERACTION_DEPART`), capped at the COLD
    floor so a long absence can't drop someone below COLD.

    ``apply_decay=False`` (used by :func:`flee_from_attack`) skips
    the no-interaction decay — the visit was cut short by another
    player's hostile action, not by a player snubbing the NPC, so
    bystanders don't get punished for an early end.

    Returns the count of slices that received decay (for
    inspection).
    """
    coll = collection if collection is not None else DB._passerby_state
    doc = coll.find_one(_npc_key(channel_id, npc_stem))
    if not doc:
        return 0
    players = doc.get("players") or {}
    if not players:
        return 0

    now = datetime.now(timezone.utc)
    decayed = 0
    operations = []
    for pid_str, slice_data in players.items():
        try:
            player_id = int(pid_str)
        except (TypeError, ValueError):
            continue
        state = PasserbyState.from_slice_doc(
            slice_data,
            channel_id=channel_id,
            npc_stem=npc_stem,
            player_id=player_id,
        )
        if apply_decay and not state.had_interaction_this_visit():
            new_credits = max(
                WARMTH_CREDITS_FLOOR,
                state.warmth_credits + DECAY_PER_NO_INTERACTION_DEPART,
            )
            if new_credits != state.warmth_credits:
                state.warmth_credits = new_credits
                state._recompute_warmth()
                decayed += 1
        # Always reset per-visit tracking on depart so a stale
        # visit_arrived_at can't bleed into the next visit.
        state.visit_arrived_at = None
        state.visit_warm_verbs = []
        state.visit_cold_verbs = []
        state.visit_witnessed_kill_count = 0
        state.visit_credits_delta = 0
        state.last_seen = now
        operations.append(UpdateOne(
            _npc_key(channel_id, npc_stem),
            {"$set": {_player_slice_path(player_id): state.to_slice_doc()}},
            upsert=True,
        ))

    for op in operations:
        DB._queues[coll].put(op)
    return decayed


def _warmth_index(warmth: Warmth) -> int:
    """Position on the ladder. Falls through to NEUTRAL for any
    parse failure — defensive against stale documents that
    somehow have an unrecognized warmth value."""
    try:
        return _WARMTH_LADDER.index(warmth)
    except ValueError:
        return _WARMTH_LADDER.index(Warmth.NEUTRAL)
