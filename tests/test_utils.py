"""Tests for Caldanai.lib.rpg.helpers.utils — generate_report, cache_auth, save_game_data."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

import caldanai.lib.rpg.helpers.utils as utils_module
from caldanai.lib.rpg.helpers.utils import (
    generate_report, cache_auth, save_game_data, save_all_now, RpgUtilities,
)


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport:
    @patch("caldanai.lib.rpg.helpers.utils.smtplib.SMTP")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
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

    @patch("caldanai.lib.rpg.helpers.utils.smtplib.SMTP")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
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

    @patch("caldanai.lib.rpg.helpers.utils.DB")
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
    @patch("caldanai.lib.rpg.helpers.utils.DB")
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

    @patch("caldanai.lib.rpg.helpers.utils.DB")
    def test_cache_auth_db_returns_none(self, mock_db):
        utils_module._cached_auth = None
        mock_db.get_auth.return_value = None
        cache_auth()
        assert utils_module._cached_auth is None

    @patch("caldanai.lib.rpg.helpers.utils.DB")
    def test_cache_auth_db_raises(self, mock_db):
        utils_module._cached_auth = None
        mock_db.get_auth.side_effect = Exception("connection refused")
        cache_auth()
        assert utils_module._cached_auth is None


# ---------------------------------------------------------------------------
# resolve_reply_channel
# ---------------------------------------------------------------------------

class TestResolveReplyChannel:
    def test_returns_game_channel_when_ctx_has_guild(self):
        """Guild invocation: reply goes to the game's bound channel."""
        game = SimpleNamespace(channel=SimpleNamespace(id=42))
        ctx = SimpleNamespace(guild=SimpleNamespace(id=1))

        assert RpgUtilities.resolve_reply_channel(ctx, game) is game.channel

    def test_returns_ctx_when_guild_is_none(self):
        """DM invocation (ctx.guild is None): reply goes back to ctx."""
        game = SimpleNamespace(channel=SimpleNamespace(id=42))
        ctx = SimpleNamespace(guild=None)

        assert RpgUtilities.resolve_reply_channel(ctx, game) is ctx

    def test_returns_ctx_when_guild_attr_missing(self):
        """``Member`` / ``User`` objects lack ``.guild`` entirely; fall
        back to the DM path rather than raising AttributeError."""
        game = SimpleNamespace(channel=SimpleNamespace(id=42))
        ctx = SimpleNamespace()  # no .guild attribute

        assert RpgUtilities.resolve_reply_channel(ctx, game) is ctx


# ---------------------------------------------------------------------------
# save_game_data loop logic
# ---------------------------------------------------------------------------

class TestSaveGameData:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
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
        game.channel.id = 888
        game.to_dict.return_value = {"guild_id": 999}
        game.player_manager.players.values.return_value = [player_dirty, player_clean]

        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        # save_game_data is a discord.ext.tasks.Loop; call the underlying coro
        coro = save_game_data.coro if hasattr(save_game_data, "coro") else save_game_data
        await coro()

        # Game data always saved with compound (guild_id, channel_id) key
        mock_db.update_game.assert_called_once_with(999, 888, {"guild_id": 999})

        # Only dirty player saved with compound (guild_id, channel_id, user_id) key
        mock_db.update_player.assert_called_once_with(999, 888, 1, {"user_id": 1})
        assert player_dirty.is_dirty is False

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
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
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
    async def test_new_player_id_resolved(self, mock_db, mock_rpg):
        new_player = MagicMock()
        new_player.id = None
        new_player.guild_id = 50
        new_player.channel_id = 500
        new_player.user_id = 7

        # save_game_data reads p["_id"] (round-3 fix `5bb7059`), not p.id —
        # set up the mock so __getitem__("_id") returns the resolved id.
        mock_db.get_player.return_value = {"_id": "resolved_id"}

        game = MagicMock()
        game.guild.id = 50
        game.channel.id = 500
        game.to_dict.return_value = {}
        game.player_manager.players.values.return_value = []

        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = {new_player}
        mock_rpg.update_statics = MagicMock()

        coro = save_game_data.coro if hasattr(save_game_data, "coro") else save_game_data
        await coro()

        mock_db.get_player.assert_called_once_with(50, 500, 7)
        assert new_player.id == "resolved_id"


class TestSaveAllNow:
    """``save_all_now`` is the one-shot synchronous sibling of
    ``save_game_data``. The loop delegates to it so the periodic
    save and the shutdown save share a single implementation. These
    tests pin the one-shot semantics and the error-swallowing
    contract that keeps shutdown from cascading on a single bad
    player/game."""

    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
    def test_is_synchronous(self, mock_db, mock_rpg):
        """save_all_now must be callable directly — no coroutine
        wrapper. The shutdown path relies on this to avoid an
        ``await`` between enqueue and flush, which would let other
        tasks interleave and enqueue new writes after the drain."""
        mock_rpg.bot.games.values.return_value = []
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        # Must not return a coroutine — a direct call returns None.
        assert save_all_now() is None

    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
    def test_enqueues_same_writes_as_loop_body(self, mock_db, mock_rpg):
        """Semantic equivalence with the old save_game_data body:
        one game update per game, one player update per dirty
        player, clean players skipped, dirty flag cleared."""
        dirty = MagicMock()
        dirty.is_dirty = True
        dirty.user_id = 1
        dirty.to_dict.return_value = {"user_id": 1}
        clean = MagicMock()
        clean.is_dirty = False
        clean.user_id = 2

        game = MagicMock()
        game.guild.id = 999
        game.channel.id = 888
        game.to_dict.return_value = {"guild_id": 999}
        game.player_manager.players.values.return_value = [dirty, clean]

        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        save_all_now()

        mock_db.update_game.assert_called_once_with(999, 888, {"guild_id": 999})
        mock_db.update_player.assert_called_once_with(999, 888, 1, {"user_id": 1})
        assert dirty.is_dirty is False

    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
    def test_swallows_exceptions(self, mock_db, mock_rpg):
        """A bad to_dict() on one player must not prevent the rest
        of the save — shutdown cannot afford to cascade-fail out of
        one bad object. The same contract the loop version carries."""
        game = MagicMock()
        game.guild.id = 1
        game.channel.id = 2
        game.to_dict.side_effect = RuntimeError("boom")
        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        # Must not raise.
        save_all_now()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    @patch("caldanai.lib.rpg.helpers.utils.DB")
    async def test_save_game_data_loop_delegates_to_save_all_now(
        self, mock_db, mock_rpg,
    ):
        """The loop body was extracted into save_all_now — verify
        the task still writes. The two share one implementation so
        any regression in save_all_now also regresses the loop."""
        game = MagicMock()
        game.guild.id = 7
        game.channel.id = 8
        game.to_dict.return_value = {}
        game.player_manager.players.values.return_value = []
        mock_rpg.bot.games.values.return_value = [game]
        mock_rpg.new_players = set()
        mock_rpg.update_statics = MagicMock()

        coro = save_game_data.coro if hasattr(save_game_data, "coro") else save_game_data
        await coro()

        mock_db.update_game.assert_called_once()


class TestDeadInvokerGuard:
    """``RpgUtilities.dead_invoker_guard`` is the shared early-return
    for commands that don't apply when the invoker is dead. Tests
    pin: the gate itself, template vs. pool inputs, parse-token
    resolution against the player actor, and the no-op-on-alive
    contract the call sites rely on for ``if ...guard(...): return``."""

    def _make_player(self, name: str = "Alice", dead: bool = False):
        from caldanai.lib.rpg.creatures import Creature
        p = Creature(
            name=name, atk="1d4", defense=0, dodge=5,
            health_max=20, health=0 if dead else 20,
            gender="female", pronouns="she, her, hers, her, herself",
        )
        return p

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_alive_player_returns_false_and_emits_nothing(self, mock_dispatch):
        channel = MagicMock()
        player = self._make_player(dead=False)

        result = RpgUtilities.dead_invoker_guard(
            channel, player, "A moan escapes the corpse of @1.",
        )

        assert result is False
        mock_dispatch.add.assert_not_called()

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_dead_player_returns_true_and_dispatches_flavor(self, mock_dispatch):
        channel = MagicMock()
        player = self._make_player(name="Caels", dead=True)

        result = RpgUtilities.dead_invoker_guard(
            channel, player, "A moan escapes the corpse of @1.",
        )

        assert result is True
        mock_dispatch.add.assert_called_once()
        # @1 resolved to the player's name.
        sent_channel, sent_line = mock_dispatch.add.call_args.args
        assert sent_channel is channel
        assert "Caels" in sent_line

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    @patch("caldanai.lib.rpg.helpers.utils.choice")
    def test_pool_input_draws_random_line(self, mock_choice, mock_dispatch):
        """A list input means "pick randomly for variety" — the
        fun-command shape. The helper must route through ``choice``
        rather than always picking element 0 or the whole list."""
        pool = [
            "@1 is in no condition to aim.",
            "The corpse of @1 stares skyward.",
        ]
        mock_choice.side_effect = lambda p: p[1]
        channel = MagicMock()
        player = self._make_player(name="Bob", dead=True)

        result = RpgUtilities.dead_invoker_guard(channel, player, pool)

        assert result is True
        mock_choice.assert_called_once_with(pool)
        sent_line = mock_dispatch.add.call_args.args[1]
        assert "Bob" in sent_line
        assert "corpse" in sent_line.lower()

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_parse_tokens_resolve_against_player_actor(self, mock_dispatch):
        """Templates can use noun-possessive / pronoun tokens. The
        helper wires the player as ``@1`` so ``@1np`` renders as the
        possessive form of the player's name."""
        channel = MagicMock()
        player = self._make_player(name="Caels", dead=True)

        RpgUtilities.dead_invoker_guard(
            channel, player, "@1np spirit flickers.",
        )

        sent_line = mock_dispatch.add.call_args.args[1]
        assert "Caels's" in sent_line


class TestDeadInvokerFlavorPools:
    """Every cog-registered dead-invoker pool must be non-empty
    and each line must render as a valid parse template against a
    single-player actor (no stray ``@`` tokens surviving render).
    Prevents a typo in a template from silently shipping to
    players as literal ``@1np`` text."""

    def _render_check(self, pool):
        from caldanai.lib.rpg.creatures import Creature
        from caldanai.lib.rpg.helpers.parser import parse
        player = Creature(
            name="Alice", atk="1d4", defense=0, dodge=5,
            health_max=20, gender="female",
            pronouns="she, her, hers, her, herself",
        )
        assert pool, "dead-invoker pool must be non-empty"
        for line in pool:
            assert isinstance(line, str) and line, "each pool entry must be a non-empty string"
            rendered = parse(line, player)
            assert "@1" not in rendered and "@2" not in rendered, (
                f"unresolved parse token in: {rendered!r}"
            )

    def test_attack_pool(self):
        from caldanai.lib.cogs.rpg_user_commands import _DEAD_INVOKER_ATTACK_FLAVOR
        self._render_check(_DEAD_INVOKER_ATTACK_FLAVOR)

    def test_hug_pool(self):
        # Hug dead-invoker pool lives in the social cog now (moved
        # alongside ``$hug`` when the warmth refactor split the two).
        from caldanai.lib.cogs.rpg_social_commands import _DEAD_INVOKER_FLAVOR
        self._render_check(_DEAD_INVOKER_FLAVOR["hug"])

    def test_inventory_pool(self):
        from caldanai.lib.cogs.rpg_inventory_commands import _DEAD_INVOKER_INVENTORY_FLAVOR
        self._render_check(_DEAD_INVOKER_INVENTORY_FLAVOR)

    def test_target_dead_invoker_pool(self):
        from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
        self._render_check(RpgUserCommands._TARGET_DEAD_INVOKER_FLAVOR)
