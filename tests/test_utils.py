"""Tests for Caldanai.lib.rpg.helpers.utils — generate_report, cache_auth, save_game_data."""

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

import Caldanai.lib.rpg.helpers.utils as utils_module
from Caldanai.lib.rpg.helpers.utils import generate_report, cache_auth, save_game_data, RpgUtilities


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport:
    @patch("Caldanai.lib.rpg.helpers.utils.smtplib.SMTP")
    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    def test_generate_report_with_db_auth(self, mock_db, mock_smtp):
        mock_db.get_auth.return_value = {
            "DEV_EMAIL": "dev@test.com",
            "SMTP_USER": "smtp@test.com",
            "SMTP_PASSWORD": "password",
            "SMS_EMAIL": "sms@test.com",
        }
        smtp_instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=smtp_instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = generate_report(
            author_id=123,
            author_display_name="Tester",
            message="Something went wrong",
        )
        assert result is True
        assert smtp_instance.starttls.called
        assert smtp_instance.login.called
        assert smtp_instance.send_message.call_count == 2  # email + SMS

    @patch("Caldanai.lib.rpg.helpers.utils.smtplib.SMTP")
    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    def test_generate_report_with_cached_auth(self, mock_db, mock_smtp):
        # DB auth fails, fall back to cache
        mock_db.get_auth.side_effect = Exception("DB down")
        utils_module._cached_auth = {
            "DEV_EMAIL": "dev@test.com",
            "SMTP_USER": "smtp@test.com",
            "SMTP_PASSWORD": "password",
            "SMS_EMAIL": "sms@test.com",
        }
        smtp_instance = MagicMock()
        mock_smtp.return_value.__enter__ = MagicMock(return_value=smtp_instance)
        mock_smtp.return_value.__exit__ = MagicMock(return_value=False)

        result = generate_report(
            author_id=123,
            author_display_name="Tester",
            message="fallback test",
        )
        assert result is True

        # Clean up
        utils_module._cached_auth = None

    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    def test_generate_report_no_auth_returns_false(self, mock_db):
        mock_db.get_auth.return_value = None
        utils_module._cached_auth = None

        result = generate_report(
            author_id=123,
            author_display_name="Tester",
            message="no auth",
        )
        assert result is False


# ---------------------------------------------------------------------------
# cache_auth
# ---------------------------------------------------------------------------

class TestCacheAuth:
    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    def test_cache_auth_success(self, mock_db):
        utils_module._cached_auth = None
        mock_db.get_auth.return_value = {
            "DEV_EMAIL": "dev@test.com",
            "SMTP_USER": "smtp@test.com",
            "SMTP_PASSWORD": "pw",
            "SMS_EMAIL": "sms@test.com",
        }
        cache_auth()
        assert utils_module._cached_auth is not None
        assert utils_module._cached_auth["DEV_EMAIL"] == "dev@test.com"

        # Clean up
        utils_module._cached_auth = None

    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    def test_cache_auth_db_returns_none(self, mock_db):
        utils_module._cached_auth = None
        mock_db.get_auth.return_value = None
        cache_auth()
        assert utils_module._cached_auth is None

    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    def test_cache_auth_db_raises(self, mock_db):
        utils_module._cached_auth = None
        mock_db.get_auth.side_effect = Exception("connection refused")
        cache_auth()
        assert utils_module._cached_auth is None


# ---------------------------------------------------------------------------
# save_game_data loop logic
# ---------------------------------------------------------------------------

class TestSaveGameData:
    @pytest.mark.asyncio
    @patch("Caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    async def test_dirty_players_saved(self, mock_db, mock_rpg):
        player_dirty = MagicMock()
        player_dirty.is_dirty = True
        player_dirty.user_id = 1
        player_dirty.to_dict.return_value = {"user_id": 1}
        player_dirty.id = "abc"

        player_clean = MagicMock()
        player_clean.is_dirty = False
        player_clean.user_id = 2
        player_clean.id = "def"

        game = MagicMock()
        game.guild.id = 999
        game.to_dict.return_value = {"guild_id": 999}
        game.player_manager.players.values.return_value = [player_dirty, player_clean]

        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        # save_game_data is a discord.ext.tasks.Loop; call the underlying coro
        coro = save_game_data.coro if hasattr(save_game_data, "coro") else save_game_data
        await coro()

        # Game data always saved
        mock_db.update_game.assert_called_once_with(999, {"guild_id": 999})

        # Only dirty player saved
        mock_db.update_player.assert_called_once_with(999, 1, {"user_id": 1})
        assert player_dirty.is_dirty is False

    @pytest.mark.asyncio
    @patch("Caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    async def test_clean_players_skipped(self, mock_db, mock_rpg):
        player = MagicMock()
        player.is_dirty = False
        player.user_id = 5
        player.id = "xyz"

        game = MagicMock()
        game.guild.id = 100
        game.to_dict.return_value = {}
        game.player_manager.players.values.return_value = [player]

        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        coro = save_game_data.coro if hasattr(save_game_data, "coro") else save_game_data
        await coro()

        mock_db.update_player.assert_not_called()

    @pytest.mark.asyncio
    @patch("Caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("Caldanai.lib.rpg.helpers.utils.DB")
    async def test_new_player_id_resolved(self, mock_db, mock_rpg):
        new_player = MagicMock()
        new_player.id = None
        new_player.guild_id = 50
        new_player.user_id = 7

        mock_db.get_player.return_value = MagicMock(id="resolved_id")

        game = MagicMock()
        game.guild.id = 50
        game.to_dict.return_value = {}
        game.player_manager.players.values.return_value = []

        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = {new_player}
        mock_rpg.update_statics = MagicMock()

        coro = save_game_data.coro if hasattr(save_game_data, "coro") else save_game_data
        await coro()

        mock_db.get_player.assert_called_once_with(50, 7)
        assert new_player.id == "resolved_id"
