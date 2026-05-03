"""Per-channel passerby NPC state — warmth, acquaintance, and
encounter accumulation, persisted to MongoDB.

Schema
------

One document per ``(channel_id, npc_stem, player_id)`` triple:

.. code-block:: python

    {
        "channel_id":     <int>,           # Discord channel where this state lives
        "npc_stem":       <str>,           # plugin filename stem ("wagoneer", "wren", ...)
        "player_id":      <int>,           # Discord user_id of the player
        "warmth":         <str>,           # Warmth enum value
        "acquainted":     <bool>,          # NPC knows what to call this player
        "acquainted_via": <str | None>,    # "greet" | "mention" | "osmosis"
        "met_count":      <int>,           # encounters total on this channel
        "first_met":      <datetime>,
        "last_seen":      <datetime>,
    }

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
    """In-memory representation of a per-(channel, npc, player)
    state document. Defaults match a "first encounter" record:
    NEUTRAL warmth, not acquainted, met_count 0."""

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

    def to_doc(self) -> dict:
        """Serialize to a dict ready for MongoDB upsert. Warmth
        enum gets stored as its string value so the document
        stays portable."""
        d = asdict(self)
        d["warmth"] = str(self.warmth)
        return d

    @classmethod
    def from_doc(cls, doc: dict) -> "PasserbyState":
        """Inverse of :meth:`to_doc`. Tolerant of stale / partial
        documents — missing fields fall back to dataclass defaults
        rather than raising. Defensive against schema evolution."""
        return cls(
            channel_id=doc.get("channel_id", 0),
            npc_stem=doc.get("npc_stem", ""),
            player_id=doc.get("player_id", 0),
            warmth=Warmth.from_str(doc.get("warmth")) or Warmth.NEUTRAL,
            acquainted=bool(doc.get("acquainted", False)),
            acquainted_via=doc.get("acquainted_via"),
            met_count=int(doc.get("met_count", 0)),
            first_met=doc.get("first_met") or datetime.now(timezone.utc),
            last_seen=doc.get("last_seen") or datetime.now(timezone.utc),
        )


def _key(channel_id: int, npc_stem: str, player_id: int) -> dict:
    """Compound key for find / upsert."""
    return {
        "channel_id": int(channel_id),
        "npc_stem": str(npc_stem).lower(),
        "player_id": int(player_id),
    }


def get_state(
    channel_id: int,
    npc_stem: str,
    player_id: int,
    *,
    collection=None,
) -> PasserbyState:
    """Fetch the state document for this triple. Returns a fresh
    default-shaped :class:`PasserbyState` if no document exists
    yet — callers don't have to handle the missing-doc case
    separately, just read fields off the dataclass.
    """
    coll = collection if collection is not None else DB._passerby_state
    doc = coll.find_one(_key(channel_id, npc_stem, player_id))
    if doc:
        return PasserbyState.from_doc(doc)
    return PasserbyState(
        channel_id=int(channel_id),
        npc_stem=str(npc_stem).lower(),
        player_id=int(player_id),
    )


def _upsert(coll, key: dict, set_fields: dict) -> None:
    """Queue an upsert via the existing DB write-buffer pattern.

    Direct ``UpdateOne`` (not bulk) since each per-encounter
    update is independent and we want low-latency persistence
    rather than batched commits. The DB module's queue
    machinery handles retries / connection-failure backoff
    transparently for us.
    """
    set_fields.setdefault("last_seen", datetime.now(timezone.utc))
    DB._queues[coll].put(
        UpdateOne(key, {"$set": set_fields}, upsert=True)
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

    set_fields = {
        "met_count": state.met_count,
        "last_seen": state.last_seen,
        "acquainted": state.acquainted,
        "acquainted_via": state.acquainted_via,
    }
    # Set first_met only on the very first encounter (when the
    # in-memory default == post-increment-by-one). Use upsert
    # so the field lands once and isn't overwritten thereafter.
    if state.met_count == 1:
        set_fields["first_met"] = state.first_met
    _upsert(coll, _key(channel_id, npc_stem, player_id), set_fields)
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
    _upsert(
        coll,
        _key(channel_id, npc_stem, player_id),
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
    """Set warmth to a specific tier. Used by tests / admin
    overrides; gameplay normally goes through :func:`degrade_warmth`
    or :func:`promote_warmth` which step the ladder."""
    coll = collection if collection is not None else DB._passerby_state
    state = get_state(channel_id, npc_stem, player_id, collection=coll)
    state.warmth = warmth
    state.last_seen = datetime.now(timezone.utc)
    _upsert(
        coll,
        _key(channel_id, npc_stem, player_id),
        {
            "warmth": str(warmth),
            "last_seen": state.last_seen,
        },
    )
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
        _upsert(
            coll,
            _key(channel_id, npc_stem, player_id),
            {
                "warmth": str(new_warmth),
                "last_seen": state.last_seen,
            },
        )
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
        _upsert(
            coll,
            _key(channel_id, npc_stem, player_id),
            {
                "warmth": str(new_warmth),
                "last_seen": state.last_seen,
            },
        )
    return state


def _warmth_index(warmth: Warmth) -> int:
    """Position on the ladder. Falls through to NEUTRAL for any
    parse failure — defensive against stale documents that
    somehow have an unrecognized warmth value."""
    try:
        return _WARMTH_LADDER.index(warmth)
    except ValueError:
        return _WARMTH_LADDER.index(Warmth.NEUTRAL)
