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

    def upsert(self, key: dict, set_fields: dict, addtoset_fields: dict = None):
        """Apply an upsert in the way the state module expects.
        Mimics the queue's eventual-write effect, including the
        Mongo dotted-path semantics for nested writes and
        ``$addToSet`` semantics for unique-append into list fields.
        """
        existing = self.find_one(key)
        if existing is None:
            existing = {**key}
            self._docs.append(existing)
        for path, value in (set_fields or {}).items():
            self._apply_dotted_set(existing, path, value)
        for path, value in (addtoset_fields or {}).items():
            self._apply_dotted_addtoset(existing, path, value)

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

    @staticmethod
    def _apply_dotted_addtoset(doc: dict, path: str, value) -> None:
        """Append ``value`` to the list at ``path`` if not already
        present. Mirrors Mongo's ``$addToSet`` semantics. Creates
        intermediate dicts and the target list as needed."""
        parts = path.split(".")
        target = doc
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        existing = target.setdefault(parts[-1], [])
        if value not in existing:
            existing.append(value)


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
            # + $set / $addToSet fields and apply them to the fake
            # collection.
            captured.append(op)
            filt = op._filter
            update = op._doc
            set_fields = update.get("$set", {})
            addtoset_fields = update.get("$addToSet", {})
            coll.upsert(filt, set_fields, addtoset_fields)

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

    def test_mark_encounter_writes_only_its_own_fields(
        self, coll, queues_patch,
    ):
        """Per-field write contract: ``mark_encounter`` only touches
        ``met_count`` and ``last_seen`` (plus acquainted/via on
        osmosis flip). It must NOT write ``warmth`` or other fields
        — that's the whole point of the per-field refactor: leave
        sibling fields intact so concurrent helpers don't clobber
        each other.

        Inspection-via-Compass concern (the original bug from the
        2026-05-03 schema restructure) is addressed differently
        now: ``from_slice_doc`` fills missing fields with sensible
        defaults, so a partial slice still hydrates to a coherent
        in-memory state. Lifecycle hooks (mark_visit_arrival /
        mark_visit_depart / set_warmth) write the full slice and
        keep on-disk slices uniform after any visit cycle."""
        mark_encounter(1, "wagoneer", 999, collection=coll)
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        assert doc is not None
        slice_data = doc["players"]["999"]
        assert slice_data["met_count"] == 1
        assert "warmth" not in slice_data
        assert "warmth_credits" not in slice_data
        # Sibling field-write happens during osmosis flip
        # specifically — first encounter (met_count=1) doesn't
        # trigger it.
        assert "acquainted" not in slice_data

    def test_mark_acquainted_writes_only_its_own_fields(
        self, coll, queues_patch,
    ):
        mark_acquainted(1, "wagoneer", 999, "greet", collection=coll)
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        slice_data = doc["players"]["999"]
        assert slice_data["acquainted"] is True
        assert slice_data["acquainted_via"] == "greet"
        # Did NOT touch met_count or warmth — those belong to other
        # mutators and stay independent.
        assert "met_count" not in slice_data
        assert "warmth" not in slice_data

    def test_partial_slice_hydrates_with_defaults(
        self, coll, queues_patch,
    ):
        """A field-by-field-built slice can be missing fields the
        dataclass declares; ``from_slice_doc`` MUST fill defaults
        so the in-memory state is coherent even when the on-disk
        doc is partial."""
        mark_encounter(1, "wagoneer", 999, collection=coll)
        # Round-trip through get_state — should fill missing
        # warmth_credits / warmth / etc. with defaults.
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.met_count == 1
        assert state.warmth == Warmth.NEUTRAL
        assert state.warmth_credits == 0
        assert state.acquainted is False
        assert state.acquainted_via is None

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
        # warmth is now derived from warmth_credits — set credits
        # within the WARM band (20..39) so the recomputed tier
        # lands at WARM.
        original = PasserbyState(
            channel_id=1,
            npc_stem="wagoneer",
            player_id=999,
            warmth_credits=25,
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
        assert recovered.warmth_credits == 25
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
            warmth_credits=25,  # WARM band
        )
        slice_data = state.to_slice_doc()
        assert "channel_id" not in slice_data
        assert "npc_stem" not in slice_data
        assert "player_id" not in slice_data
        assert slice_data["warmth"] == str(Warmth.WARM)
        assert slice_data["warmth_credits"] == 25

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


# ---------------------------------------------------------------------------
# Warmth credits — tier derivation, drop-tier, per-visit clamp, decay
# ---------------------------------------------------------------------------


from caldanai.lib.rpg.creatures.passersby.state import (
    apply_greet_credits,
    apply_verb_credits,
    mark_visit_arrival,
    mark_visit_depart,
    warmth_from_credits,
    witness_kill,
    GREET_CREDIT_DELTA,
    WITNESS_NON_PASSIVE_KILL_CREDIT,
    WITNESS_PASSIVE_KILL_DEFAULT_CREDIT,
    DECAY_STEP_TOWARD_NEUTRAL,
    TIER_DROP_SENTINEL,
)


class TestWarmthFromCredits:
    """Tier mapping must match the documented credit bands so
    everything else (per-visit clamp, drop_tier, set_warmth) lands
    on intuitive boundaries."""

    @pytest.mark.parametrize("credits,expected", [
        (-100, Warmth.COLD),
        (-50, Warmth.COLD),
        (-40, Warmth.COLD),
        (-39, Warmth.COOL),
        (-25, Warmth.COOL),
        (-20, Warmth.COOL),
        (-19, Warmth.NEUTRAL),
        (0, Warmth.NEUTRAL),
        (19, Warmth.NEUTRAL),
        (20, Warmth.WARM),
        (25, Warmth.WARM),
        (39, Warmth.WARM),
        (40, Warmth.HOT),
        (50, Warmth.HOT),
        (100, Warmth.HOT),
    ])
    def test_tier_boundaries(self, credits, expected):
        assert warmth_from_credits(credits) == expected

    def test_out_of_band_above_clamps_to_hot(self):
        # Defensive — should never happen via normal API, but
        # protects inspection tools from crashes on stale data.
        assert warmth_from_credits(500) == Warmth.HOT

    def test_out_of_band_below_clamps_to_cold(self):
        assert warmth_from_credits(-500) == Warmth.COLD


class TestPasserbyStateRecomputesWarmth:
    def test_post_init_derives_warmth_from_credits(self):
        state = PasserbyState(
            channel_id=1, npc_stem="x", player_id=1,
            warmth_credits=25,
        )
        assert state.warmth == Warmth.WARM

    def test_explicit_warmth_arg_is_overridden_by_credits(self):
        # warmth is purely derived now — passing a tier directly
        # without matching credits gets stomped by __post_init__.
        state = PasserbyState(
            channel_id=1, npc_stem="x", player_id=1,
            warmth_credits=0,  # NEUTRAL band
            warmth=Warmth.HOT,  # ignored
        )
        assert state.warmth == Warmth.NEUTRAL


class TestApplyVerbCredits:
    def test_warm_verb_first_use_grants_credits(self, coll, queues_patch):
        state, delta = apply_verb_credits(
            1, "wagoneer", 999, "hug", Warmth.WARM, collection=coll,
        )
        assert delta == 5
        assert state.warmth_credits == 5
        assert state.warmth == Warmth.NEUTRAL  # still in NEUTRAL band

    def test_same_warm_verb_twice_in_visit_only_counts_once(
        self, coll, queues_patch,
    ):
        apply_verb_credits(
            1, "wagoneer", 999, "hug", Warmth.WARM, collection=coll,
        )
        state, delta = apply_verb_credits(
            1, "wagoneer", 999, "hug", Warmth.WARM, collection=coll,
        )
        assert delta == 0  # already used this visit
        assert state.warmth_credits == 5  # unchanged

    def test_different_warm_verbs_in_visit_each_count(
        self, coll, queues_patch,
    ):
        apply_verb_credits(
            1, "wagoneer", 999, "hug", Warmth.WARM, collection=coll,
        )
        apply_verb_credits(
            1, "wagoneer", 999, "comfort", Warmth.WARM, collection=coll,
        )
        state, delta = apply_verb_credits(
            1, "wagoneer", 999, "nod", Warmth.NEUTRAL, collection=coll,
        )
        # hug (+5) + comfort (+5) + nod (+2) = +12
        assert state.warmth_credits == 12

    def test_cold_verb_lowers_credits(self, coll, queues_patch):
        state, delta = apply_verb_credits(
            1, "wagoneer", 999, "glare", Warmth.COLD, collection=coll,
        )
        assert delta == -5
        assert state.warmth_credits == -5

    def test_per_visit_one_tier_clamp_blocks_two_tier_jump(
        self, coll, queues_patch,
    ):
        # Player starts NEUTRAL (credits=0). Per-visit clamp
        # ceiling = top of WARM = +39. Pile on credits past that
        # and verify they cap at 39.
        from caldanai.lib.rpg.creatures.passersby.state import (
            _apply_credits_in_memory,
        )
        # Use the in-memory helper directly to slam many credits
        # in one visit and prove the clamp absorbs the excess.
        state = PasserbyState(
            channel_id=1, npc_stem="x", player_id=1,
            warmth_credits=0,
            tier_at_visit_start=Warmth.NEUTRAL,
        )
        applied = _apply_credits_in_memory(state, 100)
        assert state.warmth_credits == 39  # top of WARM
        assert applied == 39
        # A second attempt this visit caps at 0 (already at limit).
        applied2 = _apply_credits_in_memory(state, 50)
        assert applied2 == 0
        assert state.warmth_credits == 39

    def test_per_visit_clamp_works_downward(self, coll, queues_patch):
        from caldanai.lib.rpg.creatures.passersby.state import (
            _apply_credits_in_memory,
        )
        state = PasserbyState(
            channel_id=1, npc_stem="x", player_id=1,
            warmth_credits=0,
            tier_at_visit_start=Warmth.NEUTRAL,
        )
        applied = _apply_credits_in_memory(state, -100)
        # Bottom of COOL = -39
        assert state.warmth_credits == -39
        assert applied == -39


class TestApplyGreetCredits:
    def test_first_greet_grants_5(self, coll, queues_patch):
        state, delta = apply_greet_credits(
            1, "wagoneer", 999, collection=coll,
        )
        assert delta == GREET_CREDIT_DELTA == 5
        assert state.warmth_credits == 5

    def test_greet_same_visit_twice_only_once(self, coll, queues_patch):
        apply_greet_credits(1, "wagoneer", 999, collection=coll)
        state, delta = apply_greet_credits(1, "wagoneer", 999, collection=coll)
        assert delta == 0
        assert state.warmth_credits == 5


class TestWitnessKill:
    def test_non_passive_kill_grants_10(self, coll, queues_patch):
        state, delta = witness_kill(
            1, "wagoneer", 999,
            is_passive=False,
            monster_stem="bandit",
            collection=coll,
        )
        assert delta == WITNESS_NON_PASSIVE_KILL_CREDIT == 10
        assert state.warmth_credits == 10

    def test_passive_kill_default_penalty_neg_10(self, coll, queues_patch):
        state, delta = witness_kill(
            1, "wagoneer", 999,
            is_passive=True,
            monster_stem="sheep",
            collection=coll,
        )
        assert delta == WITNESS_PASSIVE_KILL_DEFAULT_CREDIT == -10
        assert state.warmth_credits == -10

    def test_passive_kill_per_npc_override_int(self, coll, queues_patch):
        # Wagoneer-style override: harsher penalty for sheep
        # specifically (hypothetical, just exercises the int path).
        state, delta = witness_kill(
            1, "wagoneer", 999,
            is_passive=True,
            monster_stem="sheep",
            passive_kill_penalty={"sheep": -25},
            collection=coll,
        )
        # Per-visit clamp on a NEUTRAL-start = bottom of COOL = -39.
        # -25 fits inside, so all of it lands.
        assert delta == -25
        assert state.warmth_credits == -25

    def test_shepherd_sheep_tier_drop_from_neutral(self, coll, queues_patch):
        state, delta = witness_kill(
            1, "shepherd", 999,
            is_passive=True,
            monster_stem="sheep",
            passive_kill_penalty={"sheep": TIER_DROP_SENTINEL},
            collection=coll,
        )
        # NEUTRAL → tier drop lands at top of COOL = -20.
        assert state.warmth_credits == -20
        assert state.warmth == Warmth.COOL

    def test_shepherd_sheep_tier_drop_from_warm(self, coll, queues_patch):
        _seed_player_slice(
            coll, 1, "shepherd", 999, warmth_credits=30,
        )
        state, delta = witness_kill(
            1, "shepherd", 999,
            is_passive=True,
            monster_stem="sheep",
            passive_kill_penalty={"sheep": TIER_DROP_SENTINEL},
            collection=coll,
        )
        # WARM → tier drop lands at top of NEUTRAL = +19.
        assert state.warmth_credits == 19
        assert state.warmth == Warmth.NEUTRAL

    def test_tier_drop_from_cold_is_noop(self, coll, queues_patch):
        _seed_player_slice(
            coll, 1, "shepherd", 999, warmth_credits=-80,
        )
        state, delta = witness_kill(
            1, "shepherd", 999,
            is_passive=True,
            monster_stem="sheep",
            passive_kill_penalty={"sheep": TIER_DROP_SENTINEL},
            collection=coll,
        )
        # Already COLD — nothing colder to drop to.
        assert delta == 0
        assert state.warmth_credits == -80

    def test_passive_kill_wildcard_fallback(self, coll, queues_patch):
        # NPC says "any passive kill is bad" — wildcard.
        state, delta = witness_kill(
            1, "herbalist", 999,
            is_passive=True,
            monster_stem="squirrel",
            passive_kill_penalty={"*": -15},
            collection=coll,
        )
        assert delta == -15

    def test_specific_stem_beats_wildcard(self, coll, queues_patch):
        state, delta = witness_kill(
            1, "shepherd", 999,
            is_passive=True,
            monster_stem="sheep",
            passive_kill_penalty={"sheep": TIER_DROP_SENTINEL, "*": -5},
            collection=coll,
        )
        # Specific entry wins; should be tier drop (lands at -20)
        # not the wildcard -5.
        assert state.warmth_credits == -20


class TestVisitLifecycleHooks:
    def test_arrival_resets_per_visit_state_for_existing_slices(
        self, coll, queues_patch,
    ):
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=15,
            visit_warm_verbs=["hug", "comfort"],
            visit_credits_delta=10,
        )
        count = mark_visit_arrival(1, "wagoneer", collection=coll)
        assert count == 1
        # Re-read; per-visit fields should be reset, credits
        # preserved, tier_at_visit_start captured from current
        # warmth (15 → NEUTRAL).
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 15
        assert state.visit_warm_verbs == []
        assert state.visit_cold_verbs == []
        assert state.visit_credits_delta == 0
        assert state.tier_at_visit_start == Warmth.NEUTRAL

    def test_arrival_no_doc_returns_zero(self, coll):
        count = mark_visit_arrival(1, "wagoneer", collection=coll)
        assert count == 0

    def test_depart_with_no_interaction_decays_positive_toward_zero(
        self, coll, queues_patch,
    ):
        """Positive credits step DOWN by 1 toward 0 on a missed
        visit — relationship cools toward neutral when not
        maintained."""
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=15,
            visit_arrived_at=None,
            visit_warm_verbs=[],
            visit_cold_verbs=[],
            visit_witnessed_kill_count=0,
        )
        decayed = mark_visit_depart(1, "wagoneer", collection=coll)
        assert decayed == 1
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 14  # 15 - 1 toward 0

    def test_depart_with_no_interaction_decays_negative_toward_zero(
        self, coll, queues_patch,
    ):
        """Negative credits step UP by 1 toward 0 on a missed
        visit — hostile relationships also soften with absence
        (you're not actively building grudges with someone who
        isn't there)."""
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=-15,
            visit_warm_verbs=[],
        )
        decayed = mark_visit_depart(1, "wagoneer", collection=coll)
        assert decayed == 1
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == -14  # -15 + 1 toward 0

    def test_depart_at_zero_credits_no_op(self, coll, queues_patch):
        """Credits already at the NEUTRAL center don't move on a
        missed visit — there's nowhere to step toward 0 from 0."""
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=0,
            visit_warm_verbs=[],
        )
        decayed = mark_visit_depart(1, "wagoneer", collection=coll)
        assert decayed == 0
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 0

    def test_depart_decay_does_not_cross_zero_from_positive(
        self, coll, queues_patch,
    ):
        """A player at +1 credits decays to 0 (not -1). Decay is
        floored at the NEUTRAL center — absence pulls toward
        neutral, never past it."""
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=1,
            visit_warm_verbs=[],
        )
        mark_visit_depart(1, "wagoneer", collection=coll)
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 0  # capped at NEUTRAL center

    def test_depart_decay_does_not_cross_zero_from_negative(
        self, coll, queues_patch,
    ):
        """A player at -1 credits decays to 0 (not +1). Same cap
        on the cold side — decay never overshoots the center."""
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=-1,
            visit_warm_verbs=[],
        )
        mark_visit_depart(1, "wagoneer", collection=coll)
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 0  # capped at NEUTRAL center

    def test_depart_with_interaction_no_decay(self, coll, queues_patch):
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=15,
            visit_warm_verbs=["hug"],
        )
        decayed = mark_visit_depart(1, "wagoneer", collection=coll)
        assert decayed == 0
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 15  # no decay

    def test_depart_apply_decay_false_skips_decay(self, coll, queues_patch):
        # Used by flee_from_attack — bystanders shouldn't get
        # punished when another player attacked the NPC.
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=15,
            visit_warm_verbs=[],
        )
        decayed = mark_visit_depart(
            1, "wagoneer", apply_decay=False, collection=coll,
        )
        assert decayed == 0
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.warmth_credits == 15

    def test_depart_resets_visit_tracking_regardless(self, coll, queues_patch):
        _seed_player_slice(
            coll, 1, "wagoneer", 999,
            warmth_credits=15,
            visit_warm_verbs=["hug"],
            visit_credits_delta=5,
        )
        mark_visit_depart(1, "wagoneer", collection=coll)
        state = get_state(1, "wagoneer", 999, collection=coll)
        assert state.visit_warm_verbs == []
        assert state.visit_credits_delta == 0
        assert state.visit_arrived_at is None


class TestLegacyMigration:
    def test_legacy_warmth_only_doc_derives_credits(self):
        # Pre-credits doc has only warmth tier. Round-trip through
        # from_slice_doc should derive credits from the tier
        # midpoint so the relationship survives the schema change.
        recovered = PasserbyState.from_slice_doc(
            {"warmth": "warm", "acquainted": True},
            channel_id=1, npc_stem="x", player_id=1,
        )
        assert recovered.warmth == Warmth.WARM
        assert recovered.warmth_credits == 25  # WARM midpoint

    def test_legacy_doc_with_no_warmth_at_all(self):
        recovered = PasserbyState.from_slice_doc(
            {}, channel_id=1, npc_stem="x", player_id=1,
        )
        assert recovered.warmth == Warmth.NEUTRAL
        assert recovered.warmth_credits == 0

    def test_credits_field_wins_over_legacy_warmth(self):
        # If both fields are present (e.g. mid-migration), credits
        # is the source of truth — derived warmth must match.
        recovered = PasserbyState.from_slice_doc(
            {"warmth": "warm", "warmth_credits": -30},
            channel_id=1, npc_stem="x", player_id=1,
        )
        assert recovered.warmth_credits == -30
        assert recovered.warmth == Warmth.COOL  # derived, not stored


class TestQueuedWriteIndependence:
    """Regression for the bug Caels caught playtesting Wren-greeting:
    consecutive helpers in the same code path used to each issue
    full-slice writes that read stale collection state — the
    ``$greet`` flow chained mark_encounter → mark_acquainted →
    apply_greet_credits, and the third write overwrote the second's
    ``acquainted_via="greet"`` because all three read the empty
    pre-write state and replaced the whole slice on flush.

    Per-field ``$set`` (with ``$addToSet`` for the verb-tracking
    list) means each helper only writes the fields it actually
    changed; sibling fields written by other helpers survive even
    when the queue defers all three writes."""

    def test_greet_flow_preserves_all_three_helpers_changes(
        self, coll, queues_patch,
    ):
        """Replays the cog's $greet sequence and asserts every
        helper's intended change is reflected on disk after all
        three queue ops have applied."""
        # 1. mark_encounter — bumps met_count.
        mark_encounter(1, "wren", 999, collection=coll)
        # 2. mark_acquainted — sets acquainted + via.
        mark_acquainted(1, "wren", 999, "greet", collection=coll)
        # 3. apply_greet_credits — bumps credits + records verb.
        apply_greet_credits(1, "wren", 999, collection=coll)

        state = get_state(1, "wren", 999, collection=coll)
        # All three changes must be visible — no helper clobbered
        # another's fields by writing the whole slice from a stale
        # read.
        assert state.met_count == 1, "mark_encounter's met_count was clobbered"
        assert state.acquainted is True, "mark_acquainted's acquainted was clobbered"
        assert state.acquainted_via == "greet", "mark_acquainted's via was clobbered"
        assert state.warmth_credits == 5, "apply_greet_credits's credits were clobbered"
        assert "greet" in state.visit_warm_verbs

    def test_witness_kill_preserves_acquaintance(
        self, coll, queues_patch,
    ):
        """A witnessed kill on a player who was just greeted
        shouldn't lose the acquaintance — the witness write only
        touches credit fields."""
        mark_acquainted(1, "wren", 999, "greet", collection=coll)
        witness_kill(
            1, "wren", 999,
            is_passive=False,
            monster_stem="bandit",
            collection=coll,
        )
        state = get_state(1, "wren", 999, collection=coll)
        assert state.acquainted is True
        assert state.acquainted_via == "greet"
        assert state.warmth_credits == 10

    def test_apply_verb_credits_preserves_acquaintance(
        self, coll, queues_patch,
    ):
        mark_acquainted(1, "wren", 999, "greet", collection=coll)
        apply_verb_credits(
            1, "wren", 999, "hug", Warmth.WARM, collection=coll,
        )
        state = get_state(1, "wren", 999, collection=coll)
        assert state.acquainted is True
        assert state.acquainted_via == "greet"
        assert state.warmth_credits == 5
        assert "hug" in state.visit_warm_verbs


class TestSetWarmthViaCredits:
    def test_set_warmth_writes_tier_midpoint_credits(self, coll, queues_patch):
        state = set_warmth(1, "wagoneer", 999, Warmth.HOT, collection=coll)
        assert state.warmth == Warmth.HOT
        assert state.warmth_credits == 50  # HOT midpoint

    def test_degrade_warmth_uses_midpoint(self, coll, queues_patch):
        _seed_player_slice(coll, 1, "wagoneer", 999, warmth_credits=50)
        state = degrade_warmth(1, "wagoneer", 999, collection=coll)
        assert state.warmth == Warmth.WARM
        assert state.warmth_credits == 25

    def test_promote_warmth_uses_midpoint(self, coll, queues_patch):
        state = promote_warmth(1, "wagoneer", 999, collection=coll)
        assert state.warmth == Warmth.WARM
        assert state.warmth_credits == 25
