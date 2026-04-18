from typing import TYPE_CHECKING
from discord.ext.commands import Cog, CheckFailure, command, has_permissions, guild_only, is_owner, Context

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

    @Cog.listener()
    async def on_ready(self):
        _log.info("BotAdminCommands ready.")


async def setup(bot: "Bot"):
    await bot.add_cog(BotAdminCommands(bot))
