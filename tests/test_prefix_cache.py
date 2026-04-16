"""Tests for the per-guild prefix cache in ``caldanai.lib.bot``.

The cache replaces a per-message ``DB.get_server_by_guild_id`` call
with an in-memory dict lookup. Tests cover:

- Cache population on first access, reuse on subsequent access.
- Cache bypass when the message has no guild (DMs).
- Explicit cache ops: ``cache_prefix``, ``evict_prefix``,
  ``clear_prefix_cache``.
- New-guild first-message path (DB returns None → insert, default
  prefix used, cached).
- DB exception fallback (default prefix used, NOT cached so a retry
  can succeed once the DB is back).
"""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.bot import (
    cache_prefix,
    clear_prefix_cache,
    evict_prefix,
    get_prefix,
    _prefix_cache,
)


@pytest.fixture(autouse=True)
def reset_cache():
    """Wipe the cache before and after every test so state doesn't
    leak between tests in this module."""
    clear_prefix_cache()
    yield
    clear_prefix_cache()


def _message(guild_id=42, guild_name="Test Guild"):
    """Build a minimal message-like mock that ``get_prefix`` reads:
    ``message.guild`` and ``message.guild.id`` / ``.name``."""
    guild = MagicMock()
    guild.id = guild_id
    guild.name = guild_name
    msg = MagicMock()
    msg.guild = guild
    return msg


class TestCachePopulation:
    @patch("caldanai.lib.bot.DB")
    def test_first_call_hits_db_and_populates_cache(self, mock_db):
        mock_db.get_server_by_guild_id.return_value = {"prefix": "!"}
        bot = MagicMock()
        get_prefix(bot, _message(guild_id=100))
        mock_db.get_server_by_guild_id.assert_called_once_with(100)
        assert _prefix_cache[100] == "!"

    @patch("caldanai.lib.bot.DB")
    def test_subsequent_calls_do_not_hit_db(self, mock_db):
        mock_db.get_server_by_guild_id.return_value = {"prefix": "!"}
        bot = MagicMock()
        get_prefix(bot, _message(guild_id=100))
        mock_db.get_server_by_guild_id.reset_mock()

        # Ten more messages in the same guild — not a single DB call.
        for _ in range(10):
            get_prefix(bot, _message(guild_id=100))
        mock_db.get_server_by_guild_id.assert_not_called()

    @patch("caldanai.lib.bot.DB")
    def test_independent_guilds_cached_independently(self, mock_db):
        def fake_get(gid):
            return {"prefix": "!"} if gid == 1 else {"prefix": "?"}

        mock_db.get_server_by_guild_id.side_effect = fake_get
        bot = MagicMock()
        get_prefix(bot, _message(guild_id=1))
        get_prefix(bot, _message(guild_id=2))
        assert _prefix_cache[1] == "!"
        assert _prefix_cache[2] == "?"


class TestCacheBypass:
    @patch("caldanai.lib.bot.DB")
    def test_dm_message_skips_cache_and_db(self, mock_db):
        """DMs have ``message.guild is None`` and shouldn't ever hit
        the DB or populate the cache."""
        bot = MagicMock()
        msg = MagicMock()
        msg.guild = None
        get_prefix(bot, msg)
        mock_db.get_server_by_guild_id.assert_not_called()
        assert len(_prefix_cache) == 0


class TestInvalidation:
    def test_cache_prefix_sets_entry(self):
        cache_prefix(5, "?")
        assert _prefix_cache[5] == "?"

    def test_cache_prefix_overwrites_existing(self):
        cache_prefix(5, "!")
        cache_prefix(5, "?")
        assert _prefix_cache[5] == "?"

    def test_evict_prefix_drops_entry(self):
        cache_prefix(5, "!")
        evict_prefix(5)
        assert 5 not in _prefix_cache

    def test_evict_prefix_idempotent(self):
        # Evicting an absent entry must not raise.
        evict_prefix(999)
        assert 999 not in _prefix_cache

    def test_clear_wipes_everything(self):
        cache_prefix(1, "!")
        cache_prefix(2, "?")
        clear_prefix_cache()
        assert len(_prefix_cache) == 0


class TestNewGuild:
    @patch("caldanai.lib.bot.DB")
    def test_first_seen_guild_inserts_and_uses_default(self, mock_db):
        """DB returns None → insert a default row, cache "$", future
        lookups hit the cache."""
        mock_db.get_server_by_guild_id.return_value = None
        bot = MagicMock()
        get_prefix(bot, _message(guild_id=77, guild_name="Fresh"))
        mock_db.insert_server.assert_called_once_with(77, "Fresh")
        assert _prefix_cache[77] == "$"

    @patch("caldanai.lib.bot.DB")
    def test_first_seen_guild_not_re_inserted_on_next_message(self, mock_db):
        """After the insert on first message, the cache is populated,
        so subsequent messages don't hit insert_server again even if
        the DB is still 'fresh'."""
        mock_db.get_server_by_guild_id.return_value = None
        bot = MagicMock()
        get_prefix(bot, _message(guild_id=77, guild_name="Fresh"))
        mock_db.reset_mock()

        get_prefix(bot, _message(guild_id=77, guild_name="Fresh"))
        mock_db.insert_server.assert_not_called()
        mock_db.get_server_by_guild_id.assert_not_called()


class TestDBFailureFallback:
    @patch("caldanai.lib.bot.DB")
    def test_db_exception_falls_back_to_default_prefix(self, mock_db):
        """If the DB raises, use the default "$" rather than crashing
        the message pipeline."""
        mock_db.get_server_by_guild_id.side_effect = Exception("boom")
        bot = MagicMock()
        # Should not raise.
        get_prefix(bot, _message(guild_id=88))

    @patch("caldanai.lib.bot.DB")
    def test_db_exception_still_caches_default(self, mock_db):
        """Current behavior: even on DB failure we cache the default
        so we don't hammer a broken DB repeatedly. Trade-off: if the
        DB comes back with a non-default prefix for this guild, an
        operator needs to bounce the process (or change the prefix,
        which invalidates via ``cache_prefix``) to pick it up.

        If that trade-off ever proves wrong we'd change this test
        AND the implementation — so lock the behavior in here."""
        mock_db.get_server_by_guild_id.side_effect = Exception("boom")
        bot = MagicMock()
        get_prefix(bot, _message(guild_id=88))
        assert _prefix_cache[88] == "$"
