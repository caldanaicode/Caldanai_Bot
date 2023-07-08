from discord.ext import tasks
from discord.ext.commands import Cog, CheckFailure, command, has_permissions, guild_only, Context

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.db import DB

from time import sleep


class BotAdminCommands(Cog):
	def __init__(self, bot):
		self.bot = bot

	@command(name='prefix', brief="Changes the bot's prefix for recognizing commands.")
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
				if DB.get_server_by_guild_id(ctx.guild.id) is None:
					DB.insert_server(ctx.guild.id, ctx.guild.name, prefix=prefix)
				else:
					DB.update_server_prefix(ctx.guild.id, prefix)

				Dispatcher.add(ctx, f"Prefix set to {prefix}.")

			except Exception as e:
				stdout(e)
				Dispatcher.add(
					ctx,
					"There appears to be an issue with the database at the moment. Please try again later."
				)

	@change_prefix.error
	async def change_prefix_error(self, ctx: Context, exc):
		if isinstance(exc, CheckFailure):
			Dispatcher.add(ctx, "You need the Manage Server permission to do that.")

	@has_permissions(manage_guild=True)
	@command(name='reloadCog', brief='Reloads a cog -- or all cogs if no cog is specified -- on the bot.')
	async def reload_cog(self, ctx: Context, cog: str = None):
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

	async def wait_to_close(self, seconds=5):
		sleep(5)
		await self.bot.close()

	@has_permissions(administrator=True)
	@command(name='shutdown', brief='Shuts down the bot with an optional message.')
	async def reload_cog(self, ctx: Context, *msg: str):
		"""
		Shuts down the bot with an optional message to be sent to servers that the bot is running on.

		:param msg: The message to announce.
		"""

		if msg:
			try:
				games = list(DB.find_all_games())
				for game in games:
					Dispatcher.add(self.bot.get_channel(game["channel_id"]), ' '.join(msg))

				Dispatcher.flush = True
				flush_dispatcher.start(self.bot)
				await self.bot.wait_for('disconnect')

			except Exception as e:
				stdout(e)

			finally:
				exit(0)

	@Cog.listener()
	async def on_ready(self):
		stdout("BotAdminCommands ready.")


async def setup(bot):
	await bot.add_cog(BotAdminCommands(bot))


@tasks.loop(seconds=1)
async def flush_dispatcher(bot):
	if Dispatcher.queue.empty():
		flush_dispatcher.stop()
		Dispatcher.flush = False
		await bot.close()
		stdout("Connection closed by shutdown command.")
