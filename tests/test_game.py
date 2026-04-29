"""Tests for Caldanai.lib.rpg (Game class)."""

from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest


def _make_game_dict(**overrides):
    """Return a minimal valid game dict for from_dict."""
    d = {
        "_id": "game123",
        "guild_id": 111,
        "channel_id": 222,
        "use_spawn_timer": False,
        "spawn_duration": 10,
        "loot_duration": 5,
        "spawn_timer_range": [600, 3600],
        "enable_ambience": False,
        "game_time": 0,
    }
    d.update(overrides)
    return d


def _make_game_guild_channel(mock_db):
    """Create standard guild/channel mocks and configure mock_db."""
    guild = MagicMock()
    guild.id = 111
    guild.roles = []
    channel = MagicMock()
    channel.id = 222
    mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}
    return guild, channel


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------

class TestGameSerialization:
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_to_dict_keys(self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch):
        from caldanai.lib.rpg import Game

        guild, channel = _make_game_guild_channel(mock_db)

        # Configure the GameClock mock so to_dict can call game_clock.get_seconds()
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild,
            channel=channel,
            game_id="game123",
            use_spawn_timer=False,
            enable_ambience=False,
        )
        d = game.to_dict()
        assert d["guild_id"] == 111
        assert d["channel_id"] == 222
        assert "channel_id" in d  # verify key name is channel_id not channel
        assert d["_id"] == "game123"

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_to_dict_omits_id_when_none(self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch):
        from caldanai.lib.rpg import Game

        guild, channel = _make_game_guild_channel(mock_db)

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild,
            channel=channel,
            game_id=None,
            use_spawn_timer=False,
            enable_ambience=False,
        )
        d = game.to_dict()
        assert "_id" not in d


# ---------------------------------------------------------------------------
# from_dict null guards
# ---------------------------------------------------------------------------

class TestFromDictNullGuards:
    @pytest.mark.asyncio
    async def test_from_dict_none_dict_returns_none(self):
        from caldanai.lib.rpg import Game
        result = await Game.from_dict(None, MagicMock())
        assert result is None

    @pytest.mark.asyncio
    async def test_from_dict_none_bot_returns_none(self):
        from caldanai.lib.rpg import Game
        result = await Game.from_dict(_make_game_dict(), None)
        assert result is None

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_from_dict_none_guild_returns_none(self, mock_gc_cls, mock_db):
        from caldanai.lib.rpg import Game

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        bot = MagicMock()
        bot.get_guild.return_value = None
        bot.get_channel.return_value = MagicMock()
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}

        result = await Game.from_dict(_make_game_dict(), bot)
        assert result is None

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_from_dict_none_channel_returns_none(self, mock_gc_cls, mock_db):
        from caldanai.lib.rpg import Game

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        bot = MagicMock()
        bot.get_guild.return_value = MagicMock()
        bot.get_channel.return_value = None
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}

        result = await Game.from_dict(_make_game_dict(), bot)
        assert result is None


# ---------------------------------------------------------------------------
# from_dict dead player kickstart
# ---------------------------------------------------------------------------

class TestFromDictDeadPlayerKickstart:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_dead_player_gets_health_regen_set(self, mock_gc_cls, mock_db):
        from caldanai.lib.rpg import Game

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        bot = MagicMock()
        guild = MagicMock()
        guild.id = 111
        guild.name = "TestGuild"
        guild.roles = []
        channel = MagicMock()
        channel.id = 222

        bot.get_guild.return_value = guild
        bot.get_channel.return_value = channel
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}
        mock_db.find_players_by_guild_id.return_value = []

        # Create a dead player mock
        dead_player = MagicMock()
        dead_player.health = 0
        dead_player.health_regen = 0
        dead_player.is_dead.return_value = True

        alive_player = MagicMock()
        alive_player.health = 20
        alive_player.health_regen = 0
        alive_player.is_dead.return_value = False

        # Patch PlayerManager where Game imports it so __init__ creates
        # our mock instance instead of a real one.
        with patch("caldanai.lib.rpg.PlayerManager") as mock_pm_cls:
            pm_instance = MagicMock()
            pm_instance.load_players = AsyncMock()
            pm_instance.players = {1: dead_player, 2: alive_player}
            pm_instance.update_inactive_roles = AsyncMock()
            mock_pm_cls.return_value = pm_instance

            game = await Game.from_dict(_make_game_dict(), bot)

        assert dead_player.health_regen == 1
        assert alive_player.health_regen == 0


# ---------------------------------------------------------------------------
# do_health_regen
# ---------------------------------------------------------------------------
# Relocated to tests/test_player_manager.py alongside the method it
# exercises (PlayerManager.do_health_regen). Game no longer owns the
# regen routine — it only schedules it on the clock.


# ---------------------------------------------------------------------------
# end_combat / cancel_combat / kill_monster
# ---------------------------------------------------------------------------

def _make_combat_game(mock_db, mock_gc_cls):
    """Create a Game with active combat state for cleanup tests."""
    guild, channel = _make_game_guild_channel(mock_db)

    mock_gc = MagicMock()
    mock_gc.get_seconds.return_value = 0
    mock_gc.time_scale = 4
    mock_gc_cls.return_value = mock_gc

    from caldanai.lib.rpg import Game
    game = Game(
        guild=guild,
        channel=channel,
        use_spawn_timer=False,
        enable_ambience=False,
    )
    monster = MagicMock()
    monster.death = "The creature falls."
    game.monster = monster
    game.combatants = [MagicMock(), MagicMock()]
    game.combat_targets = {1: ["head"], 2: ["torso"]}
    game.loot = {1: [MagicMock()]}
    game.looters = [MagicMock()]

    game.player_manager.clear_combat_roles = AsyncMock()
    game.set_spawn_timer = AsyncMock()
    # ``cancel_combat`` reads ``roles[Roles.COMBAT_MAIN].mention``
    # to build the loot-announce prompt when there's salvage in
    # the pool. Stub the role so flee-with-loot tests don't
    # KeyError on the lookup.
    from caldanai.lib.rpg.helpers.enums import Roles
    combat_role = MagicMock()
    combat_role.mention = "@combat"
    game.player_manager.roles = {Roles.COMBAT_MAIN: combat_role}
    return game


class TestEndCombat:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_clears_all_combat_state(self, mock_gc_cls, mock_pm_cls, mock_db):
        game = _make_combat_game(mock_db, mock_gc_cls)
        await game.end_combat()

        assert game.monster is None
        assert len(game.combatants) == 0
        assert len(game.combat_targets) == 0
        assert len(game.looters) == 0
        game.player_manager.clear_combat_roles.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_does_not_touch_loot(self, mock_gc_cls, mock_pm_cls, mock_db):
        """Loot is the caller's responsibility — end_combat leaves it."""
        game = _make_combat_game(mock_db, mock_gc_cls)
        loot_before = dict(game.loot)
        await game.end_combat()
        assert game.loot == loot_before

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_idempotent_when_no_combat(self, mock_gc_cls, mock_pm_cls, mock_db):
        game = _make_combat_game(mock_db, mock_gc_cls)
        game.monster = None
        game.combatants.clear()
        game.looters.clear()
        await game.end_combat()
        assert game.monster is None


class TestCancelCombat:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_cancel_combat_clears_state_but_preserves_salvage(self, mock_gc_cls, mock_pm_cls, mock_db):
        """``cancel_combat`` (monster fleeing) clears combat state
        but preserves any mid-combat salvage already accumulated
        in ``Game.loot``. Players keep what they earned even when
        the monster bolts. Pre-Phase-2 this method also called
        ``self.loot.clear()``; that erased legitimate dismemberment
        loot and was removed once salvage drops became a thing."""
        game = _make_combat_game(mock_db, mock_gc_cls)
        # Seed mid-combat salvage to verify it's preserved.
        game.loot[42] = ["pre-existing salvage item"]
        await game.cancel_combat()

        assert game.monster is None
        assert len(game.combatants) == 0
        assert len(game.looters) == 0
        # Salvage survives the flee.
        assert game.loot[42] == ["pre-existing salvage item"]
        game.set_spawn_timer.assert_awaited_once()
        game.player_manager.clear_combat_roles.assert_awaited_once()


class TestCheckTimeFlee:
    """``check_time`` is the second flee path: a ``flees_from_time``
    monster (werewolf at dawn, spirit at sunset) bolts when the
    current time-of-day stops overlapping its ``time_partition``.
    Until the 2026-04-27 consolidation, this path bypassed the
    loot-announce + ``loot_expires`` schedule entirely — only
    ``do_combat``'s SURVIVE/VENGEFUL escape branch had it inline.
    Player report flagged the gap (werewolf bolted at dawn with
    leather still in the pool, no prompt).

    The fix routes both paths through ``cancel_combat`` →
    ``_finalize_combat``, which returns the announce string for
    the caller to append to its own narration. These tests pin
    that contract: time-flee with salvage in pool emits the
    prompt; time-flee with empty pool stays silent.
    """

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_time_flee_with_salvage_emits_loot_prompt(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """A flees_from_time monster bolting with mid-combat
        salvage in ``self.loot`` should fire the same announce
        prompt the SURVIVE-flee branch already does."""
        game = _make_combat_game(mock_db, mock_gc_cls)

        # Configure the monster as flees_from_time, with a
        # ``time_partition`` that DOESN'T overlap the current
        # time-of-day → ``flee=True`` in check_time. Mock the
        # specific attributes check_time reads.
        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        # ``NIGHT`` only — a "DAY" current TOD won't overlap.
        game.monster.flees_from_time = True
        game.monster.dies_from_time = False
        game.monster.time_partition = TimesOfDay.NIGHT.value
        game.monster.time_flee = "@1d bolts for cover at sunrise."
        game.monster.is_dead.return_value = False

        # GameClock returns are read directly — flee triggers when
        # current TOD's flag isn't in time_partition.
        game.game_clock.get_time_of_day.return_value = "NOON"
        game.game_clock.get_time_components.return_value = (12, 0, 0)
        game.game_clock.get_next_time.return_value = ("AFTERNOON", 14, 0)
        game.game_clock.remove_routine = MagicMock()
        game.game_clock.add_routine = MagicMock()

        # Seed mid-combat salvage so the announce path fires.
        game.loot[42] = ["a leather"]

        await game.check_time()

        # Dispatcher.add called with a message that includes the
        # bolt narration AND the loot prompt. The prompt fragment
        # is stable enough across phrasing changes to assert on.
        all_calls = [
            str(call.args[1]) for call in mock_dispatch.add.call_args_list
            if len(call.args) >= 2
        ]
        blob = "\n".join(all_calls)
        assert "bolts for cover" in blob, (
            f"expected the time_flee narration in dispatch; got:\n{blob}"
        )
        assert "There might be something to" in blob, (
            f"expected the loot announce in dispatch; got:\n{blob}"
        )
        # Salvage preserved.
        assert game.loot[42] == ["a leather"]

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_time_flee_with_only_stale_pool_no_loot_prompt(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Loot from a PRIOR encounter still in the pool but THIS
        combat dropped nothing fresh (e.g., sheep walk-off, dragon
        fly-off). The post-flee prompt should stay silent — the old
        loot already had its own announce; firing again would
        mislead the player into thinking the runaway dropped
        something. Regression for the 2026-04-29 bug Caels caught
        live: sheep walked off and the prompt fired even though the
        sheep dropped nothing; the leftover items in pool were
        Vael's overburdened-from-prior-bandit stash.
        """
        game = _make_combat_game(mock_db, mock_gc_cls)

        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        game.monster.flees_from_time = True
        game.monster.dies_from_time = False
        game.monster.time_partition = TimesOfDay.NIGHT.value
        game.monster.time_flee = "@1d bolts for cover at sunrise."
        game.monster.is_dead.return_value = False

        game.game_clock.get_time_of_day.return_value = "NOON"
        game.game_clock.get_time_components.return_value = (12, 0, 0)
        game.game_clock.get_next_time.return_value = ("AFTERNOON", 14, 0)
        game.game_clock.remove_routine = MagicMock()
        game.game_clock.add_routine = MagicMock()

        # Pool has stale loot from a prior encounter; size_at_start
        # snapshot captured the same value at combat begin, so the
        # diff (current - start) is zero — nothing fresh added.
        game.loot.clear()
        game.loot[42] = ["a leftover stick"]
        game.combat.loot_size_at_start = 1

        await game.check_time()

        all_calls = [
            str(call.args[1]) for call in mock_dispatch.add.call_args_list
            if len(call.args) >= 2
        ]
        blob = "\n".join(all_calls)
        assert "bolts for cover" in blob
        assert "There might be something to" not in blob, (
            f"unexpected loot prompt when pool size unchanged "
            f"(stale leftovers, no fresh drops); got:\n{blob}"
        )
        # Stale loot itself preserved (cleanup is loot_expires's
        # job, not the announce path's).
        assert game.loot[42] == ["a leftover stick"]

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_time_flee_with_empty_pool_no_loot_prompt(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Empty loot pool → time-flee narration only, no loot
        prompt (no announce when there's nothing to claim).
        """
        game = _make_combat_game(mock_db, mock_gc_cls)

        from caldanai.lib.rpg.helpers.enums import TimesOfDay
        game.monster.flees_from_time = True
        game.monster.dies_from_time = False
        game.monster.time_partition = TimesOfDay.NIGHT.value
        game.monster.time_flee = "@1d bolts for cover at sunrise."
        game.monster.is_dead.return_value = False

        game.game_clock.get_time_of_day.return_value = "NOON"
        game.game_clock.get_time_components.return_value = (12, 0, 0)
        game.game_clock.get_next_time.return_value = ("AFTERNOON", 14, 0)
        game.game_clock.remove_routine = MagicMock()
        game.game_clock.add_routine = MagicMock()

        # Empty loot pool — no announce should fire.
        game.loot.clear()

        await game.check_time()

        all_calls = [
            str(call.args[1]) for call in mock_dispatch.add.call_args_list
            if len(call.args) >= 2
        ]
        blob = "\n".join(all_calls)
        assert "bolts for cover" in blob
        assert "There might be something to" not in blob, (
            f"unexpected loot prompt in empty-pool flee; got:\n{blob}"
        )


class TestKillMonster:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_kill_monster_drops_no_loot(self, mock_gc_cls, mock_pm_cls, mock_db):
        """Admin kill clears loot and does not generate new loot."""
        game = _make_combat_game(mock_db, mock_gc_cls)
        await game.kill_monster()

        assert game.monster is None
        assert len(game.loot) == 0
        game.set_spawn_timer.assert_awaited_once()
        game.player_manager.clear_combat_roles.assert_awaited_once()


# ---------------------------------------------------------------------------
# Channel routing (Game._channel_routes + for_channel)
# ---------------------------------------------------------------------------


class TestChannelRouting:
    """``Game._channel_routes`` maps Discord channel ids to their owning
    Game so arbitrary subsystems can find the game a channel belongs
    to without holding a Game reference. Primary channel is auto-
    registered at construction; dungeon / thread channels extend via
    ``register_channel``."""

    def setup_method(self):
        from caldanai.lib.rpg import Game
        Game._channel_routes.clear()

    def teardown_method(self):
        from caldanai.lib.rpg import Game
        Game._channel_routes.clear()

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_primary_channel_auto_registered(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        assert game.channel_id == channel.id
        assert Game.for_channel(channel.id) is game

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_register_channel_adds_route(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        # Simulate a dungeon thread opening at channel_id 9999.
        game.register_channel(9999)
        assert Game.for_channel(9999) is game

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_unregister_channel_removes_route(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        game.register_channel(9999)
        game.unregister_channel(9999)
        assert Game.for_channel(9999) is None
        # Primary channel still routes (unregister only touches 9999).
        assert Game.for_channel(channel.id) is game

    def test_for_channel_returns_none_for_unknown_channel(self):
        from caldanai.lib.rpg import Game
        assert Game.for_channel(424242) is None


# ---------------------------------------------------------------------------
# monster_statics counter semantics
# ---------------------------------------------------------------------------

class TestMonsterStatics:
    """Guards the counter-bump behavior used from on_time_change /
    do_combat / end_combat. All three sites rely on incrementing a
    missing key yielding 1. If monster_statics ever regresses to a
    plain dict, ``d[key] += 1`` on a missing key will raise KeyError."""

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_bump_missing_key_starts_at_one(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        # Mirror the idiom used at all three counter-bump sites.
        game.monster_statics["goblin.killed"] += 1
        assert game.monster_statics["goblin.killed"] == 1

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_repeat_bumps_accumulate(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        game.monster_statics["goblin.killed"] += 1
        game.monster_statics["goblin.killed"] += 1
        game.monster_statics["goblin.escaped"] += 1
        assert game.monster_statics["goblin.killed"] == 2
        assert game.monster_statics["goblin.escaped"] == 1

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_monster_statics_not_serialized(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """monster_statics is intentionally NOT serialized (utils.update_statics
        drains it to the DB statistics collection directly). Confirm that
        bumping entries does not leak into to_dict output."""
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel, game_id="gid",
            use_spawn_timer=False, enable_ambience=False,
        )
        game.monster_statics["goblin.killed"] += 3
        d = game.to_dict()
        assert "monster_statics" not in d

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_bump_survives_drain_reset(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Regression guard for helpers/utils.py::update_statics: after the
        drain-and-reset swap, the next bump on an empty counter must still
        start at 1. A reset back to plain dict would KeyError here."""
        from collections import Counter
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        game.monster_statics["goblin.killed"] += 1
        # Mirror the swap-and-reset in helpers/utils.py::update_statics.
        _, game.monster_statics = game.monster_statics, Counter()
        game.monster_statics["goblin.killed"] += 1
        assert game.monster_statics["goblin.killed"] == 1


# ---------------------------------------------------------------------------
# Player lookup shims
# ---------------------------------------------------------------------------

class TestPlayerLookupShims:
    """``Game.get_player_by_user_id`` is a thin façade over
    ``player_manager.players`` so callers outside PlayerManager don't
    reach into the underlying dict shape."""

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_get_player_by_user_id_returns_player_when_present(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc
        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        sentinel = MagicMock(name="player_42")
        game.player_manager.players = {42: sentinel}
        assert game.get_player_by_user_id(42) is sentinel

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_get_player_by_user_id_returns_none_when_absent(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc
        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        game.player_manager.players = {}
        assert game.get_player_by_user_id(999) is None


# ---------------------------------------------------------------------------
# Ambience kill-switch split: master + per-subsystem flags
# ---------------------------------------------------------------------------


class TestAmbienceEnabled:
    """``Game.ambience_enabled(subsystem)`` returns the effective
    on/off state for each subsystem — master ANDed with the per-
    subsystem flag. Either side being ``False`` suppresses the
    subsystem; only both being ``True`` lets it emit."""

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_master_off_suppresses_all_subsystems(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc
        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False,
            enable_ambience=False,
            enable_ambience_local=True,
            enable_ambience_celestial=True,
            enable_ambience_weather=True,
        )
        for subsystem in Game.AMBIENCE_SUBSYSTEMS:
            assert game.ambience_enabled(subsystem) is False, (
                f"master=False should suppress {subsystem} even when its own flag is True"
            )

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_subsystem_off_suppresses_only_itself(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.get_season.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc
        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False,
            enable_ambience=True,
            enable_ambience_local=False,
            enable_ambience_celestial=True,
            enable_ambience_weather=True,
        )
        assert game.ambience_enabled("local") is False
        assert game.ambience_enabled("celestial") is True
        assert game.ambience_enabled("weather") is True

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_unknown_subsystem_falls_back_to_master_only(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """A subsystem name not registered on the Game treats its
        per-subsystem flag as ``True`` — adding a new subsystem in
        code without first adding its flag shouldn't silently
        disable it."""
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.get_season.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc
        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=True,
        )
        assert game.ambience_enabled("not_a_real_subsystem") is True
        game.enable_ambience = False
        assert game.ambience_enabled("not_a_real_subsystem") is False


class TestAmbiencePersistence:
    """Ambience subsystem flags must round-trip through ``to_dict``
    and be restorable via ``from_dict`` defaults when absent (pre-
    split documents shouldn't load with subsystems silently off)."""

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_to_dict_emits_all_subsystem_flags(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game
        guild, channel = _make_game_guild_channel(mock_db)
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.get_season.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc
        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False,
            enable_ambience=True,
            enable_ambience_local=False,
            enable_ambience_celestial=True,
            enable_ambience_weather=False,
        )
        d = game.to_dict()
        assert d["enable_ambience"] is True
        assert d["enable_ambience_local"] is False
        assert d["enable_ambience_celestial"] is True
        assert d["enable_ambience_weather"] is False

