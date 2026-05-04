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
                "warmth":         <str>,         # Warmth enum value, always present
                "acquainted":     <bool>,        # NPC knows what to call this player
                "acquainted_via": <str | None>,  # "greet" | "mention" | "osmosis"
                "met_count":      <int>,         # encounters total on this channel
                "first_met":      <datetime>,
                "last_seen":      <datetime>,
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

Tested with :class:`unittest.mock.MagicMock` standing in for the
DB collection so the per-channel logic is verifiable without a
live Mongo. The default :class:`DB._passerby_state` accessor is
the production binding; ``collection`` parameter on each function
overrides for tests.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

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


@dataclass
class PasserbyState:
    """In-memory representation of a single per-(channel, npc, player)
    relationship slice. Defaults match a "first encounter" record:
    NEUTRAL warmth, not acquainted, met_count 0.

    The dataclass carries the channel/npc/player triple even though
    the persisted slice doesn't store them — those identify *which*
    slice the in-memory state belongs to, but they're keyed via
    the parent doc + sub-mapping key on disk."""

    channel_id: int
    npc_stem: str
    player_id: int
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

    def to_slice_doc(self) -> dict:
        """Serialize the persistable slice (per-player fields only).
        Channel / NPC / player triple is identified by parent doc +
        sub-mapping key, not embedded in the slice itself."""
        d = asdict(self)
        d["warmth"] = str(self.warmth)
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
        defaults rather than raising."""
        return cls(
            channel_id=int(channel_id),
            npc_stem=str(npc_stem).lower(),
            player_id=int(player_id),
            warmth=Warmth.from_str(slice_data.get("warmth")) or Warmth.NEUTRAL,
            acquainted=bool(slice_data.get("acquainted", False)),
            acquainted_via=slice_data.get("acquainted_via"),
            met_count=int(slice_data.get("met_count", 0)),
            first_met=slice_data.get("first_met") or datetime.now(timezone.utc),
            last_seen=slice_data.get("last_seen") or datetime.now(timezone.utc),
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

    Writes the FULL slice (every field on the dataclass) every
    time — guarantees that warmth, acquaintance, met_count, etc.
    all stay in sync between memory and disk. Per-player atomicity
    via dotted-path ``$set`` means concurrent writes for different
    players (player A waving while player B greets) don't clobber
    each other's slices.

    The DB queue machinery handles retries / connection-failure
    backoff transparently for us.
    """
    state.last_seen = state.last_seen or datetime.now(timezone.utc)
    DB._queues[coll].put(
        UpdateOne(
            _npc_key(channel_id, npc_stem),
            {"$set": {_player_slice_path(player_id): state.to_slice_doc()}},
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

    _upsert_player_slice(coll, channel_id, npc_stem, player_id, state)
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
    _upsert_player_slice(coll, channel_id, npc_stem, player_id, state)
    return state


def set_warmth(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    warmth: Warmth,
    *,
    collection=None,
) -> PasserbyState:
    """Set warmth to a specific tier. Used by tests / admin
    overrides; gameplay normally goes through :func:`degrade_warmth`
    or :func:`promote_warmth` which step the ladder."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    state.warmth = warmth
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
    """Drop warmth ``steps`` tiers along the ladder
    ``hot > warm > neutral > cool > cold``. Floors at COLD —
    repeated attacks on a cold-warmth NPC don't go below cold;
    the consequence space lives in *whether* they return at all
    (handled by the spawn pipeline reading the warmth state)."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    new_idx = max(0, _warmth_index(state.warmth) - steps)
    new_warmth = _WARMTH_LADDER[new_idx]
    if new_warmth != state.warmth:
        state.warmth = new_warmth
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
    """Raise warmth ``steps`` tiers along the ladder. Caps at HOT.
    Future hook for sustained-friendliness or in-fiction kindness
    earning warmth; not used in V1 yet."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    new_idx = min(len(_WARMTH_LADDER) - 1, _warmth_index(state.warmth) + steps)
    new_warmth = _WARMTH_LADDER[new_idx]
    if new_warmth != state.warmth:
        state.warmth = new_warmth
        state.last_seen = datetime.now(timezone.utc)
        _upsert_player_slice(coll, channel_id, npc_stem, player_id, state)
    return state


def _warmth_index(warmth: Warmth) -> int:
    """Position on the ladder. Falls through to NEUTRAL for any
    parse failure — defensive against stale documents that
    somehow have an unrecognized warmth value."""
    try:
        return _WARMTH_LADDER.index(warmth)
    except ValueError:
        return _WARMTH_LADDER.index(Warmth.NEUTRAL)
