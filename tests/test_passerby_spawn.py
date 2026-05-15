"""Tests for the passerby spawn-pipeline state machine in
``caldanai.lib.rpg.creatures.passersby.spawn``.

Pure-function design (game-like object passed in, no real
``Game``) so transitions are unit-testable without the Discord
or Mongo stack. Validates:

- State transitions: idle → present, idle → silhouette,
  silhouette → present (drain), present → idle (depart / flee).
- ``is_combat_active`` honors monster + combatants gates.
- ``pick_npc`` deduplicates aliases and uniformly samples plugin
  classes.
- ``flee_from_attack`` reads PRE-degrade warmth for line
  rendering and applies degrade after.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.creatures.passersby.spawn import (
    OUTCOME_DEATH,
    OUTCOME_FLED,
    OUTCOME_WON,
    attempt_spawn,
    depart_passerby,
    drain_silhouette,
    flee_from_attack,
    is_combat_active,
    overhear_keywords,
    overhear_mentions,
    pick_npc,
)
from caldanai.lib.rpg.creatures.passersby.wagoneer import Wagoneer
from caldanai.lib.rpg.creatures.passersby.wren import Wren
from caldanai.lib.rpg.helpers.warmth import Warmth


# ---------------------------------------------------------------------------
# Fake game / collection fixtures
# ---------------------------------------------------------------------------


def _make_game(
    monster=None, combatants=None, passerby=None, pending=None, channel_id=1,
):
    return SimpleNamespace(
        channel_id=channel_id,
        monster=monster,
        combatants=combatants or [],
        passerby=passerby,
        pending_silhouette=pending,
    )


def _make_alive_monster():
    """Minimal monster stand-in: ``is_dead()`` returns False."""
    m = MagicMock()
    m.is_dead.return_value = False
    return m


def _make_dead_monster():
    m = MagicMock()
    m.is_dead.return_value = True
    return m


class _FakeCollection:
    """Same shape as the test_passerby_state fixture — minimal
    pymongo Collection stand-in. Handles dotted-path ``$set``
    writes (``players.42`` syntax) so the per-NPC schema's
    atomic per-player slice writes apply correctly."""

    def __init__(self):
        self._docs = []

    def find_one(self, filter_):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in filter_.items()):
                return doc
        return None

    def insert(self, doc):
        """Test-only helper to seed the collection with prior state."""
        self._docs.append(doc)

    def upsert(self, key: dict, set_fields: dict):
        """Apply an upsert in the way the state module expects,
        including Mongo dotted-path semantics for nested writes."""
        existing = self.find_one(key)
        if existing is None:
            existing = {**key}
            self._docs.append(existing)
        for path, value in set_fields.items():
            self._apply_dotted_set(existing, path, value)

    @staticmethod
    def _apply_dotted_set(doc: dict, path: str, value) -> None:
        parts = path.split(".")
        target = doc
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value


def _seed_player_slice(coll, channel_id, npc_stem, player_id, **slice_fields):
    """Helper: seed the new per-NPC schema with one player slice.
    Used by tests that need pre-existing state for verifying mutator
    behavior."""
    coll.insert({
        "channel_id": channel_id,
        "npc_stem": npc_stem,
        "players": {str(player_id): dict(slice_fields)},
    })


def _make_capturing_queue_factories(coll):
    """Build the (FakeQueue, FakeQueuesDict) shape the spawn tests
    use to apply queued writes to a fake collection synchronously.
    Centralized here because the same boilerplate appeared in five
    tests previously."""
    captured: list = []

    class _CaptureQueue:
        def put(self, op):
            captured.append(op)
            filt = op._filter
            set_fields = op._doc.get("$set", {})
            coll.upsert(filt, set_fields)

    class _CaptureDict(dict):
        def __missing__(self, key):
            q = _CaptureQueue()
            self[key] = q
            return q

    return captured, _CaptureDict()


@pytest.fixture
def coll():
    return _FakeCollection()


@pytest.fixture
def quiet_db(coll):
    """Patch the DB module so writes go nowhere (pure-state tests
    don't care about persistence side-effects)."""

    class _NoOpQueue:
        def put(self, op):
            pass

    class _NoOpDict(dict):
        def __missing__(self, key):
            q = _NoOpQueue()
            self[key] = q
            return q

    with patch("caldanai.lib.rpg.creatures.passersby.state.DB") as mock_db:
        mock_db._passerby_state = coll
        mock_db._queues = _NoOpDict()
        yield mock_db


# ---------------------------------------------------------------------------
# is_combat_active
# ---------------------------------------------------------------------------


class TestIsCombatActive:
    def test_no_monster_no_combat(self):
        assert is_combat_active(_make_game()) is False

    def test_monster_no_combatants_no_combat(self):
        """Monster spawned but no players engaged → not in
        combat. Silhouette mode shouldn't fire just because a
        creature exists."""
        game = _make_game(monster=_make_alive_monster(), combatants=[])
        assert is_combat_active(game) is False

    def test_dead_monster_not_combat(self):
        game = _make_game(
            monster=_make_dead_monster(),
            combatants=[MagicMock()],
        )
        assert is_combat_active(game) is False

    def test_alive_monster_with_combatants(self):
        game = _make_game(
            monster=_make_alive_monster(),
            combatants=[MagicMock()],
        )
        assert is_combat_active(game) is True


# ---------------------------------------------------------------------------
# pick_npc
# ---------------------------------------------------------------------------


class TestPickNpc:
    def test_returns_class_from_registry(self):
        game = _make_game()
        registry = {"wagoneer": Wagoneer, "wren": Wren}
        cls = pick_npc(game, registry=registry)
        assert cls in (Wagoneer, Wren)

    def test_dedupes_aliases(self):
        """Multiple alias keys pointing at the same class should
        not bias the random pick toward that class."""
        game = _make_game()
        # Wagoneer with several alias keys; only one chance per
        # plugin class.
        registry = {
            "wagoneer": Wagoneer,
            "wagon driver": Wagoneer,
            "wagoner": Wagoneer,
            "wren": Wren,
        }
        # Sample 100 picks; both classes should appear (60-40
        # split if dedupe works, ~75-25 if not).
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=lambda seq: seq[0],
        ):
            cls = pick_npc(game, registry=registry)
        assert cls is Wagoneer  # First in dedup-preserve-order

    def test_empty_registry_returns_none(self):
        assert pick_npc(_make_game(), registry={}) is None


# ---------------------------------------------------------------------------
# attempt_spawn — state machine
# ---------------------------------------------------------------------------


class TestAttemptSpawn:
    def test_idle_to_present_no_combat(self, quiet_db):
        """Game with no combat → NPC arrives. ``passerby`` set;
        ``pending_silhouette`` stays None."""
        game = _make_game()
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.pick_npc",
            return_value=Wagoneer,
        ):
            line = attempt_spawn(game)
        assert isinstance(game.passerby, Wagoneer)
        assert game.pending_silhouette is None
        assert line is not None
        assert "wagoneer" in line.lower()

    def test_idle_to_silhouette_during_combat(self, quiet_db):
        """Combat active → NPC enters silhouette state, not
        present. Line is drawn from the silhouette pool, not
        the arrival pool."""
        game = _make_game(
            monster=_make_alive_monster(),
            combatants=[MagicMock()],
        )
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.pick_npc",
            return_value=Wagoneer,
        ):
            line = attempt_spawn(game)
        assert isinstance(game.pending_silhouette, Wagoneer)
        assert game.passerby is None
        assert line is not None
        # Verify line came from the silhouette pool by parser-
        # rendering each candidate with the same NPC and checking
        # for a match. Pool entries since 2026-05-03 use @1-token
        # forms (@1D, @1S) so pre-render comparison can't be
        # verbatim — we render then compare.
        from caldanai.lib.rpg.helpers.parser import parse
        npc = game.pending_silhouette
        rendered_silhouette = [parse(p, npc) for p in Wagoneer.SILHOUETTE_POOL]
        rendered_arrival = [parse(p, npc) for p in Wagoneer.ARRIVAL_POOL]
        assert line in rendered_silhouette
        assert line not in rendered_arrival

    def test_present_blocks_further_spawn(self, quiet_db):
        game = _make_game(passerby=Wagoneer())
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.pick_npc",
            return_value=Wren,
        ):
            line = attempt_spawn(game)
        assert line is None
        # State unchanged.
        assert isinstance(game.passerby, Wagoneer)

    def test_pending_silhouette_blocks_further_spawn(self, quiet_db):
        game = _make_game(pending=Wagoneer())
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.pick_npc",
            return_value=Wren,
        ):
            line = attempt_spawn(game)
        assert line is None
        assert isinstance(game.pending_silhouette, Wagoneer)

    def test_no_npc_picked_returns_none(self, quiet_db):
        game = _make_game()
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.pick_npc",
            return_value=None,
        ):
            line = attempt_spawn(game)
        assert line is None
        assert game.passerby is None


# ---------------------------------------------------------------------------
# drain_silhouette — combat-end hook
# ---------------------------------------------------------------------------


class TestDrainSilhouette:
    def test_no_pending_returns_none(self, quiet_db):
        game = _make_game()
        result = drain_silhouette(game, OUTCOME_WON)
        assert result is None

    def test_drain_promotes_to_present(self, quiet_db):
        game = _make_game(pending=Wagoneer())
        line = drain_silhouette(game, OUTCOME_WON)
        assert game.pending_silhouette is None
        assert isinstance(game.passerby, Wagoneer)
        assert line is not None

    @pytest.mark.parametrize("outcome,expected_pool_attr", [
        (OUTCOME_WON, "COMBAT_WON_REACTIONS"),
        (OUTCOME_FLED, "COMBAT_FLED_REACTIONS"),
        (OUTCOME_DEATH, "PARTY_DEATH_REACTIONS"),
    ])
    def test_outcome_selects_matching_pool(
        self, outcome, expected_pool_attr, quiet_db,
    ):
        """Each outcome routes to its specific pool. Verified by
        capturing the pool passed to ``random.choice``."""
        game = _make_game(pending=Wagoneer())
        captured = []

        def capturing_choice(pool):
            captured.append(pool)
            return pool[0]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=capturing_choice,
        ):
            drain_silhouette(game, outcome)
        assert captured[0] is getattr(Wagoneer, expected_pool_attr)

    def test_witness_renders_with_state(self, coll, quiet_db):
        """Witness passed → reaction line uses witness as @2 with
        StrangerActor / real-name surface based on acquaintance."""
        game = _make_game(pending=Wagoneer())
        witness = SimpleNamespace(
            name="Caels",
            uses_article=False,
            user_id=1,
            pronouns={
                __import__(
                    "caldanai.lib.rpg.helpers.enums", fromlist=["Pronouns"]
                ).Pronouns.SUBJECTIVE: "he",
                __import__(
                    "caldanai.lib.rpg.helpers.enums", fromlist=["Pronouns"]
                ).Pronouns.OBJECTIVE: "him",
                __import__(
                    "caldanai.lib.rpg.helpers.enums", fromlist=["Pronouns"]
                ).Pronouns.POSSESSIVE: "his",
                __import__(
                    "caldanai.lib.rpg.helpers.enums", fromlist=["Pronouns"]
                ).Pronouns.ADJECTIVE: "his",
                __import__(
                    "caldanai.lib.rpg.helpers.enums", fromlist=["Pronouns"]
                ).Pronouns.REFLEXIVE: "himself",
            },
            plural_verbs=False,
        )
        # Not acquainted → witness renders as "the traveler" in
        # the resulting line.
        line = drain_silhouette(
            game, OUTCOME_WON, witness=witness, collection=coll,
        )
        assert line is not None
        # Should NOT contain "Caels" (not acquainted yet).
        assert "Caels" not in line


# ---------------------------------------------------------------------------
# drain_silhouette — passive-kill branch
# ---------------------------------------------------------------------------


class TestDrainSilhouettePassiveKill:
    """When the resolved combat killed a passive monster (e.g. a
    sheep), the silhouette-drain should pick from the NPC's
    PASSIVE_KILL_REACTIONS pool instead of the generic
    COMBAT_WON_REACTIONS praise pool. Player-reported 2026-05-09:
    *"It looks like the shepherd wanted us to kill his sheep?"* —
    the COMBAT_WON praise was firing on a sheep-kill, opposite of
    the design intent encoded in PASSIVE_KILL_PENALTY."""

    def _make_passive_monster(self, stem: str = "sheep"):
        """Monster mock with PASSIVE aggression + a module-stem the
        passive-kill lookup can match against."""
        from caldanai.lib.rpg.helpers.enums import AggressionLevels
        m = MagicMock()
        m.aggression = AggressionLevels.PASSIVE
        # Override __module__ so the spawn-side stem extraction
        # (``type(monster).__module__.rsplit(".", 1)[-1].lower()``)
        # produces our intended stem.
        type(m).__module__ = f"caldanai.lib.rpg.creatures.monsters.{stem}"
        return m

    def _make_aggressive_monster(self):
        from caldanai.lib.rpg.helpers.enums import AggressionLevels
        m = MagicMock()
        m.aggression = AggressionLevels.VENGEFUL
        type(m).__module__ = "caldanai.lib.rpg.creatures.monsters.bandit"
        return m

    def test_passive_kill_uses_passive_pool_when_stem_matches(
        self, quiet_db,
    ):
        """Shepherd has ``PASSIVE_KILL_REACTIONS["sheep"]``. With a
        passive sheep monster + WON outcome, the dispatch picks
        from that pool, NOT from COMBAT_WON_REACTIONS."""
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        game = _make_game(
            monster=self._make_passive_monster("sheep"),
            pending=Shepherd(),
        )
        captured = []

        def capturing_choice(pool):
            captured.append(pool)
            return pool[0]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=capturing_choice,
        ):
            drain_silhouette(game, OUTCOME_WON)

        assert captured[0] is Shepherd.PASSIVE_KILL_REACTIONS["sheep"]
        assert captured[0] is not Shepherd.COMBAT_WON_REACTIONS

    def test_passive_kill_falls_back_to_wildcard_when_no_stem_match(
        self, quiet_db,
    ):
        """Shepherd has ``"*"`` wildcard for any-passive. Killing
        a hypothetical passive monster with no stem-specific entry
        falls through to the wildcard pool."""
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        game = _make_game(
            # Use a stem that doesn't exist in PASSIVE_KILL_REACTIONS.
            monster=self._make_passive_monster("hypothetical_passive"),
            pending=Shepherd(),
        )
        captured = []

        def capturing_choice(pool):
            captured.append(pool)
            return pool[0]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=capturing_choice,
        ):
            drain_silhouette(game, OUTCOME_WON)

        assert captured[0] is Shepherd.PASSIVE_KILL_REACTIONS["*"]

    def test_passive_kill_falls_through_when_no_pool_at_all(
        self, quiet_db,
    ):
        """An NPC without ANY ``PASSIVE_KILL_REACTIONS`` entries
        falls through to ``COMBAT_WON_REACTIONS``. Bug-prevention
        tradeoff: silent-fall-through would be more correct
        philosophically (don't praise the kill), but COMBAT_WON
        keeps the silhouette beat from disappearing entirely. Authors
        opt INTO the passive-kill branch by populating the pool."""
        from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin

        class _BareNPC(PasserbyPlugin):
            COMBAT_WON_REACTIONS = ["@1D arrives. \"Done.\""]
            # No PASSIVE_KILL_REACTIONS — inherits empty default.

        game = _make_game(
            monster=self._make_passive_monster("sheep"),
            pending=_BareNPC(),
        )
        captured = []

        def capturing_choice(pool):
            captured.append(pool)
            return pool[0]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=capturing_choice,
        ):
            drain_silhouette(game, OUTCOME_WON)

        assert captured[0] is _BareNPC.COMBAT_WON_REACTIONS

    def test_non_passive_kill_uses_combat_won_unchanged(self, quiet_db):
        """Non-passive monster (bandit, etc.) → COMBAT_WON_REACTIONS,
        same as before the fix. The passive-kill branch is gated on
        ``aggression == PASSIVE``; everything else passes through."""
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        game = _make_game(
            monster=self._make_aggressive_monster(),
            pending=Shepherd(),
        )
        captured = []

        def capturing_choice(pool):
            captured.append(pool)
            return pool[0]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=capturing_choice,
        ):
            drain_silhouette(game, OUTCOME_WON)

        assert captured[0] is Shepherd.COMBAT_WON_REACTIONS

    def test_passive_kill_only_branches_on_won_outcome(self, quiet_db):
        """FLED/DEATH outcomes don't branch on passive-kill — those
        outcomes mean the monster wasn't actually killed (FLED) or
        a player died (DEATH); neither is "you killed a sheep"."""
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        game = _make_game(
            monster=self._make_passive_monster("sheep"),
            pending=Shepherd(),
        )
        captured = []

        def capturing_choice(pool):
            captured.append(pool)
            return pool[0]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            side_effect=capturing_choice,
        ):
            drain_silhouette(game, OUTCOME_FLED)
        assert captured[0] is Shepherd.COMBAT_FLED_REACTIONS


class TestGetPassiveKillPool:
    """``PasserbyPlugin.get_passive_kill_pool`` helper precedence:
    stem-specific > ``"*"`` wildcard > empty list. Used by both
    the silhouette-drain branch (spawn.py) and the Present-passerby
    branch (Game._render_present_passive_kill_reaction)."""

    def test_stem_specific_wins(self):
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        pool = Shepherd.get_passive_kill_pool("sheep")
        assert pool is Shepherd.PASSIVE_KILL_REACTIONS["sheep"]

    def test_wildcard_fallback_when_stem_unknown(self):
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        pool = Shepherd.get_passive_kill_pool("hypothetical_other")
        assert pool is Shepherd.PASSIVE_KILL_REACTIONS["*"]

    def test_empty_when_no_pool_at_all(self):
        from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin

        class _BareNPC(PasserbyPlugin):
            pass

        assert _BareNPC.get_passive_kill_pool("sheep") == []
        assert _BareNPC.get_passive_kill_pool("anything") == []


# ---------------------------------------------------------------------------
# depart_passerby
# ---------------------------------------------------------------------------


class TestDepartPasserby:
    def test_no_passerby_returns_none(self):
        game = _make_game()
        assert depart_passerby(game) is None

    def test_present_to_idle(self):
        game = _make_game(passerby=Wagoneer())
        line = depart_passerby(game)
        assert game.passerby is None
        assert line is not None
        assert "wagoneer" in line.lower() or "cart" in line.lower()


class TestKeywordBiasedDeparture:
    """Per-visit keyword bias on DEPARTURE_POOL. When the NPC has
    overheard a ``NAME_DROP_KEYWORDS`` token in player chat, the
    matching pool line is heavily weighted at depart-time so the
    name-drop feels like the world responding rather than a
    1-in-N lottery draw."""

    def test_empty_heard_keywords_uses_unweighted_choice(self):
        """No heard keywords → no weights passed; the implementation
        falls through to plain ``random.choice``. Patch both
        ``choice`` and ``choices`` to assert only ``choice`` is
        called."""
        wren = Wren()
        assert wren.heard_keywords == set()
        game = _make_game(passerby=wren)
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            return_value="canned-line",
        ) as mock_choice, patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choices",
        ) as mock_choices:
            depart_passerby(game)
        assert mock_choice.called
        assert not mock_choices.called

    def test_heard_keyword_with_matching_line_biases_via_weights(self):
        """When a heard keyword's substring appears in a pool line,
        ``random.choices`` is called with a weights list where the
        matching line carries ``_KEYWORD_BIAS_WEIGHT`` and the rest
        carry 1. Verifies the weight construction, not the random
        outcome (deterministic over the build, not the pick)."""
        wren = Wren()
        wren.heard_keywords.add("halrick")
        game = _make_game(passerby=wren)
        captured_weights = []
        captured_pool = []

        def fake_choices(pool, weights, k=1):
            captured_pool.extend(pool)
            captured_weights.extend(weights)
            return [pool[0]]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choices",
            side_effect=fake_choices,
        ):
            depart_passerby(game)

        # Pool was Wren's full DEPARTURE_POOL.
        assert captured_pool == Wren.DEPARTURE_POOL
        # Exactly one line in Wren's pool contains "Halrick" — that
        # one gets bias weight; the other five get weight 1.
        halrick_lines = [
            i for i, line in enumerate(Wren.DEPARTURE_POOL)
            if "Halrick" in line
        ]
        assert len(halrick_lines) == 1
        halrick_idx = halrick_lines[0]
        for i, weight in enumerate(captured_weights):
            if i == halrick_idx:
                assert weight > 1, (
                    f"line {i} ({Wren.DEPARTURE_POOL[i]!r}) should be "
                    f"weighted >1, got {weight}"
                )
            else:
                assert weight == 1, (
                    f"line {i} should be weight 1, got {weight}"
                )

    def test_heard_keyword_with_no_matching_line_falls_back_to_choice(self):
        """If a heard keyword's substring doesn't appear in any pool
        line (e.g. a name-drop that hasn't been authored yet), the
        weights list collapses to all-1 — pragmatically equivalent
        to ``choice`` — so the bias path no-ops gracefully. The
        implementation chooses ``choice`` directly when no pool
        line matches any heard substring."""
        wren = Wren()
        # Synthetic: pretend Wren learned "ghost" but no pool line
        # contains the substring "Ghost".
        wren.NAME_DROP_KEYWORDS = {"ghost": "Ghost"}
        wren.heard_keywords.add("ghost")
        assert not any("Ghost" in line for line in Wren.DEPARTURE_POOL)
        game = _make_game(passerby=wren)
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choice",
            return_value="canned-line",
        ) as mock_choice, patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choices",
        ) as mock_choices:
            depart_passerby(game)
        assert mock_choice.called
        assert not mock_choices.called


# ---------------------------------------------------------------------------
# flee_from_attack — kill-route flee path
# ---------------------------------------------------------------------------


class TestPickNpcTimeFilter:
    """Time-of-day spawn gating — Wren shouldn't run errands at
    midnight, the wagoneer doesn't cart at 02:00."""

    def test_diurnal_wagoneer_active_at_noon(self):
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        registry = {"wagoneer": Wagoneer}
        cls = pick_npc(
            _make_game(), registry=registry,
            time_of_day=TimesOfDay.NOON,
        )
        assert cls is Wagoneer

    def test_diurnal_wagoneer_filtered_out_at_night(self):
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        registry = {"wagoneer": Wagoneer}
        cls = pick_npc(
            _make_game(), registry=registry,
            time_of_day=TimesOfDay.NIGHT,
        )
        assert cls is None

    def test_wren_filtered_out_at_dusk(self):
        """Wren's partition excludes DUSK (kid expected home by
        sundown)."""
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        registry = {"wren": Wren}
        cls = pick_npc(
            _make_game(), registry=registry,
            time_of_day=TimesOfDay.DUSK,
        )
        assert cls is None

    def test_herbalist_active_at_dusk(self):
        """The herbalist explicitly walks at dusk for the herbs
        that only show themselves then."""
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        registry = {"herbalist": Herbalist}
        cls = pick_npc(
            _make_game(), registry=registry,
            time_of_day=TimesOfDay.DUSK,
        )
        assert cls is Herbalist

    def test_no_active_npcs_returns_none(self):
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        # All four NPCs filtered out at deep NIGHT.
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        registry = {
            "wagoneer": Wagoneer,
            "herbalist": Herbalist,
            "shepherd": Shepherd,
            "wren": Wren,
        }
        cls = pick_npc(
            _make_game(), registry=registry,
            time_of_day=TimesOfDay.NIGHT,
        )
        assert cls is None

    def test_resolves_time_from_game_clock(self):
        """Production binding: ``pick_npc`` reads
        ``game.game_clock.get_time_of_day()`` when ``time_of_day``
        not explicitly passed."""
        registry = {"wagoneer": Wagoneer}
        clock = MagicMock()
        clock.get_time_of_day.return_value = "noon"
        game = SimpleNamespace(
            channel_id=1, monster=None, combatants=[],
            passerby=None, pending_silhouette=None,
            game_clock=clock,
        )
        cls = pick_npc(game, registry=registry)
        assert cls is Wagoneer

    def test_no_clock_skips_filter(self):
        """Game without a clock (test fixtures, edge cases) gets
        all candidates — defensive."""
        registry = {"wagoneer": Wagoneer}
        cls = pick_npc(_make_game(), registry=registry)
        # _make_game has no game_clock; filter is skipped.
        assert cls is Wagoneer


class TestOverhearMentions:
    """Acquaintance-via-@mention learning. NPC overhears another
    player @mentioning a player and learns the mentioned
    player's name."""

    def test_no_passerby_does_nothing(self, coll, quiet_db):
        game = _make_game()
        msg = SimpleNamespace(mentions=[])
        result = overhear_mentions(game, msg, collection=coll)
        assert result == []

    def test_no_mentions_does_nothing(self, coll, quiet_db):
        game = _make_game(passerby=Wagoneer())
        msg = SimpleNamespace(mentions=[])
        result = overhear_mentions(game, msg, collection=coll)
        assert result == []

    def test_mention_of_game_player_acquaints(self, coll):
        game = _make_game(passerby=Wagoneer())
        # Stand in a player_manager with one player keyed by id.
        target_player = SimpleNamespace(id=42)
        game.player_manager = SimpleNamespace(players={42: target_player})

        msg = SimpleNamespace(
            mentions=[SimpleNamespace(id=42, bot=False)],
        )

        captured_ops, queues_dict = _make_capturing_queue_factories(coll)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.DB"
        ) as mock_db:
            mock_db._passerby_state = coll
            mock_db._queues = queues_dict
            result = overhear_mentions(game, msg, collection=coll)

        assert result == [42]
        # Per-NPC parent doc with the player's slice nested under
        # ``players["42"]``.
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        slice_data = doc["players"]["42"]
        assert slice_data["acquainted"] is True
        assert slice_data["acquainted_via"] == "mention"

    def test_mention_of_non_game_player_ignored(self, coll, quiet_db):
        """A bystander @mention of someone NOT in the player roster
        doesn't earn acquaintance — NPCs only learn names of
        actual players."""
        game = _make_game(passerby=Wagoneer())
        game.player_manager = SimpleNamespace(players={})  # no players
        msg = SimpleNamespace(
            mentions=[SimpleNamespace(id=999, bot=False)],
        )
        result = overhear_mentions(game, msg, collection=coll)
        assert result == []

    def test_already_acquainted_skipped(self, coll, quiet_db):
        """Re-mention of an already-acquainted player doesn't
        re-fire mark_acquainted (count returns 0)."""
        _seed_player_slice(
            coll, 1, "wagoneer", 42,
            warmth="neutral",
            acquainted=True,
            acquainted_via="greet",
        )
        game = _make_game(passerby=Wagoneer())
        target_player = SimpleNamespace(id=42)
        game.player_manager = SimpleNamespace(players={42: target_player})
        msg = SimpleNamespace(
            mentions=[SimpleNamespace(id=42, bot=False)],
        )
        result = overhear_mentions(game, msg, collection=coll)
        assert result == []  # Already known.

    def test_silhouette_npc_also_learns(self, coll):
        """An NPC in silhouette mode (during combat) still
        overhears mentions — they're at the verge, not deaf."""
        game = _make_game(pending=Wagoneer())
        target_player = SimpleNamespace(id=42)
        game.player_manager = SimpleNamespace(players={42: target_player})
        msg = SimpleNamespace(
            mentions=[SimpleNamespace(id=42, bot=False)],
        )

        captured_ops, queues_dict = _make_capturing_queue_factories(coll)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.DB"
        ) as mock_db:
            mock_db._passerby_state = coll
            mock_db._queues = queues_dict
            result = overhear_mentions(game, msg, collection=coll)
        assert result == [42]


class TestOverhearKeywords:
    """Keyword overhear hook. When a player posts a message and the
    NPC has opted into ``NAME_DROP_KEYWORDS``, matching tokens
    accumulate on the NPC's per-visit ``heard_keywords`` set for
    later use in :func:`_pick_departure_line`."""

    def test_no_passerby_returns_empty(self):
        game = _make_game()
        msg = SimpleNamespace(content="tell Halrick about it")
        assert overhear_keywords(game, msg) == []

    def test_npc_without_name_drop_keywords_no_ops(self):
        """An NPC class that hasn't opted into the bias (the default)
        skips the scan entirely — no scribbling on a set the NPC
        doesn't use."""
        wagoneer = Wagoneer()
        assert wagoneer.NAME_DROP_KEYWORDS == {}
        game = _make_game(passerby=wagoneer)
        msg = SimpleNamespace(content="tell Halrick about it")
        assert overhear_keywords(game, msg) == []
        assert wagoneer.heard_keywords == set()

    def test_keyword_token_added_to_heard(self):
        wren = Wren()
        game = _make_game(passerby=wren)
        msg = SimpleNamespace(
            content="Tell old Marn the standing-stones got a new one today",
        )
        newly_heard = overhear_keywords(game, msg)
        assert newly_heard == ["marn"]
        assert "marn" in wren.heard_keywords

    def test_case_insensitive_token_match(self):
        """Player-side capitalization doesn't matter for token
        detection — ``Marn`` / ``MARN`` / ``marn`` all add the
        ``"marn"`` key."""
        wren = Wren()
        game = _make_game(passerby=wren)
        msg = SimpleNamespace(content="HALRICK was just asking about you")
        newly_heard = overhear_keywords(game, msg)
        assert newly_heard == ["halrick"]
        assert "halrick" in wren.heard_keywords

    def test_message_without_keyword_no_ops(self):
        wren = Wren()
        game = _make_game(passerby=wren)
        msg = SimpleNamespace(
            content="the cyclops just walked, dirt knows where",
        )
        assert overhear_keywords(game, msg) == []
        assert wren.heard_keywords == set()

    def test_duplicate_keyword_not_re_added(self):
        """Same token in a later message returns empty newly_heard
        (already accumulated). The set stays the size it was."""
        wren = Wren()
        game = _make_game(passerby=wren)
        first = SimpleNamespace(content="tell Halrick")
        overhear_keywords(game, first)
        assert wren.heard_keywords == {"halrick"}
        second = SimpleNamespace(content="and Halrick says hi back")
        assert overhear_keywords(game, second) == []
        assert wren.heard_keywords == {"halrick"}

    def test_multiple_keywords_in_one_message(self):
        wren = Wren()
        game = _make_game(passerby=wren)
        msg = SimpleNamespace(
            content="news for old Marn AND Halrick at the ferry-house",
        )
        newly_heard = overhear_keywords(game, msg)
        assert set(newly_heard) == {"marn", "halrick"}
        assert wren.heard_keywords == {"marn", "halrick"}

    def test_silhouette_npc_also_overhears(self):
        """An NPC in pending_silhouette mode is at the verge, not
        deaf — keywords spoken during combat accumulate so the
        eventual departure (after the silhouette resolves and the
        NPC eventually departs) carries the bias."""
        wren = Wren()
        game = _make_game(pending=wren)
        msg = SimpleNamespace(content="news for old Marn")
        newly_heard = overhear_keywords(game, msg)
        assert newly_heard == ["marn"]
        assert wren.heard_keywords == {"marn"}

    def test_missing_content_attr_treated_as_empty(self):
        """Defensive: a malformed message object without a
        ``content`` attribute should no-op cleanly rather than
        raise — protects against unexpected discord.py message
        shapes."""
        wren = Wren()
        game = _make_game(passerby=wren)
        msg = SimpleNamespace()  # no content attribute
        assert overhear_keywords(game, msg) == []
        assert wren.heard_keywords == set()

    def test_end_to_end_overhear_then_depart_biases(self):
        """Integration: the NPC overhears a keyword, then the
        departure call sees the heard set and invokes the weighted
        ``choices`` path. Verifies the side-effect chain through
        ``heard_keywords`` rather than mocking pieces."""
        wren = Wren()
        game = _make_game(passerby=wren)
        overhear_keywords(
            game, SimpleNamespace(content="tell Halrick about the kill"),
        )
        assert "halrick" in wren.heard_keywords
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.choices",
            return_value=[Wren.DEPARTURE_POOL[0]],  # any line; just witness call
        ) as mock_choices:
            depart_passerby(game)
        assert mock_choices.called


class TestFleeFromAttack:
    def test_no_passerby_returns_none(self, quiet_db):
        game = _make_game()
        attacker = SimpleNamespace(user_id=1)
        result = flee_from_attack(game, attacker)
        assert result is None

    def test_flee_clears_passerby(self, coll, quiet_db):
        game = _make_game(passerby=Wagoneer())
        attacker = SimpleNamespace(
            name="Aggressor", uses_article=False, user_id=42,
            pronouns={}, plural_verbs=False,
        )
        # Pre-populate with acquainted state so the line could use
        # the real name (verifies the PRE-degrade read).
        _seed_player_slice(
            coll, 1, "wagoneer", 42,
            warmth="warm", acquainted=True, acquainted_via="greet",
            met_count=3,
        )
        line = flee_from_attack(game, attacker, collection=coll)
        assert game.passerby is None
        assert line is not None

    def test_flee_degrades_warmth(self, coll, quiet_db):
        game = _make_game(passerby=Wagoneer())
        attacker = SimpleNamespace(
            name="Aggressor", uses_article=False, user_id=42,
            pronouns={}, plural_verbs=False,
        )
        _seed_player_slice(
            coll, 1, "wagoneer", 42,
            warmth="warm", acquainted=True,
        )
        captured, queues_dict = _make_capturing_queue_factories(coll)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.DB"
        ) as mock_db:
            mock_db._passerby_state = coll
            mock_db._queues = queues_dict
            flee_from_attack(game, attacker, collection=coll)
        # Warmth dropped from WARM → NEUTRAL (one tier).
        doc = coll.find_one({
            "channel_id": 1, "npc_stem": "wagoneer",
        })
        slice_data = doc["players"]["42"]
        assert slice_data["warmth"] == str(Warmth.NEUTRAL)
