from discord.ext.commands import Cog, CheckFailure, command, has_permissions, guild_only

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.db import MongoDB


class BotAdminCommands(Cog):
	def __init__(self, bot):
		self.bot = bot

	@command(name='prefix', brief="Changes the bot's prefix for recognizing commands.")
	@guild_only()
	@has_permissions(manage_guild=True)
	async def change_prefix(self, ctx, prefix: str):
		"""
		Changes the bot's prefix for recognizing commands. Requires Manage Server permissions.

		:param prefix: The new prefix to use.
		"""
		if len(prefix) > 5:
			Dispatcher.add(ctx, "Prefix cannot be longer than 5 characters.")

		else:
			if MongoDB.servers.find_one({'guild_id': ctx.guild.id}) is None:
				MongoDB.servers.insert_one({'guild_id': ctx.guild.id, 'prefix': prefix})
			else:
				MongoDB.servers.update_one({'guild_id': ctx.guild.id}, {'$set': {'prefix': prefix}})
			
			Dispatcher.add(ctx, f"Prefix set to {prefix}.")
		
	@change_prefix.error
	async def change_prefix_error(self, ctx, exc):
		if isinstance(exc, CheckFailure):
			Dispatcher.add(ctx, "You need the Manage Server permission to do that.")

	@has_permissions(manage_guild=True)
	@command(name='reloadCog', brief='Reloads a cog -- or all cogs if no cog is specified -- on the bot.')
	async def reload_cog(self, ctx, cog: str = None):
		"""
		Reloads a cog -- or all cogs if no cog is specified -- on the bot.

		:param cog: The name of the cog to reload.
		"""
		if cog is None:
			self.bot.reload_all_cogs()
			Dispatcher.add(ctx, "Cogs reloaded!")
		else:
			for c in self.bot.COGS:
				if c.lower() == cog.lower():
					self.bot.reload_cog(c)
					Dispatcher.add(ctx, f"{cog} cog reloaded!")
					return
			else:
				Dispatcher.add(ctx, f"There is no cog '{cog}' loaded.")
	
	@Cog.listener()
	async def on_ready(self):
		stdout("BotAdminCommands ready.")


def setup(bot):
	bot.add_cog(BotAdminCommands(bot))
