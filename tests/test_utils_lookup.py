"""Tests for the ``RpgUtilities`` lookup helpers (``get_game``,
``get_player``, ``get_games_for_user``).

These helpers are the connective tissue between Discord-provided
context objects and the in-memory game/player state. They get
exercised via commands but the ``Context`` vs ``Member`` vs ``User``
discrimination is easy to get wrong during refactors — this file
asserts the discrimination directly so the next refactor surfaces a
broken path immediately instead of via a player typing ``$hug
@someone`` in production.

Regression context: when ``bot.games`` was rekeyed from ``guild.id``
to ``channel.id`` (2026-04-15), ``get_game(Member)`` started crashing
with ``AttributeError: 'Member' object has no attribute 'channel'``
because ``Member`` objects don't have a channel. The first fix's
fallback tried to key ``bot.games`` by ``guild_id`` from the player
doc — which no longer worked because ``bot.games`` is channel-keyed.
Shipped version: callers pass the already-resolved ``game`` through
explicitly via ``get_player(mention, game=game)``. These tests lock
that behavior in.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from discord import Member, User
from discord.ext.commands import Context


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.games = {}
    return bot


@pytest.fixture
def rpg_with_bot(mock_bot):
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    original = RpgUtilities.bot
    RpgUtilities.bot = mock_bot
    yield RpgUtilities
    RpgUtilities.bot = original


def _make_game(guild_id=111, channel_id=999):
    from caldanai.lib.rpg import Game
    game = MagicMock(spec=Game)
    game.guild = MagicMock()
    game.guild.id = guild_id
    game.channel = MagicMock()
    game.channel.id = channel_id
    return game


def _make_context(guild_id=111, channel_id=999, author_id=42):
    ctx = MagicMock(spec=Context)
    ctx.guild = MagicMock()
    ctx.guild.id = guild_id
    ctx.channel = MagicMock()
    ctx.channel.id = channel_id
    ctx.author = MagicMock()
    ctx.author.id = author_id
    return ctx


def _make_member(guild_id=111, user_id=42):
    """Member has ``.guild`` and ``.id`` but NO ``.channel`` and
    NO ``.author`` — this is the shape that crashed post-rekey."""
    member = MagicMock(spec=Member)
    member.id = user_id
    member.guild = MagicMock()
    member.guild.id = guild_id
    # Members don't have .channel; spec=Member enforces attribute
    # limits but ``MagicMock`` auto-creates attrs, so be explicit.
    del member.channel
    del member.author
    return member


class TestGetGameWithContext:
    """Standard command invocation path — ``ctx`` is a ``Context``."""

    @pytest.mark.asyncio
    async def test_resolves_via_channel_id(self, rpg_with_bot):
        game = _make_game(channel_id=999)
        rpg_with_bot.bot.games = {999: game}
        ctx = _make_context(channel_id=999)

        result = await rpg_with_bot.get_game(ctx)
        assert result is game

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_channel(self, rpg_with_bot):
        rpg_with_bot.bot.games = {}
        ctx = _make_context(channel_id=9999)

        with patch("caldanai.lib.rpg.helpers.utils.Dispatcher"):
            result = await rpg_with_bot.get_game(ctx)
        assert result is None


class TestGetGameWithMember:
    """Mention-passthrough path — ``ctx`` is a ``Member`` (no
    ``.channel``, no ``.author``). Regression guard for the
    post-rekey AttributeError."""

    @pytest.mark.asyncio
    async def test_member_resolves_via_get_games_for_user(
        self, rpg_with_bot,
    ):
        game = _make_game(guild_id=111, channel_id=999)
        rpg_with_bot.bot.games = {999: game}
        member = _make_member(guild_id=111, user_id=42)

        # Player doc includes channel_id (post-migration shape) →
        # get_games_for_user can route to bot.games[999].
        with patch(
            "caldanai.lib.rpg.helpers.utils.DB.find_players_by_user_id",
            return_value=[{"user_id": 42, "guild_id": 111, "channel_id": 999}],
        ), patch("caldanai.lib.rpg.helpers.utils.Dispatcher"):
            result = await rpg_with_bot.get_game(member)
        assert result is game

    @pytest.mark.asyncio
    async def test_member_without_channel_attribute_does_not_crash(
        self, rpg_with_bot,
    ):
        """Tightest regression: Member objects lack ``.channel``, so
        the channel-keyed lookup can't be used on them — we must
        route to the user-lookup path gracefully."""
        rpg_with_bot.bot.games = {}
        member = _make_member()

        with patch(
            "caldanai.lib.rpg.helpers.utils.DB.find_players_by_user_id",
            return_value=[],
        ), patch("caldanai.lib.rpg.helpers.utils.Dispatcher"):
            # Must NOT raise AttributeError.
            result = await rpg_with_bot.get_game(member)
        assert result is None

    @pytest.mark.asyncio
    async def test_member_with_legacy_player_doc_no_channel_id(
        self, rpg_with_bot,
    ):
        """Legacy player doc (pre-migration): has ``guild_id`` but
        no ``channel_id``. ``bot.games`` is channel-keyed, so the
        guild_id fallback in ``get_games_for_user`` won't match.
        Current behavior: returns None — which is exactly what
        ``$hug @serena`` hit in production before the shipped fix
        to pass ``game`` through explicitly. Locked in so we don't
        silently regress the shipped caller-side fix.

        If we ever want legacy docs to resolve without a caller-
        side pass-through, the fix goes in ``get_games_for_user``
        (scan ``bot.games.values()`` matching guild_id) — and this
        test should be flipped to assert a non-None result."""
        game = _make_game(guild_id=111, channel_id=999)
        rpg_with_bot.bot.games = {999: game}
        member = _make_member(guild_id=111, user_id=42)

        with patch(
            "caldanai.lib.rpg.helpers.utils.DB.find_players_by_user_id",
            return_value=[{"user_id": 42, "guild_id": 111}],  # legacy
        ), patch("caldanai.lib.rpg.helpers.utils.Dispatcher"):
            result = await rpg_with_bot.get_game(member)
        assert result is None


class TestGetGameInDM:
    """DM path — no guild, no channel. Caller must be a ``Context``
    whose ``.guild`` is None."""

    @pytest.mark.asyncio
    async def test_dm_context_uses_author_id_lookup(self, rpg_with_bot):
        game = _make_game(channel_id=999)
        rpg_with_bot.bot.games = {999: game}
        ctx = _make_context()
        ctx.guild = None  # DM

        with patch(
            "caldanai.lib.rpg.helpers.utils.DB.find_players_by_user_id",
            return_value=[{"user_id": 42, "guild_id": 111, "channel_id": 999}],
        ), patch("caldanai.lib.rpg.helpers.utils.Dispatcher"):
            result = await rpg_with_bot.get_game(ctx)
        assert result is game


class TestGetGamesForUser:
    """Direct tests on the user→games resolver."""

    def test_channel_id_lookup_matches_current_bot_games_keying(
        self, rpg_with_bot,
    ):
        game = _make_game(channel_id=999)
        rpg_with_bot.bot.games = {999: game}

        with patch(
            "caldanai.lib.rpg.helpers.utils.DB.find_players_by_user_id",
            return_value=[{"user_id": 42, "guild_id": 111, "channel_id": 999}],
        ):
            games = rpg_with_bot.get_games_for_user(42)
        assert games == [game]

    def test_legacy_doc_without_channel_id_misses(self, rpg_with_bot):
        """Documented-current-behavior test: the fallback to
        ``guild_id`` as a ``bot.games`` key is a miss because the
        dict is channel-keyed. See the note in ``test_member_with_
        legacy_player_doc_no_channel_id`` for the migration path."""
        game = _make_game(guild_id=111, channel_id=999)
        rpg_with_bot.bot.games = {999: game}

        with patch(
            "caldanai.lib.rpg.helpers.utils.DB.find_players_by_user_id",
            return_value=[{"user_id": 42, "guild_id": 111}],
        ):
            games = rpg_with_bot.get_games_for_user(42)
        assert games == []

    def test_returns_empty_for_none_uid(self, rpg_with_bot):
        assert rpg_with_bot.get_games_for_user(None) == []


class TestGetPlayerGamePassthrough:
    """``get_player(mention, game=game)`` is the shipped pattern for
    mention-passthrough calls (smite, hug, haunt, look, etc.).
    When ``game`` is passed explicitly, the helper must NOT try to
    re-resolve it via ``get_game`` — that's the path that crashed
    with Member inputs post-rekey."""

    @pytest.mark.asyncio
    async def test_pass_game_through_skips_get_game(self, rpg_with_bot):
        game = _make_game(channel_id=999)
        fake_player = MagicMock()
        game.player_manager = MagicMock()
        game.player_manager.get_player = AsyncMock(return_value=fake_player)

        member = _make_member(user_id=42)

        # Importantly: do NOT patch get_game. If the passthrough
        # works, get_game is never called, and the test doesn't
        # depend on its behavior.
        result = await rpg_with_bot.get_player(member, game=game)
        assert result is fake_player
        game.player_manager.get_player.assert_awaited_once_with(member)
