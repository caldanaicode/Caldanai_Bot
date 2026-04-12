"""Shared fixtures for Caldanai Bot tests."""

import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Mock environment variables before any Caldanai modules are imported.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_env(monkeypatch):
    """Provide default env vars so modules can import without a real .env file."""
    monkeypatch.setenv("DB_CONNECTION", "mongodb://localhost:27017")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("STAGE", "TEST")


# ---------------------------------------------------------------------------
# Discord mocks
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_guild():
    guild = MagicMock()
    guild.id = 123456789
    guild.name = "Test Guild"
    guild.icon = MagicMock()
    guild.icon.url = "https://example.com/icon.png"
    guild.roles = []
    guild.get_member = MagicMock(return_value=None)
    guild.fetch_member = AsyncMock(return_value=None)
    guild.fetch_roles = AsyncMock(return_value=[])
    guild.create_role = AsyncMock()
    return guild


@pytest.fixture
def mock_channel():
    channel = MagicMock()
    channel.id = 987654321
    channel.send = AsyncMock()
    return channel


@pytest.fixture
def mock_member():
    member = MagicMock()
    member.id = 111222333
    member.display_name = "TestPlayer"
    member.roles = []
    member.add_roles = AsyncMock()
    member.remove_roles = AsyncMock()
    member.bot = False
    return member


@pytest.fixture
def mock_ctx(mock_guild, mock_channel, mock_member):
    ctx = MagicMock()
    ctx.guild = mock_guild
    ctx.channel = mock_channel
    ctx.author = mock_member
    ctx.prefix = "$"
    ctx.message = MagicMock()
    ctx.message.mentions = []
    ctx.command = MagicMock()
    ctx.command.qualified_name = "test"
    ctx.invoked_with = "test"
    return ctx


# ---------------------------------------------------------------------------
# Database mock
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_db():
    """Patches the DB class so no real MongoDB connection is needed."""
    with patch("caldanai.db.DB") as db:
        db._is_connected = True
        db.get_auth.return_value = {
            "TOKEN": "fake-token",
            "OWNER_IDS": [111222333],
            "DEV_EMAIL": "dev@test.com",
            "SMTP_USER": "smtp@test.com",
            "SMTP_PASSWORD": "password",
            "SMS_EMAIL": "sms@test.com",
        }
        db.get_server_by_guild_id.return_value = {"prefix": "$"}
        db.find_all_games.return_value = []
        db.find_players_by_guild_id.return_value = []
        db.get_player.return_value = None
        db.get_game_by_guild_id.return_value = None
        yield db
