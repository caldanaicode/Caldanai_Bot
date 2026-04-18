"""Tests for ``Bot.games`` — a read-only live view over
``Game._channel_routes``.

Prior to 2026-04-17, ``Bot.games`` was a standalone dict that had to
be kept in sync with ``Game._channel_routes`` by every add/remove
code path. Drift between the two registries was exactly the shape
of the 2026-04-15 guild-id/channel-id rekey bug (``bot.games`` rekeyed
but one caller still used guild_id against the new map). These tests
lock in the property-view semantics so that cannot regress:

- ``bot.games`` reads through to the class registry.
- ``Game.register_channel`` / ``unregister_channel`` (the write path)
  is reflected through ``bot.games`` on the next access.
- Dict-style reads all work (``.get``, ``in``, iteration, ``.values``,
  ``.keys``, ``.items``).
- External mutation of ``bot.games`` is rejected (read-only proxy).
"""

from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def clean_routes():
    """Isolate ``Game._channel_routes`` from cross-test pollution."""
    from caldanai.lib.rpg import Game
    Game._channel_routes.clear()
    yield Game
    Game._channel_routes.clear()


def _make_game(channel_id, guild_id=111):
    """Build a non-initialized Game-like object that ``register_channel``
    can store. Avoids the real ``Game.__init__`` side-effects (clock
    daemons, weather, DB reads) — we're testing the registry, not
    Game construction."""
    from caldanai.lib.rpg import Game
    game = MagicMock(spec=Game)
    game.guild = MagicMock()
    game.guild.id = guild_id
    game.channel = MagicMock()
    game.channel.id = channel_id
    return game


def _make_bot():
    """Instantiate a real ``Bot`` without going through ``__init__``
    (which would hit the DB for auth credentials). We only need the
    class's ``games`` property, which reads directly from
    ``Game._channel_routes``."""
    from caldanai.lib.bot import Bot
    return Bot.__new__(Bot)


class TestBotGamesView:
    def test_empty_registry_returns_empty_view(self, clean_routes):
        bot = _make_bot()
        assert len(bot.games) == 0
        assert list(bot.games) == []

    def test_register_channel_visible_via_bot_games(self, clean_routes):
        """Primary registration path: ``Game.register_channel`` puts
        the game into the registry, and ``bot.games[channel_id]``
        resolves to that game — no separate ``bot.games[...]=game``
        assignment involved."""
        Game = clean_routes
        bot = _make_bot()
        game = _make_game(channel_id=999)

        game.register_channel = Game.register_channel.__get__(game)
        game.register_channel(999)

        assert bot.games[999] is game
        assert bot.games.get(999) is game
        assert 999 in bot.games

    def test_unregister_channel_removes_from_bot_games(self, clean_routes):
        """Teardown path: ``unregister_channel`` drops the entry from
        the registry, and it disappears from ``bot.games``. This is
        exactly the teardown behavior ``RpgUtilities.remove_game``
        now relies on (no more ``del bot.games[channel_id]``)."""
        Game = clean_routes
        bot = _make_bot()
        game = _make_game(channel_id=999)

        game.register_channel = Game.register_channel.__get__(game)
        game.unregister_channel = Game.unregister_channel.__get__(game)
        game.register_channel(999)
        assert 999 in bot.games

        game.unregister_channel(999)
        assert 999 not in bot.games
        assert bot.games.get(999) is None

    def test_for_channel_and_bot_games_agree(self, clean_routes):
        """Single source of truth: ``Game.for_channel(id)`` and
        ``bot.games.get(id)`` must return the same Game for any
        registered channel."""
        Game = clean_routes
        bot = _make_bot()
        game = _make_game(channel_id=999)

        game.register_channel = Game.register_channel.__get__(game)
        game.register_channel(999)

        assert Game.for_channel(999) is bot.games.get(999)
        assert Game.for_channel(999) is game

    def test_spillover_channel_visible_via_bot_games(self, clean_routes):
        """Multi-channel routing (dungeon threads, etc.) preserved:
        an additional ``register_channel`` on a Game makes the new
        id resolvable through both ``Game.for_channel`` and
        ``bot.games``. The primary channel keeps resolving too."""
        Game = clean_routes
        bot = _make_bot()
        game = _make_game(channel_id=999)

        game.register_channel = Game.register_channel.__get__(game)
        game.register_channel(999)  # primary
        game.register_channel(5555)  # dungeon thread spillover

        assert bot.games.get(999) is game
        assert bot.games.get(5555) is game
        assert Game.for_channel(5555) is game

    def test_iteration_and_values_supported(self, clean_routes):
        """Cogs iterate ``bot.games.values()`` / ``bot.games.items()``
        (shutdown command, save-game-data loop, watchdog). The view
        must support all of those."""
        Game = clean_routes
        bot = _make_bot()
        g1 = _make_game(channel_id=111)
        g2 = _make_game(channel_id=222)

        for g in (g1, g2):
            g.register_channel = Game.register_channel.__get__(g)
            g.register_channel(g.channel.id)

        assert set(bot.games.keys()) == {111, 222}
        assert set(bot.games.values()) == {g1, g2}
        assert dict(bot.games.items()) == {111: g1, 222: g2}
        assert set(iter(bot.games)) == {111, 222}

    def test_view_is_read_only(self, clean_routes):
        """Outside code can't mutate ``bot.games`` directly — writes
        must go through ``register_channel`` / ``unregister_channel``.
        ``MappingProxyType`` rejects ``__setitem__`` / ``__delitem__``
        at the type level, enforcing the single source of truth."""
        bot = _make_bot()
        assert isinstance(bot.games, MappingProxyType)

        with pytest.raises(TypeError):
            bot.games[42] = object()

    def test_view_reflects_subsequent_registrations(self, clean_routes):
        """The view is *live*: a single ``bot.games`` access early
        in a function stays valid as the registry changes beneath
        it (no stale snapshot)."""
        Game = clean_routes
        bot = _make_bot()
        view = bot.games  # capture BEFORE any registration
        assert len(view) == 0

        game = _make_game(channel_id=999)
        game.register_channel = Game.register_channel.__get__(game)
        game.register_channel(999)

        # Same view object, newly visible entry.
        assert view[999] is game
        assert len(view) == 1
