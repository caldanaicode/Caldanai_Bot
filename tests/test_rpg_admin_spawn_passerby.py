"""Tests for the new $spawn passerby + $spawn depart + $spawn config
passerby admin commands in rpg_admin_commands.

Existing $spawn config monster handlers were relocated (decorators
only — handler bodies unchanged) and aren't re-tested here. The
case-insensitivity invariant test (``test_group_case_insensitivity.py``)
already exercises that the relocated groups exist with correct
flags.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_admin_commands import RpgAdminCommands
from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.creatures.passersby.wagoneer import Wagoneer
from caldanai.lib.rpg.creatures.passersby.wren import Wren


@pytest.fixture(autouse=True)
def _load_passerby_plugins():
    """Tests reference Wagoneer/Wren classes directly but the
    registry-based force-spawn lookup also needs the registry
    populated. Idempotent — load_plugins re-discovers each call
    but reuses cached classes."""
    PasserbyPlugin.load_plugins()


@pytest.fixture
def cog():
    return RpgAdminCommands(bot=MagicMock())


def _make_game(*, passerby=None, pending=None):
    """Minimal Game stand-in with the fields the new admin commands
    read. ``do_passerby_depart`` / ``set_passerby_timer`` are async
    methods; mock them as AsyncMock so awaits resolve cleanly."""
    game = MagicMock()
    game.passerby = passerby
    game.pending_silhouette = pending
    game.use_passerby_timer = True
    game.passerby_spawn_range = (900, 2700)
    game.passerby_depart_after = 300
    game.do_passerby_depart = AsyncMock()
    game.set_passerby_timer = AsyncMock()
    game.game_clock = MagicMock()
    game.game_clock.add_routine = MagicMock()
    game.game_clock.remove_routine = MagicMock()
    game.channel = MagicMock()
    game.save = MagicMock()
    return game


def _make_ctx(cog, game, channel_id: int = 42):
    ctx = MagicMock()
    ctx.channel.id = channel_id
    ctx.guild = MagicMock()
    ctx.guild.icon = MagicMock()
    ctx.guild.icon.url = "https://example.com/icon.png"
    cog.bot.games = {channel_id: game}
    return ctx


class TestSpawnPasserbyForceSpawn:
    """``$spawn passerby [name]`` force-spawn admin command."""

    @pytest.mark.asyncio
    async def test_named_force_spawn_sets_passerby_field(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.passerby.callback(cog, ctx, "wagoneer")

        assert isinstance(game.passerby, Wagoneer)

    @pytest.mark.asyncio
    async def test_named_force_spawn_dispatches_arrival(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.passerby.callback(cog, ctx, "wagoneer")

        # Arrival line dispatched (one of Wagoneer.ARRIVAL_POOL).
        assert mock_dispatch.add.called
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("wagoneer" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_named_force_spawn_schedules_depart(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.passerby.callback(cog, ctx, "wagoneer")

        # Depart timer scheduled with game.do_passerby_depart as the
        # callable. (do_passerby_depart is an AsyncMock here so we
        # match by identity, not by __name__.)
        scheduled_calls = game.game_clock.add_routine.call_args_list
        assert any(
            c.args[0] is game.do_passerby_depart for c in scheduled_calls
        ), f"expected depart routine scheduled; got {scheduled_calls}"
        # And scheduled at the configured depart_after.
        depart_call = next(
            c for c in scheduled_calls
            if c.args[0] is game.do_passerby_depart
        )
        assert depart_call.args[1] == game.passerby_depart_after

    @pytest.mark.asyncio
    async def test_random_force_spawn_picks_an_npc(self, cog):
        """No name arg → calls pick_npc and assigns whatever it
        returns. Patch pick_npc to return a deterministic class."""
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.rpg.creatures.passersby.spawn.pick_npc",
            return_value=Wren,
        ), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.passerby.callback(cog, ctx, None)

        assert isinstance(game.passerby, Wren)

    @pytest.mark.asyncio
    async def test_already_present_passerby_skips(self, cog):
        existing = Wagoneer()
        game = _make_game(passerby=existing)
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.passerby.callback(cog, ctx, "herbalist")

        # passerby slot unchanged.
        assert game.passerby is existing
        # Single dispatch — the "already present" message.
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("already present" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_silhouette_present_skips(self, cog):
        silhouette = Wagoneer()
        game = _make_game(pending=silhouette)
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.passerby.callback(cog, ctx, "herbalist")

        # passerby slot still None; silhouette unchanged.
        assert game.passerby is None
        assert game.pending_silhouette is silhouette
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("silhouette" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_unknown_name_dispatches_error(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.passerby.callback(cog, ctx, "definitely_not_a_passerby_name")

        assert game.passerby is None
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("no passerby" in str(m).lower() for m in added)


class TestSpawnDepart:
    """``$spawn depart`` force-departs the present passerby."""

    @pytest.mark.asyncio
    async def test_no_passerby_dispatches_warning(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.depart.callback(cog, ctx)

        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("no passerby" in str(m).lower() for m in added)
        # do_passerby_depart not called.
        game.do_passerby_depart.assert_not_called()

    @pytest.mark.asyncio
    async def test_present_passerby_depart_invoked(self, cog):
        game = _make_game(passerby=Wagoneer())
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.depart.callback(cog, ctx)

        game.do_passerby_depart.assert_awaited_once()


class TestConfigPasserbyTunables:
    """``$spawn config passerby min/max/duration/set`` tunables."""

    @pytest.mark.asyncio
    async def test_min_no_arg_displays_current(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.config_passerby_min.callback(cog, ctx, None)

        # No write, dispatched the current value.
        game.save.assert_not_called()
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("minimum passerby" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_min_valid_arg_updates_and_saves(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.config_passerby_min.callback(cog, ctx, 10)

        # 10 minutes → 600 seconds; max preserved.
        assert game.passerby_spawn_range == (600, 2700)
        game.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_min_above_max_rejected(self, cog):
        game = _make_game()
        # Default max is 2700s (45 min). Attempt min=50 should reject.
        ctx = _make_ctx(cog, game)

        with patch(
            "caldanai.lib.cogs.rpg_admin_commands.Dispatcher"
        ) as mock_dispatch:
            await cog.config_passerby_min.callback(cog, ctx, 50)

        # No write.
        assert game.passerby_spawn_range == (900, 2700)
        game.save.assert_not_called()
        added = [
            c.args[1] for c in mock_dispatch.add.call_args_list
            if len(c.args) >= 2
        ]
        assert any("less than the maximum" in str(m).lower() for m in added)

    @pytest.mark.asyncio
    async def test_max_valid_arg_updates_and_saves(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.config_passerby_max.callback(cog, ctx, 60)

        # 60 minutes → 3600 seconds; min preserved.
        assert game.passerby_spawn_range == (900, 3600)
        game.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_duration_valid_arg_updates_and_saves(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.config_passerby_duration.callback(cog, ctx, 10)

        # 10 minutes → 600 seconds.
        assert game.passerby_depart_after == 600
        game.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_off_clears_routine(self, cog):
        game = _make_game()
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.config_passerby_set.callback(cog, ctx, "off")

        assert game.use_passerby_timer is False
        # Routine removed.
        game.game_clock.remove_routine.assert_called_once()
        game.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_on_starts_routine(self, cog):
        game = _make_game()
        game.use_passerby_timer = False  # start disabled
        ctx = _make_ctx(cog, game)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.config_passerby_set.callback(cog, ctx, "on")

        assert game.use_passerby_timer is True
        game.set_passerby_timer.assert_awaited_once()
        game.save.assert_called_once()
