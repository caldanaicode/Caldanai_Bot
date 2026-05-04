"""Tests for ``caldanai.lib.rpg.creatures.passersby.state``.

Covers the per-(channel, NPC) document with players sub-mapping —
warmth ladder steps, acquaintance via the three learning events,
met-count accumulation, the osmosis auto-promotion rule, and the
schema-level guarantee that warmth is persisted on every write
(the bug fix that motivated the 2026-05-03 schema restructure).

Mock collection stands in for MongoDB so the logic is verified
without a live DB. The state module's helpers all accept a
``collection`` keyword for this — production binding falls
through to ``DB._passerby_state``.

Schema reminder (post-restructure):

.. code-block:: python

    {
        "channel_id":  1234,
        "npc_stem":    "shepherd",
        "players": {
            "999": {
                "warmth": "warm",
                "acquainted": true,
                ...
            },
        },
    }
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
    Collection API the state module uses (``find_one`` for reads).
    Writes go through ``DB._queues[coll].put`` which we patch
    separately to capture the queued operations.

    The upsert helper handles dotted-path ``$set`` keys (e.g.
    ``players.999``) — splits on the first dot and writes into
    the nested sub-dict, creating it if missing. This matches the
    new state-module behavior of writing per-player slices via
    ``$set: {f"players.{pid}": <slice>}``.
    """

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
        Mimics the queue's eventual-write effect, including the
        Mongo dotted-path semantics for nested writes."""
        existing = self.find_one(key)
        if existing is None:
            existing = {**key}
            self._docs.append(existing)
        for path, value in set_fields.items():
            self._apply_dotted_set(existing, path, value)

    @staticmethod
    def _apply_dotted_set(doc: dict, path: str, value) -> None:
        """Set a value at a possibly-dotted path. ``"a.b.c" = v``
        becomes ``doc["a"]["b"]["c"] = v`` with intermediate dicts
        created as needed."""
        parts = path.split(".")
        target = doc
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value


def _seed_player_slice(coll: _FakeCollection, channel_id, npc_stem, player_id, **slice_fields):
    """Helper: seed a per-(channel, npc) doc with a single player
    slice. Tests use this to set up prior state for verifying
    mutator behavior."""
    coll.insert({
        "channel_id": channel_id,
        "npc_stem": npc_stem,
        "players": {str(player_id): dict(slice_fields)},
    })


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

    def test_doc_exists_but_no_player_slice_returns_default(self, coll):
        """The NPC has been encountered by other players, but THIS
        player has no slice yet — should return a default state,
        not error or hydrate from someone else's slice."""
        coll.insert({
            "channel_id": 1, "npc_stem": "shepherd",
            "players": {"42": {"warmth": "warm", "acquainted": True}},
        })
        state = get_state(1, "shepherd", 999, collection=coll)
        assert state.warmth == Warmth.NEUTRAL
        assert state.acquainted is False
        assert state.met_count == 0

    def test_existing_player_slice_hydrates_state(self, coll):
        _seed_player_slice(
            coll, 123, "herbalist", 999,
            warmth="warm",
            acquainted=True,
            acquainted_via="greet",
            met_count=5,
        )
        state = get_state(123, "herbalist", 999, collection=coll)
        assert state.warmth == Warmth.WARM
        assert state.acquainted is True
        assert state.acquainted_via == "greet"
        assert state.met_count == 5

    def test_npc_stem_lowercased(self, coll):
        """Lookup is case-insensitive on stem so callers don't
        have to normalize."""
        _seed_player_slice(coll, 1, "wren", 1, warmth="hot")
        state = get_state(1, "WREN", 1, collection=coll)
        assert state.warmth == Warmth.HOT

    def test_one_npc_doc_can_hold_multiple_player_slices(self, coll):
        """Two players, same shepherd, distinct relationships."""
        coll.insert({
            "channel_id": 1, "npc_stem": "shepherd",
            "players": {
                "100": {"warmth": "warm", "acquainted": True},
                "200": {"warmth": "cool", "acquainted": False},
            },
        })
        state_a = get_state(1, "shepherd", 100, collection=coll)
        state_b = get_state(1, "shepherd", 200, collection=coll)
        assert state_a.warmth == Warmth.WARM
        assert state_a.acquainted is True
        assert state_b.warmth == Warmth.COOL
        assert state_b.acquainted is False


# ---------------------------------------------------------------------------
# mark_encounter — increments + osmosis promotion
# ---------------------------------------------------------------------------


class TestMarkEncounter:
    def test_first_encounter_starts_at_one(self, coll, queues_patch):
        state = mark_encounter(123, "wagoneer", 999, collection=coll)
        assert state.met_count == 1

    def test_met_count_increments(self, coll, queues_patch):
        _seed_player_slice(
            coll, 1, "wagoneer", 1,
            warmth="neutral", met_count=2, acquainted=False,
        )
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.met_count == 3

    def test_osmosis_at_threshold_with_neutral_warmth(self, coll, queues_patch):
        """met_count crossing the osmosis threshold with NEUTRAL+
        warmth flips acquainted automatically."""
        _seed_player_slice(
            coll, 1, "wagoneer", 1,
            warmth="neutral",
            met_count=_OSMOSIS_MET_COUNT - 1,
            acquainted=False,
        )
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.met_count == _OSMOSIS_MET_COUNT
        assert state.acquainted is True
        assert state.acquainted_via == "osmosis"

    def test_osmosis_does_not_fire_for_cool_warmth(self, coll, queues_patch):
        """A hostile (cool/cold) history doesn't earn name-knowledge
        no matter how many encounters."""
        _seed_player_slice(
            coll, 1, "wagoneer", 1,
            warmth="cool",
            met_count=_OSMOSIS_MET_COUNT * 2,
            acquainted=False,
        )
        state = mark_encounter(1, "wagoneer", 1, collection=coll)
        assert state.acquainted is False

    def test_already_acquainted_unchanged(self, coll, queues_patch):
        """If the player was acquainted via greet earlier, met_count
        increments don't overwrite the existing via-tag."""
        _seed_player_slice(
            coll, 1, "wagoneer", 1,
            warmth="warm",
            met_count=1,
            acquainted=True,
            acquainted_via="greet",
        )
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
        _seed_player_slice(
            coll, 1, "wagoneer", 1,
            warmth="neutral",
            met_count=0,
            acquainted=True,
            acquainted_via="greet",
        )
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
        _seed_player_slice(coll, 1, "wagoneer", 1, warmth="warm")
        state = degrade_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.NEUTRAL

    def test_degrade_floors_at_cold(self, coll, queues_patch):
        _seed_player_slice(coll, 1, "wagoneer", 1, warmth="cold")
        state = degrade_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.COLD

    def test_degrade_multiple_steps(self, coll, queues_patch):
        _seed_player_slice(coll, 1, "wagoneer", 1, warmth="hot")
        state = degrade_warmth(1, "wagoneer", 1, steps=3, collection=coll)
        assert state.warmth == Warmth.COOL

    def test_promote_one_step(self, coll, queues_patch):
        _seed_player_slice(coll, 1, "wagoneer", 1, warmth="cool")
        state = promote_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.NEUTRAL

    def test_promote_caps_at_hot(self, coll, queues_patch):
        _seed_player_slice(coll, 1, "wagoneer", 1, warmth="hot")
        state = promote_warmth(1, "wagoneer", 1, collection=coll)
        assert state.warmth == Warmth.HOT

    def test_set_warmth_explicit(self, coll, queues_patch):
        state = set_warmth(1, "wagoneer", 999, Warmth.WARM, collection=coll)
        assert state.warmth == Warmth.WARM


# ---------------------------------------------------------------------------
# Persistence — verify upserts queued on writes + warmth lands every time
# ---------------------------------------------------------------------------


class TestPersistence:
    def test_mark_encounter_writes_to_db(self, coll, queues_patch):
        mark_encounter(1, "wagoneer", 999, collection=coll)
        # Queue captured the UpdateOne; FakeCollection applied it.
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        assert doc is not None
        assert doc["players"]["999"]["met_count"] == 1

    def test_warmth_persisted_on_first_encounter(self, coll, queues_patch):
        """Bug-fix verification (2026-05-03 schema restructure):
        warmth must land in the doc on the FIRST write, not only
        when set_warmth/degrade/promote is called explicitly. The
        previous schema persisted only met_count + acquainted +
        last_seen on mark_encounter, leaving warmth as the in-
        memory default that never reached disk."""
        mark_encounter(1, "wagoneer", 999, collection=coll)
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        assert doc is not None
        slice_data = doc["players"]["999"]
        assert "warmth" in slice_data
        assert slice_data["warmth"] == str(Warmth.NEUTRAL)

    def test_warmth_persisted_on_mark_acquainted(self, coll, queues_patch):
        """Same bug-fix: mark_acquainted must persist warmth too."""
        mark_acquainted(1, "wagoneer", 999, "greet", collection=coll)
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        slice_data = doc["players"]["999"]
        assert "warmth" in slice_data
        assert slice_data["warmth"] == str(Warmth.NEUTRAL)

    def test_full_slice_persisted_on_every_write(self, coll, queues_patch):
        """Every persisted slice should contain ALL the fields the
        dataclass declares — no partial-write surprises during
        Mongo-Compass inspection."""
        mark_encounter(1, "wagoneer", 999, collection=coll)
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        slice_data = doc["players"]["999"]
        for required in (
            "warmth", "acquainted", "acquainted_via", "met_count",
            "first_met", "last_seen",
        ):
            assert required in slice_data, f"missing {required}"

    def test_two_players_same_npc_share_one_doc(self, coll, queues_patch):
        """Three players acquainted with the shepherd should be
        ONE shepherd doc with three player slices, not three
        shepherd docs."""
        mark_encounter(1, "shepherd", 100, collection=coll)
        mark_encounter(1, "shepherd", 200, collection=coll)
        mark_encounter(1, "shepherd", 300, collection=coll)
        # Find ALL shepherd docs in this channel.
        shepherd_docs = [
            d for d in coll._docs
            if d.get("channel_id") == 1 and d.get("npc_stem") == "shepherd"
        ]
        assert len(shepherd_docs) == 1
        assert set(shepherd_docs[0]["players"].keys()) == {"100", "200", "300"}

    def test_concurrent_player_writes_dont_clobber(self, coll, queues_patch):
        """Per-player atomic $set means player A's write doesn't
        overwrite player B's slice. After mixed writes both players
        read back the values they wrote."""
        set_warmth(1, "shepherd", 100, Warmth.WARM, collection=coll)
        set_warmth(1, "shepherd", 200, Warmth.COOL, collection=coll)
        # After both writes, both slices intact.
        a = get_state(1, "shepherd", 100, collection=coll)
        b = get_state(1, "shepherd", 200, collection=coll)
        assert a.warmth == Warmth.WARM
        assert b.warmth == Warmth.COOL

    def test_degrade_writes_only_when_changed(self, coll, queues_patch):
        _seed_player_slice(coll, 1, "wagoneer", 1, warmth="cold")
        ops_before = len(queues_patch)
        # Already at COLD, degrade is a no-op.
        degrade_warmth(1, "wagoneer", 1, collection=coll)
        ops_after = len(queues_patch)
        assert ops_after == ops_before  # No write queued.


# ---------------------------------------------------------------------------
# Schema round-trip
# ---------------------------------------------------------------------------


class TestSchemaRoundTrip:
    def test_to_slice_doc_from_slice_doc_idempotent(self):
        original = PasserbyState(
            channel_id=1,
            npc_stem="wagoneer",
            player_id=999,
            warmth=Warmth.WARM,
            acquainted=True,
            acquainted_via="greet",
            met_count=5,
        )
        slice_data = original.to_slice_doc()
        recovered = PasserbyState.from_slice_doc(
            slice_data,
            channel_id=1,
            npc_stem="wagoneer",
            player_id=999,
        )
        assert recovered.channel_id == 1
        assert recovered.npc_stem == "wagoneer"
        assert recovered.player_id == 999
        assert recovered.warmth == Warmth.WARM
        assert recovered.acquainted is True
        assert recovered.acquainted_via == "greet"
        assert recovered.met_count == 5

    def test_to_slice_doc_omits_identity_triple(self):
        """The persisted slice doesn't carry its own channel/npc/
        player keys — those live in the parent doc + sub-mapping
        key. Embedding them on the slice would be redundant data
        that could drift out of sync with the keying."""
        state = PasserbyState(
            channel_id=1, npc_stem="wagoneer", player_id=999,
            warmth=Warmth.WARM,
        )
        slice_data = state.to_slice_doc()
        assert "channel_id" not in slice_data
        assert "npc_stem" not in slice_data
        assert "player_id" not in slice_data
        assert slice_data["warmth"] == str(Warmth.WARM)

    def test_from_slice_doc_tolerates_partial(self):
        """Stale slices missing fields should hydrate to dataclass
        defaults — defensive against schema evolution."""
        state = PasserbyState.from_slice_doc(
            {},
            channel_id=1, npc_stem="wagoneer", player_id=1,
        )
        assert state.warmth == Warmth.NEUTRAL
        assert state.acquainted is False
        assert state.met_count == 0

    def test_from_slice_doc_tolerates_unknown_warmth(self):
        """Unknown warmth value falls through to NEUTRAL rather
        than raising."""
        state = PasserbyState.from_slice_doc(
            {"warmth": "absolutely-frigid"},  # not in the enum
            channel_id=1, npc_stem="x", player_id=1,
        )
        assert state.warmth == Warmth.NEUTRAL
