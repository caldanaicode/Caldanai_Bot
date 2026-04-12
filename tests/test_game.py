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

class TestDoHealthRegen:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_heals_injured_player(self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch):
        from caldanai.lib.rpg import Game

        guild, channel = _make_game_guild_channel(mock_db)

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild,
            channel=channel,
            use_spawn_timer=False,
            enable_ambience=False,
        )

        player = MagicMock()
        player.health = 15
        player.health_regen = 3
        player.get_health_max.return_value = 20
        player.apply_damage.return_value = ""

        game.player_manager.players = {1: player}
        await game.do_health_regen()

        player.apply_damage.assert_called_once_with(-3)
        # health < max, so health_regen should increment
        assert player.health_regen == 4

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_skips_full_health_player(self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch):
        from caldanai.lib.rpg import Game

        guild, channel = _make_game_guild_channel(mock_db)

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild,
            channel=channel,
            use_spawn_timer=False,
            enable_ambience=False,
        )

        player = MagicMock()
        player.health = 20
        player.health_regen = 5
        player.get_health_max.return_value = 20

        game.player_manager.players = {1: player}
        await game.do_health_regen()

        player.apply_damage.assert_not_called()
        # At full health, regen resets to 0
        assert player.health_regen == 0

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_resurrects_dead_player(self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch):
        from caldanai.lib.rpg import Game

        guild, channel = _make_game_guild_channel(mock_db)

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild,
            channel=channel,
            use_spawn_timer=False,
            enable_ambience=False,
        )

        player = MagicMock()
        player.health = 0
        player.health_regen = 2
        player.get_health_max.return_value = 20
        player.apply_damage.return_value = "gasps as life returns"

        game.player_manager.players = {1: player}
        await game.do_health_regen()

        player.apply_damage.assert_called_once_with(-2)
        # Still below max (health is mocked at 0, so remains < 20), regen increments
        assert player.health_regen == 3
        # Dispatcher should have been called with the resurrection message
        mock_dispatch.add.assert_called_once()


# ---------------------------------------------------------------------------
# cancel_combat
# ---------------------------------------------------------------------------

class TestCancelCombat:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_cancel_combat_clears_state(self, mock_gc_cls, mock_pm_cls, mock_db):
        from caldanai.lib.rpg import Game

        guild, channel = _make_game_guild_channel(mock_db)

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild,
            channel=channel,
            use_spawn_timer=False,
            enable_ambience=False,
        )
        game.monster = MagicMock()
        game.combatants = [MagicMock(), MagicMock()]
        game.loot = {1: [MagicMock()]}
        game.looters = [MagicMock()]

        # Patch set_spawn_timer to avoid side effects
        game.set_spawn_timer = AsyncMock()

        await game.cancel_combat()

        assert game.monster is None
        assert len(game.combatants) == 0
        assert len(game.loot) == 0
        assert len(game.looters) == 0
        game.set_spawn_timer.assert_awaited_once()
