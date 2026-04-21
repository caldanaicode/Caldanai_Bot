from typing import TYPE_CHECKING
from discord import TextChannel
from discord.ext.commands import (
    Cog, CheckFailure, command, group, check_any,
    has_permissions, guild_only, is_owner, Context,
)

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.db import DB
from caldanai.lib.bot import cache_prefix

if TYPE_CHECKING:
    from caldanai.lib.bot import Bot


_log = get_logger(__name__)


class BotAdminCommands(Cog):
    def __init__(self, bot: "Bot"):
        self.bot = bot

    @command(name="prefix", brief="Changes the bot's prefix for recognizing commands.")
    @guild_only()
    @has_permissions(manage_guild=True)
    async def change_prefix(self, ctx: Context, prefix: str):
        """
        Changes the bot's prefix for recognizing commands. Requires Manage Server permissions.

        :param prefix: The new prefix to use.
        """
        if len(prefix) > 5:
            Dispatcher.add(ctx, "Prefix cannot be longer than 5 characters.")

        else:
            try:
                if DB.get_server_by_guild_id(ctx.guild.id):
                    DB.update_server_prefix(ctx.guild.id, prefix)
                else:
                    DB.insert_server(ctx.guild.id, ctx.guild.name, prefix)

                # Keep the in-memory cache in sync so the very next
                # message in this guild uses the new prefix without
                # a DB round-trip.
                cache_prefix(ctx.guild.id, prefix)

                Dispatcher.add(ctx, f"Prefix set to {prefix}.")

            except Exception as e:
                _log.error(e)
                Dispatcher.add(
                    ctx, "There appears to be an issue with the database at the moment. Please try again later."
                )

    @change_prefix.error
    async def change_prefix_error(self, ctx: Context, exc):
        if isinstance(exc, CheckFailure):
            Dispatcher.add(ctx, "You need the Manage Server permission to do that.")

    @is_owner()
    @command(name="reload_cog", brief="Reloads a cog -- or all cogs if no cog is specified -- on the bot.")
    async def reload_cog(self, ctx: Context, cog: str = None):
        """
        Reloads a cog -- or all cogs if no cog is specified -- on the bot.

        :param cog: The name of the cog to reload.
        """
        if cog is None:
            await self.bot.reload_all_cogs()
            Dispatcher.add(ctx, "Cogs reloaded!")
        else:
            for c in self.bot.COGS:
                if c.lower() == cog.lower():
                    await self.bot.reload_cog(c)
                    Dispatcher.add(ctx, f"{cog} cog reloaded!")
                    return
            else:
                Dispatcher.add(ctx, f"There is no cog '{cog}' loaded.")

    @group(brief="Per-guild bot configuration.", invoke_without_command=True, case_insensitive=True)
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def config(self, ctx: Context):
        """
        Per-guild bot configuration commands.

        ``$config`` — show the current configuration.
        ``$config channel <name> <#mention>`` — register a per-
        guild channel by name (``ideas`` for player suggestions
        the tooling reads, ``updates`` for patch notes the tooling
        posts).
        """
        channels = DB.get_guild_channels(ctx.guild.id)
        lines = ["**Current configuration — channels:**"]
        for key in DB.GUILD_CHANNEL_KEYS:
            cid = channels.get(key)
            if cid is None:
                lines.append(f"• `{key}`: *(not set)*")
            else:
                lines.append(f"• `{key}`: <#{cid}>")
        Dispatcher.add(ctx, "\n".join(lines))

    @config.group(name="channel", brief="Per-guild named-channel registration.", invoke_without_command=True, case_insensitive=True)
    async def config_channel(self, ctx: Context):
        """Sub-group for per-guild named channels.

        ``$config channel`` — list registered channels (same as
        ``$config`` when only the channel category exists).
        ``$config channel <name> <#mention>`` — register one.

        Valid names come from :attr:`DB.GUILD_CHANNEL_KEYS`:
        ``ideas`` (where players post suggestions —
        ``tools/check_ideas.py`` reads from here) and ``updates``
        (where patch notes get posted —
        ``tools/post_patch_notes.py`` writes here).
        """
        # No subcommand → fall back to the parent's status display
        # so the operator sees what's currently registered.
        await self.config.callback(self, ctx)

    @config_channel.command(name="ideas", brief="Register the channel where players post game ideas.")
    async def config_channel_ideas(self, ctx: Context, channel: TextChannel):
        """Register the channel where players post ideas /
        suggestions. Read by ``tools/check_ideas.py``.

        :param channel: A channel mention (e.g. ``#rpg-outsourcing``).
        """
        self._set_guild_channel(ctx, "ideas", channel)

    @config_channel.command(name="updates", brief="Register the channel where patch notes are posted.")
    async def config_channel_updates(self, ctx: Context, channel: TextChannel):
        """Register the channel where the bot's tooling posts
        patch notes / announcements (``tools/post_patch_notes.py``).

        :param channel: A channel mention (e.g. ``#rpg-updates``).
        """
        self._set_guild_channel(ctx, "updates", channel)

    @staticmethod
    def _set_guild_channel(ctx: Context, key: str, channel: TextChannel) -> None:
        """Shared body for the per-channel-key config setters.
        Writes via the DB helper (which validates ``key`` against
        ``DB.GUILD_CHANNEL_KEYS``) and acknowledges in-channel."""
        try:
            DB.set_guild_channel(ctx.guild.id, key, channel.id)
        except ValueError as e:
            _log.error(f"Refused config write for {key}: {e}")
            Dispatcher.add(ctx, f"Unknown configuration key `{key}`.")
            return
        Dispatcher.add(
            ctx,
            f"Set `channel.{key}` to {channel.mention} for this guild.",
        )

    @Cog.listener()
    async def on_ready(self):
        _log.info("BotAdminCommands ready.")


async def setup(bot: "Bot"):
    await bot.add_cog(BotAdminCommands(bot))
