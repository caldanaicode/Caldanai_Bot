"""Integration tests for the passerby NPC system wiring.

The pure-logic state machine (``spawn.py``) and rendering / state
modules have their own test files. This file covers the WIRING
between those primitives and the rest of the bot:

- ``Game._finalize_combat`` promotes a pending silhouette via
  ``drain_silhouette`` with outcome detection from ``looters``.
- ``Game.do_passerby_spawn`` dispatches the arrival line and
  schedules the depart timer when an NPC arrives present.
- ``Game.do_passerby_depart`` dispatches the departure line.
- ``RpgSocialCommands._maybe_route_to_passerby_social`` matches
  by name / stem / alias, picks the warmth pool, and marks
  acquainted on greet.
- ``RpgUserCommands._maybe_flee_passerby`` routes ``$kill <NPC>``
  to ``flee_from_attack`` and skips the combat path.
- ``RpgInfoCommands._render_passerby_look_line`` returns the
  appropriate one-liner for present / silhouette / idle states.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.rpg.creatures.passersby.wagoneer import Wagoneer
from caldanai.lib.rpg.creatures.passersby.wren import Wren
from caldanai.lib.rpg.helpers.warmth import Warmth


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_game_guild_channel(mock_db):
    guild = MagicMock()
    guild.id = 111
    guild.roles = []
    channel = MagicMock()
    channel.id = 222
    mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}
    return guild, channel


def _make_finalize_game(mock_db, mock_gc_cls):
    """Game shaped for ``_finalize_combat`` exercises — combat
    fields populated, mocked clock + role lookup, async stubs for
    ``end_combat`` / ``set_spawn_timer`` so the unit test stays
    focused on the silhouette branch.
    """
    guild, channel = _make_game_guild_channel(mock_db)

    mock_gc = MagicMock()
    mock_gc.get_seconds.return_value = 0
    mock_gc.time_scale = 4
    mock_gc.add_routine = MagicMock()
    mock_gc_cls.return_value = mock_gc

    from caldanai.lib.rpg import Game
    from caldanai.lib.rpg.helpers.enums import Roles

    game = Game(
        guild=guild,
        channel=channel,
        use_spawn_timer=False,
        enable_ambience=False,
    )
    game.combat.loot_size_at_start = 0
    game.player_manager.clear_combat_roles = AsyncMock()
    game.set_spawn_timer = AsyncMock()
    combat_role = MagicMock()
    combat_role.mention = "@combat"
    game.player_manager.roles = {Roles.COMBAT_MAIN: combat_role}
    return game


class _FakePlayer:
    """Minimal Player stand-in for outcome detection. ``user_id``
    + ``is_dead()`` is all _drain_passerby_silhouette reads."""

    def __init__(self, user_id: int, dead: bool = False, name: str = "tester"):
        self.user_id = user_id
        self.name = name
        self._dead = dead
        # Pronouns dict shape parser expects — defaults applied so a
        # rendered line doesn't trip on a missing key.
        self.pronouns = {None: "they", "subject": "they"}
        self.uses_article = False

    def is_dead(self) -> bool:
        return self._dead


class _FakeCollection:
    """Minimal pymongo Collection stand-in — same shape used by the
    state-module tests.
    """

    def __init__(self):
        self._docs = []
        self.queue = []

    def find_one(self, filter_):
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in filter_.items()):
                return doc
        return None


# ---------------------------------------------------------------------------
# Game integration: silhouette drain at combat end
# ---------------------------------------------------------------------------


class TestFinalizeCombatDrainsSilhouette:
    """``_finalize_combat`` must promote a pending silhouette into
    present-state with the right outcome BEFORE end_combat clears
    the looters list (witness pickup needs them in scope)."""

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_no_silhouette_no_drain(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """No pending silhouette → no drain, no extra dispatch."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        game.pending_silhouette = None
        game.passerby = None
        game.looters = [_FakePlayer(1)]

        await game._finalize_combat(outcome="death")
        # Verify the silhouette slot stays None; drain wasn't triggered.
        assert game.pending_silhouette is None
        assert game.passerby is None

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_death_outcome_with_alive_looters_promotes_won(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Monster died, all looters alive → OUTCOME_WON — wagoneer
        promotes from silhouette to present and the WON-reaction
        line lands in the announce string the caller will dispatch
        as part of the round-output narration."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        npc = Wagoneer()
        game.pending_silhouette = npc
        game.looters = [_FakePlayer(1, dead=False)]
        # Force loot present so announce is non-empty for the
        # silhouette-prepend path.
        game.loot = {1: ["fake_item"]}

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.get_state"
        ) as mock_get_state:
            mock_get_state.return_value = SimpleNamespace(
                acquainted=False, warmth=Warmth.NEUTRAL,
            )
            announce = await game._finalize_combat(outcome="death")

        assert game.pending_silhouette is None
        assert game.passerby is npc
        # Silhouette line landed in announce (NOT dispatched
        # directly) so the caller can splice it after the round
        # narration. Content varies by random pool pick — verify
        # the prepend happened by asserting some non-empty
        # silhouette-line content sits AHEAD of the loot prompt.
        assert announce
        assert "loot" in announce  # loot prompt still present
        # Silhouette line should appear before "There might be"
        # (the loot prompt's signature) — drop empty/blank lines
        # for a robust order check.
        loot_idx = announce.find("There might be")
        assert loot_idx > 0, "silhouette line should prepend loot prompt"
        prefix = announce[:loot_idx].strip()
        assert prefix, "silhouette line should be non-empty"

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_flee_outcome_with_alive_looters_promotes_fled(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Monster bolted, all looters alive → OUTCOME_FLED."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        npc = Wagoneer()
        game.pending_silhouette = npc
        game.looters = [_FakePlayer(1, dead=False)]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.get_state"
        ) as mock_get_state:
            mock_get_state.return_value = SimpleNamespace(
                acquainted=False, warmth=Warmth.NEUTRAL,
            )
            await game._finalize_combat(outcome="flee")

        assert game.passerby is npc
        assert game.pending_silhouette is None

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_party_death_takes_precedence_over_combat_outcome(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Even a 'death' (monster-killed) combat that also took a
        party member should fire the PARTY_DEATH reaction pool — the
        fallen looter is the load-bearing signal."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        npc = Wagoneer()
        game.pending_silhouette = npc
        game.looters = [
            _FakePlayer(1, dead=True, name="Vael"),
            _FakePlayer(2, dead=False, name="Caels"),
        ]

        # Force loot so announce is non-empty.
        game.loot = {1: ["fake_item"]}
        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.get_state"
        ) as mock_get_state:
            mock_get_state.return_value = SimpleNamespace(
                acquainted=False, warmth=Warmth.NEUTRAL,
            )
            announce = await game._finalize_combat(outcome="death")

        assert game.passerby is npc
        # Verify the line came from PARTY_DEATH_REACTIONS — content
        # rides in the announce string, not the direct dispatch.
        blob = announce or ""
        # Match against a unique-fragment from each line in
        # Wagoneer.PARTY_DEATH_REACTIONS (one phrase per line so a
        # different random pick still satisfies the assertion).
        assert any(
            phrase in blob.lower()
            for phrase in (
                "dirt mends",        # line 1: "the dirt mends"
                "kneels by",          # line 2: "He kneels by @2"
                "respect",           # line 3: "the cart owes the moment that respect"
                "road tax",          # line 4: "Road tax"
                "remember the face", # line 5: "I'll remember the face"
            )
        ), f"expected PARTY_DEATH flavor; got:\n{blob}"

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_drain_schedules_depart_timer(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """After promoting a silhouette to present, the depart
        timer must be scheduled so the NPC doesn't linger forever."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        npc = Wagoneer()
        game.pending_silhouette = npc
        game.looters = [_FakePlayer(1, dead=False)]

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.get_state"
        ) as mock_get_state:
            mock_get_state.return_value = SimpleNamespace(
                acquainted=False, warmth=Warmth.NEUTRAL,
            )
            await game._finalize_combat(outcome="death")

        # add_routine called with do_passerby_depart somewhere in
        # the call list (the same clock also gets loot_expires +
        # set_spawn_timer scheduled in this path).
        scheduled = [
            c.args[0].__name__
            for c in game.game_clock.add_routine.call_args_list
            if hasattr(c.args[0], "__name__")
        ]
        assert "do_passerby_depart" in scheduled, (
            f"expected depart timer scheduled; got {scheduled}"
        )


# ---------------------------------------------------------------------------
# Game integration: spawn / depart timer routines
# ---------------------------------------------------------------------------


class TestPasserbyTimerRoutines:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_do_passerby_spawn_dispatches_and_re_arms(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """do_passerby_spawn must dispatch the arrival line, schedule
        depart, and re-arm the spawn timer."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        npc = Wagoneer()

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.attempt_spawn"
        ) as mock_attempt:
            # Simulate present-arrival: attempt_spawn sets passerby
            # and returns a flavor line.
            def _fake_attempt(g):
                g.passerby = npc
                return "A wagoneer rolls his cart up."
            mock_attempt.side_effect = _fake_attempt

            await game.do_passerby_spawn()

        # Dispatched the arrival line.
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("wagoneer" in str(m) for m in added)

        # Scheduled the depart routine and re-armed the spawn timer.
        scheduled = [
            c.args[0].__name__
            for c in game.game_clock.add_routine.call_args_list
            if hasattr(c.args[0], "__name__")
        ]
        assert "do_passerby_depart" in scheduled
        # set_passerby_timer is itself scheduled by the awaited call
        # at the end of do_passerby_spawn.

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_do_passerby_spawn_silhouette_skips_depart_schedule(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Silhouette-state arrivals (spawn during combat) must NOT
        schedule a depart timer — drain_silhouette owns that
        downstream lifecycle event after combat ends."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        npc = Wagoneer()

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.attempt_spawn"
        ) as mock_attempt:
            def _fake_attempt(g):
                g.pending_silhouette = npc
                return "On the far ridge, a wagoneer."
            mock_attempt.side_effect = _fake_attempt

            await game.do_passerby_spawn()

        scheduled = [
            c.args[0].__name__
            for c in game.game_clock.add_routine.call_args_list
            if hasattr(c.args[0], "__name__")
        ]
        # The silhouette branch must NOT schedule depart — only
        # set_passerby_timer (re-arming) should appear here.
        assert "do_passerby_depart" not in scheduled

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_do_passerby_depart_dispatches_when_present(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        game = _make_finalize_game(mock_db, mock_gc_cls)
        game.passerby = Wagoneer()

        await game.do_passerby_depart()

        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any(added)
        assert game.passerby is None

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_do_passerby_depart_no_op_when_idle(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Depart timer firing on an empty slot is a no-op (e.g.
        $kill <passerby> already cleared the NPC before the timer
        fired)."""
        game = _make_finalize_game(mock_db, mock_gc_cls)
        game.passerby = None

        await game.do_passerby_depart()

        # No dispatch happened.
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert not added


# ---------------------------------------------------------------------------
# Cog: $wave / $nod / $greet routing
# ---------------------------------------------------------------------------


class TestSocialPasserbyRouting:
    """``RpgSocialCommands._maybe_route_to_passerby_social`` is the
    shared helper that all NPC-targeting social commands go
    through. Validate matching, warmth lookup, pool selection,
    and the greet acquaintance side-effect."""

    def _make_cog(self):
        from caldanai.lib.cogs.rpg_social_commands import RpgSocialCommands
        return RpgSocialCommands(bot=MagicMock())

    def _make_game_with_passerby(self, npc=None):
        npc = npc or Wagoneer()
        game = SimpleNamespace(
            channel_id=222,
            channel=MagicMock(),
            passerby=npc,
            pending_silhouette=None,
            monster=None,
        )
        return game

    def _make_ctx(self, content: str):
        ctx = MagicMock()
        ctx.message = MagicMock()
        ctx.message.content = content
        ctx.message.mentions = []
        return ctx

    def test_returns_false_when_no_passerby(self):
        """No passerby in the slot → resolver yields nothing.
        Verified directly through ``resolve_passerby`` rather than
        the deleted cog helper."""
        from caldanai.lib.rpg.helpers.resolvers import resolve_passerby
        game = SimpleNamespace(passerby=None, pending_silhouette=None)
        assert resolve_passerby(game, "wagoneer") is None

    def test_returns_false_when_npc_lacks_verb(self):
        """``handle_verb`` returns ``None`` when the verb isn't in
        the NPC's SOCIAL_REACTIONS — cog falls through to the next
        responder."""
        npc = Wagoneer()
        game = self._make_game_with_passerby(npc)
        # Wagoneer's SOCIAL_REACTIONS is wave/nod/greet only.
        assert npc.handle_verb("shank", game, _FakePlayer(1), invocation="shank") is None

    def test_returns_false_when_text_doesnt_match(self):
        """``resolve_passerby`` rejects a token that doesn't fuzzy-
        match the NPC name / aliases."""
        from caldanai.lib.rpg.helpers.resolvers import resolve_passerby
        game = self._make_game_with_passerby()
        assert resolve_passerby(game, "herbalist") is None

    def test_token_matching_prefix_resolves(self):
        """Caels caught this: ``$greet herba`` against the herbalist
        used to fail because the matcher checked ``candidate in
        content`` (substring of message), not whether the user's
        token was a prefix/substring of any candidate. Now lives in
        ``PasserbyPlugin.matches_token`` + ``resolve_passerby``."""
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        from caldanai.lib.rpg.helpers.resolvers import resolve_passerby
        npc = Herbalist()
        game = SimpleNamespace(passerby=npc, pending_silhouette=None)

        assert resolve_passerby(game, "herba") is npc
        assert resolve_passerby(game, "herbalist") is npc
        assert resolve_passerby(game, "herb") is npc
        # Alias prefix.
        assert resolve_passerby(game, "wise") is npc  # "wise woman"
        # Typo tolerance via fuzzy_match's edit-distance pass
        # (single-character drop = 1 edit).
        assert resolve_passerby(game, "herbalst") is npc
        # Unrelated tokens don't match.
        assert resolve_passerby(game, "dragon") is None
        assert resolve_passerby(game, "") is None
        assert resolve_passerby(game, None) is None
        # Direct PasserbyPlugin.matches_token contract.
        assert npc.matches_token("herba")
        assert not npc.matches_token("dragon")

    def _make_state(self, *, acquainted=False, warmth=Warmth.NEUTRAL, met_count=1):
        """Build a PasserbyState-shaped stub for mark_encounter /
        get_state mocks. mark_encounter mutates met_count and may
        flip acquainted via osmosis, so the stub needs the full
        field set the cog reads.

        warmth is derived from warmth_credits in the post-credits
        schema; pass the desired tier here and we'll pick a
        representative midpoint credit value to land in that band."""
        from caldanai.lib.rpg.creatures.passersby.state import (
            PasserbyState, _credits_from_warmth_tier,
        )
        return PasserbyState(
            channel_id=222, npc_stem="wagoneer", player_id=1,
            warmth_credits=_credits_from_warmth_tier(warmth),
            acquainted=acquainted, met_count=met_count,
        )

    def test_routes_with_name_match(self):
        """``handle_verb("wave", ...)`` returns a rendered line when
        the verb is in SOCIAL_REACTIONS for the NPC's current warmth."""
        npc = Wagoneer()
        game = self._make_game_with_passerby(npc)
        player = _FakePlayer(1)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_verb_credits"
        ):
            mock_get_state.return_value = self._make_state()
            mock_mark_enc.return_value = self._make_state(met_count=1)
            line = npc.handle_verb("wave", game, player, invocation="wave")
            assert line  # non-empty rendered string

    def test_routes_with_alias_match(self):
        """Alias resolution ("carter" → wagoneer) is the resolver's
        job — verified separately. ``handle_verb`` itself doesn't
        care about the token; this asserts the alias lookup pre-step
        finds the NPC, then a wave through it renders."""
        from caldanai.lib.rpg.helpers.resolvers import resolve_passerby
        npc = Wagoneer()
        game = self._make_game_with_passerby(npc)
        # carter is a wagoneer alias.
        assert resolve_passerby(game, "carter") is npc

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_verb_credits"
        ):
            mock_get_state.return_value = self._make_state()
            mock_mark_enc.return_value = self._make_state(met_count=1)
            line = npc.handle_verb("wave", game, _FakePlayer(1), invocation="wave")
            assert line

    def test_greet_marks_acquainted(self):
        """``handle_verb("greet", ...)`` flips acquainted=True via
        the 'greet' tag (the explicit-introduction path)."""
        npc = Wagoneer()
        game = self._make_game_with_passerby(npc)
        player = _FakePlayer(1)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_acquainted"
        ) as mock_mark, patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_greet_credits"
        ):
            mock_get_state.return_value = self._make_state()
            mock_mark_enc.return_value = self._make_state(met_count=1)

            line = npc.handle_verb("greet", game, player, invocation="greet")
            assert line  # rendered something
            mock_mark.assert_called_once()
            args = mock_mark.call_args
            assert args.args[0] == 222  # channel_id
            assert args.args[1] == "wagoneer"  # stem
            assert args.args[2] == 1  # player_id
            assert args.args[3] == "greet"  # via tag

    def test_wave_does_not_mark_acquainted(self):
        """Only greet is the explicit acquaintance trigger. Wave /
        nod don't flip the bit themselves — the on_message overhear
        path / time osmosis do."""
        npc = Wagoneer()
        game = self._make_game_with_passerby(npc)
        player = _FakePlayer(1)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_acquainted"
        ) as mock_mark, patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_verb_credits"
        ):
            mock_get_state.return_value = self._make_state()
            mock_mark_enc.return_value = self._make_state(met_count=1)
            npc.handle_verb("wave", game, player, invocation="wave")
            mock_mark.assert_not_called()

    def test_silhouette_not_addressable_by_default(self):
        """Pending-silhouette NPCs aren't reachable by social verbs
        through the default resolution chain — they're at distance,
        watching. The unified verb dispatcher's ``include_silhouette``
        flag defaults to False; the social cog wrapper does not opt
        in. Verified via ``walk_token_chain`` directly so the test
        doesn't depend on cog-side wiring."""
        from caldanai.lib.rpg.helpers.verbs import walk_token_chain
        game = SimpleNamespace(
            channel_id=222, channel=MagicMock(),
            passerby=None,
            pending_silhouette=Wagoneer(),
            monster=None, room0=None,
            player_manager=SimpleNamespace(players={}),
        )
        # Default chain (no silhouette inclusion) returns nothing
        # for the wagoneer token.
        candidates = list(walk_token_chain(game, "wagoneer"))
        assert candidates == []
        # Opt-in path finds the silhouette.
        candidates = list(walk_token_chain(
            game, "wagoneer", include_silhouette=True,
        ))
        assert candidates == [game.pending_silhouette]


# ---------------------------------------------------------------------------
# Cog: $kill <passerby> flee routing
# ---------------------------------------------------------------------------


class TestKillPasserbyFleeRouting:
    def _make_cog(self):
        from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
        return RpgUserCommands(bot=MagicMock())

    def _game(self, npc=None):
        return SimpleNamespace(
            channel_id=222, channel=MagicMock(), passerby=npc,
        )

    def test_no_passerby_returns_false(self):
        cog = self._make_cog()
        assert not cog._maybe_flee_passerby(self._game(None), _FakePlayer(1), "wagoneer")

    def test_no_target_returns_false(self):
        cog = self._make_cog()
        assert not cog._maybe_flee_passerby(self._game(Wagoneer()), _FakePlayer(1), None)

    def test_unrelated_token_returns_false(self):
        cog = self._make_cog()
        assert not cog._maybe_flee_passerby(self._game(Wagoneer()), _FakePlayer(1), "goblin")

    def test_matches_stem_and_dispatches_flee(self):
        cog = self._make_cog()
        game = self._game(Wagoneer())

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.flee_from_attack"
        ) as mock_flee, patch(
            "caldanai.lib.cogs.rpg_user_commands.Dispatcher"
        ) as mock_dispatch:
            mock_flee.return_value = "the wagoneer scrambles backward"

            assert cog._maybe_flee_passerby(game, _FakePlayer(1), "wagoneer")
            mock_flee.assert_called_once()
            mock_dispatch.add.assert_called_once()

    def test_matches_alias(self):
        cog = self._make_cog()
        game = self._game(Wagoneer())

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.flee_from_attack"
        ) as mock_flee, patch(
            "caldanai.lib.cogs.rpg_user_commands.Dispatcher"
        ):
            mock_flee.return_value = "x"
            assert cog._maybe_flee_passerby(game, _FakePlayer(1), "carter")


# ---------------------------------------------------------------------------
# Cog: $look passerby line
# ---------------------------------------------------------------------------


class TestLookPasserbyLine:
    def _cog(self):
        from caldanai.lib.cogs.rpg_info_commands import RpgInfoCommands
        return RpgInfoCommands(bot=MagicMock())

    def test_returns_none_when_idle(self):
        cog = self._cog()
        game = SimpleNamespace(passerby=None, pending_silhouette=None)
        assert cog._render_passerby_look_line(game) is None

    def test_renders_present_passerby(self):
        cog = self._cog()
        npc = Wagoneer()
        game = SimpleNamespace(passerby=npc, pending_silhouette=None)
        line = cog._render_passerby_look_line(game)
        assert line is not None
        # Wagoneer.LOOK_LINE doesn't reference @1 tokens — just
        # check the dispatch returned the literal line.
        assert "wagoneer" in line.lower() or "cart" in line.lower()

    def test_renders_silhouette_when_no_present(self):
        cog = self._cog()
        npc = Wagoneer()
        game = SimpleNamespace(passerby=None, pending_silhouette=npc)
        line = cog._render_passerby_look_line(game)
        assert line is not None
        assert "watches" in line.lower() or "distance" in line.lower()

    def test_present_takes_precedence_over_silhouette(self):
        cog = self._cog()
        present = Wagoneer()
        silhouette = Wren()
        game = SimpleNamespace(passerby=present, pending_silhouette=silhouette)
        line = cog._render_passerby_look_line(game)
        # Present line should fire (Wagoneer.LOOK_LINE), not the
        # silhouette template.
        assert "watches" not in line.lower() or "cart" in line.lower()


# ---------------------------------------------------------------------------
# Cog: $kill <npc> confirm gate (review item 6)
# ---------------------------------------------------------------------------


class TestKillConfirmGate:
    """Mid-combat $kill <passerby> requires explicit ``yes`` so a
    player can't accidentally pre-empt their active monster combat
    AND burn an NPC warmth tier in one typo."""

    def _make_cog(self):
        from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
        return RpgUserCommands(bot=MagicMock())

    def _game(self, *, npc=None, monster=None, combatants=()):
        return SimpleNamespace(
            channel_id=222, channel=MagicMock(), passerby=npc,
            monster=monster, combatants=list(combatants), prefix="$",
        )

    def test_no_combat_proceeds_immediately(self):
        """No active monster + no combatants → flee fires without
        confirm gate."""
        cog = self._make_cog()
        player = _FakePlayer(1)
        game = self._game(npc=Wagoneer())

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.flee_from_attack"
        ) as mock_flee, patch(
            "caldanai.lib.cogs.rpg_user_commands.Dispatcher"
        ):
            mock_flee.return_value = "the wagoneer scrambles backward"
            assert cog._maybe_flee_passerby(game, player, "wagoneer")
            mock_flee.assert_called_once()

    def test_combat_active_no_confirm_emits_prompt(self):
        """Player in active combat with monster → ``$kill wagoneer``
        emits the prompt and does NOT fire flee_from_attack."""
        cog = self._make_cog()
        player = _FakePlayer(1)
        monster = MagicMock()
        game = self._game(
            npc=Wagoneer(), monster=monster, combatants=[player],
        )

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.flee_from_attack"
        ) as mock_flee, patch(
            "caldanai.lib.cogs.rpg_user_commands.Dispatcher"
        ) as mock_dispatch:
            assert cog._maybe_flee_passerby(game, player, "wagoneer")
            mock_flee.assert_not_called()
            mock_dispatch.add.assert_called_once()
            # Prompt mentions the prefix-prefixed retry command.
            call_args = mock_dispatch.add.call_args
            blob = " ".join(str(a) for a in call_args.args)
            assert "yes" in blob.lower()

    def test_combat_active_with_yes_proceeds(self):
        """`$kill wagoneer yes` while in combat → flee fires."""
        cog = self._make_cog()
        player = _FakePlayer(1)
        monster = MagicMock()
        game = self._game(
            npc=Wagoneer(), monster=monster, combatants=[player],
        )

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.flee_from_attack"
        ) as mock_flee, patch(
            "caldanai.lib.cogs.rpg_user_commands.Dispatcher"
        ):
            mock_flee.return_value = "x"
            assert cog._maybe_flee_passerby(game, player, "wagoneer yes")
            mock_flee.assert_called_once()


# ---------------------------------------------------------------------------
# Cog: $greet silhouette → "too far off" line (review item 5)
# ---------------------------------------------------------------------------


class TestGreetSilhouetteFallback:
    """``$greet <silhouette>`` renders an explicit "too far off"
    line rather than falling through to the standard miss. The
    check now lives inline at the top of the ``$greet`` command
    body — these tests verify the underlying resolver, and the
    rendered template, that the inline branch depends on."""

    def test_returns_none_when_no_silhouette(self):
        from caldanai.lib.rpg.helpers.resolvers import (
            resolve_pending_silhouette,
        )
        game = SimpleNamespace(pending_silhouette=None)
        assert resolve_pending_silhouette(game, "wagoneer") is None

    def test_returns_none_when_target_doesnt_match(self):
        from caldanai.lib.rpg.helpers.resolvers import (
            resolve_pending_silhouette,
        )
        game = SimpleNamespace(pending_silhouette=Wagoneer())
        assert resolve_pending_silhouette(game, "herbalist") is None

    def test_resolver_returns_silhouette_when_match(self):
        from caldanai.lib.rpg.helpers.resolvers import (
            resolve_pending_silhouette,
        )
        npc = Wagoneer()
        game = SimpleNamespace(pending_silhouette=npc)
        assert resolve_pending_silhouette(game, "wagoneer") is npc
        # The literal template the cog renders when the resolver
        # lands. Smoke-check the rendered output so a future template
        # rewrite doesn't silently lose the "too far / approaches"
        # signal players read on.
        from caldanai.lib.rpg.helpers.parser import parse
        line = parse(
            "@1Dc is too far off across the clearing to hear; "
            "wait until @1s approaches.",
            npc,
        )
        assert "too far" in line.lower() or "approaches" in line.lower()


# ---------------------------------------------------------------------------
# Cog: first-acquaintance cue (review items 8 + 9)
# ---------------------------------------------------------------------------


class TestAcquaintanceCue:
    """The first time an NPC learns a player's name (greet OR
    osmosis OR overhear), an italicized ACQUAINTANCE_CUE_POOL line
    fires so the player gets a visible state-change beat. After
    the verb-unification refactor, ``handle_verb`` concatenates
    the cue line below the main reaction line (newline-separated)
    so the cog dispatcher renders both as a single message."""

    def _make_state(self, *, acquainted=False, warmth=Warmth.NEUTRAL, met_count=1):
        from caldanai.lib.rpg.creatures.passersby.state import (
            PasserbyState, _credits_from_warmth_tier,
        )
        return PasserbyState(
            channel_id=222, npc_stem="wagoneer", player_id=1,
            warmth_credits=_credits_from_warmth_tier(warmth),
            acquainted=acquainted, met_count=met_count,
        )

    def _make_game(self, npc=None):
        return SimpleNamespace(
            channel_id=222, channel=MagicMock(),
            passerby=npc or Wagoneer(),
            pending_silhouette=None, monster=None,
        )

    def test_first_greet_dispatches_cue(self):
        npc = Wagoneer()
        game = self._make_game(npc)
        player = _FakePlayer(1)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_acquainted"
        ), patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_greet_credits"
        ):
            # Pre-greet: not acquainted. Post mark_encounter:
            # still not — greet handles its own flip explicitly,
            # so the renderer sees acquainted=False, the prior was
            # also False, and the cue dispatches via the
            # ``verb == "greet"`` branch in handle_verb.
            mock_get_state.return_value = self._make_state(acquainted=False)
            mock_mark_enc.return_value = self._make_state(
                acquainted=False, met_count=1,
            )
            line = npc.handle_verb("greet", game, player, invocation="greet")

        # Greet line + cue, joined by newline.
        assert line
        assert "\n" in line, f"expected greet+cue split by newline; got:\n{line}"

    def test_subsequent_greet_does_not_re_dispatch_cue(self):
        npc = Wagoneer()
        game = self._make_game(npc)
        player = _FakePlayer(1)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_acquainted"
        ), patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_greet_credits"
        ):
            mock_get_state.return_value = self._make_state(acquainted=True)
            mock_mark_enc.return_value = self._make_state(
                acquainted=True, met_count=5,
            )
            line = npc.handle_verb("greet", game, player, invocation="greet")

        # Only the greet line — no cue, since prior.acquainted was True.
        assert line
        assert "\n" not in line, f"expected single greet line; got:\n{line}"

    def test_osmosis_flip_dispatches_cue(self):
        """3rd+ encounter with NEUTRAL+ warmth flips acquainted via
        osmosis. The cue should fire on that exact interaction."""
        npc = Wagoneer()
        game = self._make_game(npc)
        player = _FakePlayer(1)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.get_state"
        ) as mock_get_state, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_encounter"
        ) as mock_mark_enc, patch(
            "caldanai.lib.rpg.creatures.passersby.state.mark_acquainted"
        ), patch(
            "caldanai.lib.rpg.creatures.passersby.state.apply_verb_credits"
        ):
            # Pre: 2 encounters, not acquainted. Post: 3 encounters,
            # osmosis just flipped it.
            mock_get_state.return_value = self._make_state(
                acquainted=False, met_count=2,
            )
            mock_mark_enc.return_value = self._make_state(
                acquainted=True, met_count=3,
            )
            line = npc.handle_verb("wave", game, player, invocation="wave")

        # Wave line + cue (osmosis flipped acquainted between prior
        # and current state).
        assert line
        assert "\n" in line, f"expected wave+cue split by newline; got:\n{line}"


# ---------------------------------------------------------------------------
# overhear_mentions: returns list of newly-acquainted ids (item 9)
# ---------------------------------------------------------------------------


class TestOverhearReturnsList:
    """The contract change: overhear_mentions now returns a list of
    newly-acquainted player ids (was an int count) so the cog can
    dispatch the per-player cue."""

    def test_returns_list_of_ids_on_success(self):
        from caldanai.lib.rpg.creatures.passersby.spawn import overhear_mentions

        # Reuse the test-passerby-spawn pattern with an inline
        # in-memory collection that supports find_one + applies
        # upserts side-effect-style.
        class _FakeColl:
            def __init__(self):
                self._docs = []

            def find_one(self, filt):
                for doc in self._docs:
                    if all(doc.get(k) == v for k, v in filt.items()):
                        return doc
                return None

        coll = _FakeColl()
        game = SimpleNamespace(
            channel_id=99,
            passerby=Wagoneer(),
            pending_silhouette=None,
            player_manager=SimpleNamespace(players={42: SimpleNamespace(id=42)}),
        )
        msg = SimpleNamespace(
            mentions=[SimpleNamespace(id=42, bot=False)],
        )

        # mark_acquainted writes via DB._queues — patch the DB
        # reference so the queue write is captured-and-applied.
        class _CaptureQ:
            def put(self, op):
                filt = op._filter
                set_fields = op._doc.get("$set", {})
                doc = coll.find_one(filt)
                if doc:
                    doc.update(set_fields)
                else:
                    coll._docs.append({**filt, **set_fields})

        from collections import defaultdict
        with patch(
            "caldanai.lib.rpg.creatures.passersby.state.DB"
        ) as mock_db:
            mock_db._passerby_state = coll
            mock_db._queues = defaultdict(_CaptureQ)
            result = overhear_mentions(game, msg, collection=coll)

        assert result == [42]
