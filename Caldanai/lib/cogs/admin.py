from discord.ext.commands import Cog, CheckFailure, command, has_permissions, guild_only

from ...Logger import stdout
from ...db.db import MongoDB


class Admin(Cog):
	def __init__(self, bot):
		self.bot = bot

	@command(name='prefix', brief="Changes the bot's prefix for recognizing commands.")
	@guild_only()
	@has_permissions(manage_guild=True)
	async def change_prefix(self, ctx, prefix: str):
		"""Changes the bot's prefix for recognizing commands.

		To change the prefix requires the user having Manage Server permissions.
		"""
		if len(prefix) > 5:
			await ctx.send("Prefix cannot be longer than 5 characters.")

		else:
			if MongoDB.servers.find_one({'guildId': ctx.guild.id}) is None:
				MongoDB.servers.insert_one({'guildId': ctx.guild.id, 'prefix': prefix})
			else:
				MongoDB.servers.update_one({'guildId': ctx.guild.id}, {'$set': {'prefix': prefix}})
			
			await ctx.send(f"Prefix set to {prefix}.")
		
	@change_prefix.error
	async def change_prefix_error(self, ctx, exc):
		if isinstance(exc, CheckFailure):
			await ctx.send("You need the Manage Server permission to do that.")

	@has_permissions(manage_guild=True)
	@command(name='reloadCog', brief='Reloads a cog -- or all cogs if no cog is specified -- on the bot.')
	async def reload_cog(self, ctx, cog: str = None):
		"""Reloads a cog -- or all cogs if no cog is specified -- on the bot.
		"""
		if cog is None:
			self.bot.reload_all_cogs()
			await ctx.send("Cogs reloaded!")
		else:
			if cog in self.bot.COGS:
				self.bot.reload_cog(cog)
				await ctx.send(f"{cog} cog reloaded!".capitalize())
			else:
				await ctx.send(f"There is no cog '{cog}' loaded.")
	
	@Cog.listener()
	async def on_ready(self):
		stdout("Admin Cog ready.")


def setup(bot):
	bot.add_cog(Admin(bot))
