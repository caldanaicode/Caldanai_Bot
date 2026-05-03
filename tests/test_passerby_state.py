"""Tests for ``caldanai.lib.rpg.creatures.passersby.state``.

Covers the per-(channel, NPC, player) state machine — warmth
ladder steps, acquaintance via the three learning events, met-
count accumulation, and the osmosis auto-promotion rule.

Mock collection stands in for MongoDB so the logic is verified
without a live DB. The state module's helpers all accept a
``collection`` keyword for this — production binding falls
through to ``DB._passerby_state``.
"""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.creatures.passersby.state import (
    PasserbyState,
    _OSMOSIS_MET_COUNT,
    degrade_warmth,
    get_state,
    mark_acquainted,
    mark_encounter,
    promote_warmth,
    set_warmth,
)
from caldanai.lib.rpg.helpers.warmth import Warmth


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


class _FakeCollection:
    """In-memory collection that mimics the subset of pymongo's
    Collection API the state module uses (``find_one`` for
    reads). Writes go through ``DB._queues[coll].put`` which we
    patch separately to capture the queued operations."""

    def __init__(self):
        self._docs: list = []

    def find_one(self, filter_):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in filter_.items()):
                return doc
        return None

    def insert(self, doc: dict):
        """Test-only helper to seed the collection with prior state."""
        self._docs.append(doc)

    def upsert(self, key: dict, set_fields: dict):
        """Apply an upsert in the way the state module expects.
        Mimics the queue's eventual-write effect."""
        existing = self.find_one(key)
        if existing:
            existing.update(set_fields)
        else:
            new_doc = {**key, **set_fields}
            self._docs.append(new_doc)


@pytest.fixture
def coll():
    return _FakeCollection()


@pytest.fixture
def queues_patch(coll):
    """Patch DB._queues so writes apply to the FakeCollection
    directly (synchronous) rather than queueing for a background
    flush. Lets tests assert state changes immediately."""
    captured: list = []

    class _FakeQueue:
        def put(self, op):
            # ``op`` is a pymongo ``UpdateOne``. Extract the filter
            # + $set fields and apply them to the fake collection.
            captured.append(op)
            filt = op._filter
            update = op._doc
            set_fields = update.get("$set", {})
            coll.upsert(filt, set_fields)

    fake_queues = {coll: _FakeQueue()}

    # ``defaultdict``-shape: any new key gets a fresh _FakeQueue.
    class _FakeQueuesDict(dict):
        def __missing__(self, key):
            q = _FakeQueue()
            self[key] = q
            return q

    fq = _FakeQueuesDict(fake_queues)

    with patch("caldanai.lib.rpg.creatures.passersby.state.DB") as mock_db:
        mock_db._passerby_state = coll
        mock_db._queues = fq
        yield captured


# ---------------------------------------------------------------------------
# get_state — initial / cached reads
# ---------------------------------------------------------------------------


class TestGetState:
    def test_no_doc_returns_default(self, coll):
        state = get_state(123, "wagoneer", 999, collection=coll)
        assert state.channel_id == 123
        assert state.npc_stem == "wagoneer"
        assert state.player_id == 999
        assert state.warmth == Warmth.NEUTRAL
        assert state.acquainted is False
        assert state.met_count == 0

    def test_existing_doc_hydrates_state(self, coll):
        coll.insert({
            "channel_id": 123,
            "npc_stem": "herbalist",
            "player_id": 999,
            "warmth": "warm",
            "acquainted": True,
            "acquainted_via": "greet",
            "met_count": 5,
        })
        state = get_state(123, "herbalist", 999, collection=coll)
        assert state.warmth == Warmth.WARM
        assert state.acquainted is True
        assert state.acquainted_via == "greet"
        assert state.met_count == 5

    def test_npc_stem_lowercased(self, coll):
        """Lookup is case-insensitive on stem so callers don't
        have to normalize."""
        coll.insert({
            "channel_id": 1, "npc_stem": "wren", "player_id": 1,
            "warmth": "hot",
        })
        state = get_state(1, "WREN", 1, collection=coll)
        assert state.warmth == Warmth.HOT


# ---------------------------------------------------------------------------
# mark_encounter — increments + osmosis promotion
# ---------------------------------------------------------------------------


class TestMarkEncounter:
    def test_first_encounter_starts_at_one(self, coll, queues_patch):
        state = mark_encounter(123, "wagoneer", 999, collection=coll)
        assert state.met_count == 1

    def test_met_count_increments(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "neutral", "met_count": 2, "acquainted": False,
        })
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.met_count == 3

    def test_osmosis_at_threshold_with_neutral_warmth(self, coll, queues_patch):
        """met_count crossing the osmosis threshold with NEUTRAL+
        warmth flips acquainted automatically."""
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "neutral", "met_count": _OSMOSIS_MET_COUNT - 1,
            "acquainted": False,
        })
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.met_count == _OSMOSIS_MET_COUNT
        assert state.acquainted is True
        assert state.acquainted_via == "osmosis"

    def test_osmosis_does_not_fire_for_cool_warmth(self, coll, queues_patch):
        """A hostile (cool/cold) history doesn't earn name-knowledge
        no matter how many encounters."""
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "cool", "met_count": _OSMOSIS_MET_COUNT * 2,
            "acquainted": False,
        })
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.acquainted is False

    def test_already_acquainted_unchanged(self, coll, queues_patch):
        """If the player was acquainted via greet earlier, met_count
        increments don't overwrite the existing via-tag."""
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "warm", "met_count": 1,
            "acquainted": True, "acquainted_via": "greet",
        })
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.acquainted is True
        assert state.acquainted_via == "greet"


# ---------------------------------------------------------------------------
# mark_acquainted — explicit learning events
# ---------------------------------------------------------------------------


class TestMarkAcquainted:
    def test_flips_to_acquainted(self, coll, queues_patch):
        state = mark_acquainted(1, "wagoneer", 999, "greet", collection=coll)
        assert state.acquainted is True
        assert state.acquainted_via == "greet"

    def test_idempotent_keeps_first_via(self, coll, queues_patch):
        """Re-acquaintance preserves the FIRST via-tag — the
        original learning event is canon."""
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "neutral", "met_count": 0,
            "acquainted": True, "acquainted_via": "greet",
        })
        state = mark_acquainted(1, "wagoneer", 1, "mention", collection=coll)
        assert state.acquainted_via == "greet"  # unchanged

    def test_via_tag_persists_through_subsequent_encounters(
        self, coll, queues_patch,
    ):
        mark_acquainted(1, "wagoneer", 999, "mention", collection=coll)
        state = mark_encounter(1, "wagoneer", 999, collection=coll)
        assert state.acquainted_via == "mention"


# ---------------------------------------------------------------------------
# Warmth ladder — degrade / promote
# ---------------------------------------------------------------------------


class TestWarmthLadder:
    def test_degrade_one_step(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "warm",
        })
        state = degrade_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.NEUTRAL

    def test_degrade_floors_at_cold(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "cold",
        })
        state = degrade_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.COLD

    def test_degrade_multiple_steps(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "hot",
        })
        state = degrade_warmth(1, "wagoneer", 1, steps=3, collection=coll)
        assert state.warmth == Warmth.COOL

    def test_promote_one_step(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "cool",
        })
        state = promote_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.NEUTRAL

    def test_promote_caps_at_hot(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "hot",
        })
        state = promote_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.HOT

    def test_set_warmth_explicit(self, coll, queues_patch):
        state = set_warmth(1, "wagoneer", 999, Warmth.WARM, collection=coll)
        assert state.warmth == Warmth.WARM


# ---------------------------------------------------------------------------
# Persistence — verify upserts queued on writes
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_mark_encounter_writes_to_db(self, coll, queues_patch):
        mark_encounter(1, "wagoneer", 999, collection=coll)
        # Queue captured the UpdateOne; FakeCollection applied it.
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 999,
        })
        assert doc is not None
        assert doc["met_count"] == 1

    def test_degrade_writes_only_when_changed(self, coll, queues_patch):
        coll.insert({
            "channel_id": 1, "npc_stem": "wagoneer", "player_id": 1,
            "warmth": "cold",
        })
        ops_before = len(queues_patch)
        # Already at COLD, degrade is a no-op.
        degrade_warmth(1, "wagoneer", 1, collection=coll)
        ops_after = len(queues_patch)
        assert ops_after == ops_before  # No write queued.


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_to_doc_from_doc_idempotent(self):
        original = PasserbyState(
            channel_id=1,
            npc_stem="wagoneer",
            player_id=999,
            warmth=Warmth.WARM,
            acquainted=True,
            acquainted_via="greet",
            met_count=5,
        )
        doc = original.to_doc()
        recovered = PasserbyState.from_doc(doc)
        assert recovered.channel_id == 1
        assert recovered.npc_stem == "wagoneer"
        assert recovered.player_id == 999
        assert recovered.warmth == Warmth.WARM
        assert recovered.acquainted is True
        assert recovered.acquainted_via == "greet"
        assert recovered.met_count == 5

    def test_from_doc_tolerates_partial(self):
        """Stale docs missing fields should hydrate to dataclass
        defaults — defensive against schema evolution."""
        state = PasserbyState.from_doc({
            "channel_id": 1,
            "npc_stem": "wagoneer",
            "player_id": 1,
            # warmth, acquainted, met_count all missing
        })
        assert state.warmth == Warmth.NEUTRAL
        assert state.acquainted is False
        assert state.met_count == 0

    def test_from_doc_tolerates_unknown_warmth(self):
        """Unknown warmth value falls through to NEUTRAL rather
        than raising."""
        state = PasserbyState.from_doc({
            "channel_id": 1, "npc_stem": "x", "player_id": 1,
            "warmth": "absolutely-frigid",  # not in the enum
        })
        assert state.warmth == Warmth.NEUTRAL
