"""Tests for ``BotAdminCommands`` — primarily the ``$config`` group
that lifts per-guild channel registration (updates / ideas)
into Discord-side admin commands. The setter writes through to the
``DB.set_guild_channel`` helper covered in ``test_db.py``; these
tests pin the cog wiring (validation, dispatch, key acceptance,
status display)."""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.cogs.bot_admin_commands import BotAdminCommands


@pytest.fixture
def cog():
    return BotAdminCommands(bot=MagicMock())


def _make_ctx(guild_id: int = 1):
    ctx = MagicMock()
    ctx.guild.id = guild_id
    return ctx


def _make_channel(channel_id: int, mention: str = "#ideas"):
    ch = MagicMock()
    ch.id = channel_id
    ch.mention = mention
    return ch


class TestConfigStatusDisplay:
    """``$config`` (no subcommand) renders the current per-guild
    channel registry. Unset channels show ``*(not set)*``; set ones
    render as live channel mentions Discord can resolve."""

    @pytest.mark.asyncio
    async def test_no_channels_set(self, cog):
        ctx = _make_ctx()
        with (
            patch("caldanai.lib.cogs.bot_admin_commands.DB") as DB,
            patch("caldanai.lib.cogs.bot_admin_commands.Dispatcher") as dispatcher,
        ):
            DB.GUILD_CHANNEL_KEYS = ("updates", "ideas")
            DB.get_guild_channels.return_value = {}
            await cog.config.callback(cog, ctx)

        sent = dispatcher.add.call_args.args[1]
        assert "Current configuration" in sent
        assert "*(not set)*" in sent
        # Every registered key shows up in the embed.
        assert "updates" in sent
        assert "ideas" in sent

    @pytest.mark.asyncio
    async def test_partial_channels_set(self, cog):
        ctx = _make_ctx()
        with (
            patch("caldanai.lib.cogs.bot_admin_commands.DB") as DB,
            patch("caldanai.lib.cogs.bot_admin_commands.Dispatcher") as dispatcher,
        ):
            DB.GUILD_CHANNEL_KEYS = ("updates", "ideas")
            DB.get_guild_channels.return_value = {"updates": 555}
            await cog.config.callback(cog, ctx)

        sent = dispatcher.add.call_args.args[1]
        # Set channel renders as Discord mention (<#id>).
        assert "<#555>" in sent
        # Unset channel still announces itself.
        assert "*(not set)*" in sent

    @pytest.mark.asyncio
    async def test_config_channel_falls_back_to_status_display(self, cog):
        """``$config channel`` (no further subcommand) shows the
        same status as ``$config`` itself — operators don't have
        to remember which spelling shows the dump."""
        ctx = _make_ctx()
        with (
            patch("caldanai.lib.cogs.bot_admin_commands.DB") as DB,
            patch("caldanai.lib.cogs.bot_admin_commands.Dispatcher") as dispatcher,
        ):
            DB.GUILD_CHANNEL_KEYS = ("updates", "ideas")
            DB.get_guild_channels.return_value = {}
            await cog.config_channel.callback(cog, ctx)

        sent = dispatcher.add.call_args.args[1]
        assert "Current configuration" in sent


class TestConfigChannelSetters:
    """``$config channel ideas <#mention>`` and ``$config channel
    updates <#mention>`` write through ``DB.set_guild_channel``
    and acknowledge in-channel. The ``TextChannel`` converter
    resolves Discord mentions before the handler runs, so by the
    time we see the arg it's an object with ``.id`` and
    ``.mention``."""

    @pytest.mark.asyncio
    async def test_ideas_writes_through_db(self, cog):
        ctx = _make_ctx(guild_id=42)
        channel = _make_channel(channel_id=999, mention="#rpg-ideas")
        with (
            patch("caldanai.lib.cogs.bot_admin_commands.DB") as DB,
            patch("caldanai.lib.cogs.bot_admin_commands.Dispatcher") as dispatcher,
        ):
            await cog.config_channel_ideas.callback(cog, ctx, channel)

        DB.set_guild_channel.assert_called_once_with(42, "ideas", 999)
        sent = dispatcher.add.call_args.args[1]
        assert "channel.ideas" in sent
        assert "#rpg-ideas" in sent

    @pytest.mark.asyncio
    async def test_updates_writes_through_db(self, cog):
        ctx = _make_ctx(guild_id=42)
        channel = _make_channel(channel_id=777, mention="#rpg-updates")
        with (
            patch("caldanai.lib.cogs.bot_admin_commands.DB") as DB,
            patch("caldanai.lib.cogs.bot_admin_commands.Dispatcher") as dispatcher,
        ):
            await cog.config_channel_updates.callback(cog, ctx, channel)

        DB.set_guild_channel.assert_called_once_with(42, "updates", 777)
        sent = dispatcher.add.call_args.args[1]
        assert "channel.updates" in sent
        assert "#rpg-updates" in sent

    def test_setter_helper_translates_db_value_error_to_user_message(self, cog):
        """If the DB helper rejects an unknown key (the typo guard),
        the user sees a polite message, not a stack trace. The check
        is defensive — the only callers above pass valid keys, but
        future config commands might pass through a string."""
        ctx = _make_ctx()
        channel = _make_channel(channel_id=1)
        with (
            patch("caldanai.lib.cogs.bot_admin_commands.DB") as DB,
            patch("caldanai.lib.cogs.bot_admin_commands.Dispatcher") as dispatcher,
        ):
            DB.set_guild_channel.side_effect = ValueError("Unknown guild channel key 'oops'")
            cog._set_guild_channel(ctx, "oops", channel)

        sent = dispatcher.add.call_args.args[1]
        assert "Unknown configuration key" in sent
