from discord import Embed, Guild
from discord.ext.commands import Cog, guild_only, has_permissions, group, cooldown, BucketType
from Caldanai.lib.bot import Bot
from .RpgUtilities import RpgUtilities
from ...Dispatcher import Dispatcher
from ...Logger import stdout
from ...db.db import MongoDB


class RpgAdminCommands(Cog):
	def __init__(self, bot: Bot):
		self.bot: Bot = bot
		self.bot.games = {}
		self.utilCog: RpgUtilities = None

	def utils(self) -> RpgUtilities:
		if self.utilCog is None:
			self.utilCog = self.bot.get_cog("RpgUtilities")
		return self.utilCog

	@group(aliases=["rpg"], brief="Groups the various Game commands.")
	@guild_only()
	@has_permissions(manage_guild=True)
	async def game_cmd(self, ctx):
		"""
		Groups the various game commands for administrators.
		"""

		if ctx.invoked_subcommand is None:
			Dispatcher.add(ctx, "This command cannot be used on its own.")
			return

		if ctx.guild is None:
			Dispatcher.add(ctx, "A game cannot be started or ended from a direct message or a group message.")
			return

	# Adds a game to the bot
	@game_cmd.command(brief="Begins an RPG game on the server in the current channel.")
	async def create(self, ctx) -> bool:
		"""
		Begins an RPG game on the server in the current channel. Only a single game per server is supported.
		"""

		if MongoDB.games.find_one({'guildId': ctx.guild.id}) is not None:
			Dispatcher.add(ctx, "Only a single game per server is supported.")

		else:
			if MongoDB.games.insert_one({'guildId': ctx.guild.id, 'channelId': ctx.id}):
				await self.utils().add_game(gid=ctx.guild.id, chid=ctx.id)
				Dispatcher.add(ctx, "A new game has been started in this channel!")
				return True
		
		return False
	
	# Removes a game from the bot and the database
	@game_cmd.command(brief="Removes the RPG game for this server. WARNING: Cannot be undone.")
	async def remove(self, ctx) -> None:
		"""
		Removes the RPG game for this server. WARNING: Cannot be undone.
		Upon removal, a new game may be created but data from the removed game is not recoverable.
		"""

		if not await self.utils().check_game_exists(ctx):
			return

		self.utils().remove_game(ctx.guild.id)
		Dispatcher.add(ctx, "The game has been removed.")

	@group(brief="Displays or sets various spawning options.")
	@guild_only()
	@has_permissions(manage_guild=True)
	@cooldown(1, 5, BucketType.guild)
	async def spawn(self, ctx):
		"""
		Displays or sets various spawning options.
		(5-second cool-down server-wide)
		"""

		if not await self.utils().check_game_exists(ctx):
			return

		if ctx.invoked_subcommand is None:
			guild: Guild = ctx.guild
			game = self.bot.games[ctx.guild.id]
			embed = Embed(title="Current Spawn Settings")
			embed.set_thumbnail(url=guild.icon_url)
			embed.add_field(name="Spawn Timing", value=f"{game.minutes_min} - {game.minutes_max} minutes", inline=True)
			embed.add_field(name="Spawn Duration", value=f"{game.spawn_duration} minutes", inline=True)
			embed.add_field(name="Loot Duration", value=f"{game.loot_duration} minutes", inline=True)
			embed.add_field(name="Spawning Enabled", value=str(game.use_spawn_timer), inline=True)
			Dispatcher.add(ctx, embed=embed)

	# Sets the minimum time between monster spawns for a game, in minutes
	@spawn.command(
		aliases=["min"],
		brief="Sets or displays the minimum time between monster spawns for a game, in minutes"
	)
	async def minimum(self, ctx, minutes: int = None):
		"""Sets or displays the minimum time between monster spawns for a game, in minutes"""

		game = self.bot.games[ctx.guild.id]		
		if minutes is None:
			Dispatcher.add(game.channel, f"Minimum spawn time is {game.minutes_min} minutes.")
			return

		if minutes <= 1:
			Dispatcher.add(game.channel, "Minimum spawn time must be more than 1 minute.")
			return

		game.minutes_min = minutes
		game.save()
		Dispatcher.add(game.channel, "Minimum spawn time has been set.")

	# Sets the maximum time between monster spawns for a game, in minutes
	@spawn.command(
		aliases=["max"],
		brief="Sets or displays the maximum time between monster spawns for a game, in minutes."
	)
	async def maximum(self, ctx, minutes: int = None):
		"""Sets or displays the maximum time between monster spawns for a game, in minutes."""

		game = self.bot.games[ctx.guild.id]
		if minutes is None:
			Dispatcher.add(game.channel, f"Maximum spawn time is {game.minutes_max} minutes.")
			return
		
		if minutes <= 1:
			Dispatcher.add(game.channel, "Maximum spawn time must be more than 1 minute.")
			return

		game.minutes_max = minutes
		game.save()
		Dispatcher.add(game.channel, "Maximum spawn time has been set.")

	# Sets the spawn duration for a game, in minutes
	@spawn.command(aliases=["dur", "d"], brief="Sets or displays the spawn duration for a game, in minutes.")
	async def duration(self, ctx, minutes: int = None):
		"""Sets or displays the spawn duration for a game, in minutes."""

		game = self.bot.games[ctx.guild.id]
		if minutes is None:
			Dispatcher.add(game.channel, f"Spawn duration is {game.spawn_duration} minutes.")
			return

		if minutes <= 1:
			Dispatcher.add(game.channel, "Spawn duration must be more than 1 minute.")
			return

		game.spawn_duration = minutes
		game.save()
		Dispatcher.add(game.channel, "Spawn duration has been set.")

	# Sets the loot duration for a game, in minutes
	@spawn.command(brief="Sets or displays the loot duration for a game, in minutes.")
	async def loot(self, ctx, minutes: int = None):
		"""Sets or displays the loot duration, in minutes."""

		game = self.bot.games[ctx.guild.id]
		if minutes is None:
			Dispatcher.add(game.channel, f"Loot duration is {game.loot_duration} minutes.")
			return

		if minutes <= 1:
			Dispatcher.add(game.channel, "Loot duration must be more than 1 minute.")
			return

		game.loot_duration = minutes
		game.save()
		Dispatcher.add(game.channel, "Loot duration has been set.")
	
	# Sets the spawning for a game on or off
	@spawn.command(brief="Sets or displays the spawning for a game on or off.")
	async def set(self, ctx, value: str = None):
		"""Sets or displays the spawning for a game on or off."""

		game = self.bot.games[ctx.guild.id]
		if value is None:
			Dispatcher.add(game.channel, f"Spawning is currently {'en' if game.use_spawn_timer else 'dis'}abled.")
			return

		value = value.lower()
		if any(v == value for v in ['1', 'on', 'true', 'enabled']):
			if not game.use_spawn_timer:
				game.use_spawn_timer = True
				game.spawn_check.start()
			else:
				Dispatcher.add(game.channel, "Spawning is already enabled.")
		
		elif any(v == value for v in ['0', 'off', 'false', 'disabled']):
			if game.use_spawn_timer:
				game.use_spawn_timer = False
			else:
				Dispatcher.add(game.channel, "Spawning is already disabled.")

		else:
			return
		
		game.save()
		Dispatcher.add(game.channel, "Spawning has been set.")
	
	# Forces a monster to spawn.
	@spawn.command(brief="Forces a monster to spawn.")
	async def monster(self, ctx):
		"""Forces a monster to spawn."""

		game = self.bot.games[ctx.guild.id]
		if game.monster is None:
			game.do_combat.start()
			return
		
		Dispatcher.add(game.channel, f"There is already a {game.monster.name} present!")
	
	# Forces a monster to die.
	@spawn.command(brief="Forces a monster to die.")
	async def kill(self, ctx):
		"""Forces a monster to die."""

		game = self.bot.games[ctx.guild.id]
		if game.monster is None:
			Dispatcher.add(game.channel, "There is no monster present!")
			return
		
		await game.kill_monster()

	# Additional maintenance after cog loads.
	@Cog.listener()
	async def on_ready(self):
		stdout("RpgAdminCommands ready.")


def setup(bot):
	bot.add_cog(RpgAdminCommands(bot))
