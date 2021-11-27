from typing import Optional

from discord import Embed, Guild
from discord.ext.commands import Cog, guild_only, has_permissions, group, cooldown, BucketType
from Caldanai.lib.bot import Bot
from .RpgUtilities import RpgUtilities
from ..rpg.creatures.player import Player
from ..rpg.inventory import Inventory
from ...Dispatcher import Dispatcher
from ...Logger import stdout
from ...db import MongoDB


class RpgAdminCommands(Cog):
	def __init__(self, bot: Bot):
		self.bot: Bot = bot
		self.bot.games = self.bot.games or {}
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
		Groups the various game commands for administrators. This command cannot be used on its own.
		"""

		if ctx.invoked_subcommand is None:
			Dispatcher.add(ctx, "This command cannot be used on its own.")
			return

		if ctx.guild is None:
			Dispatcher.add(ctx, "A game cannot be started or ended from a direct message or a group message.")
			return

	@game_cmd.command(brief="Begins an RPG game on the server in the current channel.")
	async def create(self, ctx) -> bool:
		"""
		Begins an RPG game on the server in the current channel. Only a single game per server is supported.
		"""

		if MongoDB.games.find_one({'guild_id': ctx.guild.id}) is not None:
			Dispatcher.add(ctx, "Only a single game per server is supported.")

		else:
			if MongoDB.games.insert_one({'guild_id': ctx.guild.id, 'channelId': ctx.channel.id}):
				await self.utils().add_game(gid=ctx.guild.id, chid=ctx.channel.id)
				Dispatcher.add(ctx, "A new game has been started in this channel!")
				return True

		return False

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
		Used alone, displays the various spawning options and information. See the subcommands for settings those options.

		(5-second cool-down server-wide)
		"""

		if not await self.utils().check_game_exists(ctx):
			return

		if ctx.invoked_subcommand is None:
			guild: Guild = ctx.guild
			game = self.bot.games[ctx.guild.id]
			r, i = game.game_clock.find_routine('do_spawn')
			routine = r[i] if r else None

			embed = Embed(title="Current Spawn Settings")
			embed.set_thumbnail(url=guild.icon_url)
			embed.add_field(name="Spawn Timing", value=f"{game.minutes_min} - {game.minutes_max} minutes", inline=True)
			embed.add_field(name="Spawn Duration", value=f"{int(game.spawn_duration / 60)} minutes", inline=True)
			embed.add_field(name="Loot Duration", value=f"{int(game.loot_duration / 60)} minutes", inline=True)
			embed.add_field(name="Spawning Enabled", value=str(game.use_spawn_timer), inline=True)

			if routine:
				next_spawn = routine.time_added - game.game_clock.get_tick_time() + routine.seconds
				embed.add_field(name="Next Spawn", value=f"{int(next_spawn / 60)} minutes")

			Dispatcher.add(ctx, embed=embed)

	@spawn.command(
		aliases=["min"],
		brief="Sets or displays the minimum time between monster spawns for a game, in minutes"
	)
	async def minimum(self, ctx, minutes: int = None):
		"""
		Sets or displays the minimum time between monster spawns for a game, in minutes

		:param minutes: The minimum number of minutes before another monster can spawn after the previous monster is removed.
		"""

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

	@spawn.command(
		aliases=["max"],
		brief="Sets or displays the maximum time between monster spawns for a game, in minutes."
	)
	async def maximum(self, ctx, minutes: int = None):
		"""
		Sets or displays the maximum time between monster spawns for a game, in minutes.

		:param minutes: The maximum number of minutes before another monster can be spawned after the previous is removed.
		"""

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

	@spawn.command(aliases=["dur", "d"], brief="Sets or displays the spawn duration for a game, in minutes.")
	async def duration(self, ctx, minutes: int = None):
		"""
		Sets or displays the spawn duration for a game, in minutes.

		:param minutes: The number of minutes that a monster will wait for combat on the first round. This time is halved for additional rounds of combat.
		"""

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

	@spawn.command(brief="Sets or displays the loot duration for a game, in minutes.")
	async def loot(self, ctx, minutes: int = None):
		"""
		Sets or displays the loot duration, in minutes. If a monster has loot after death, the spawn timer does not begin until after the loot timer expires.

		:param minutes: The number of minutes that loot will be available before removal.
		"""

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

	@spawn.command(aliases=['set'], brief="Sets or displays the spawning for a game on or off.")
	async def spawn_set(self, ctx, msg: str = None):
		"""
		Sets or displays the spawning for a game on or off.

		:param msg: To enable spawning use 1, on, true, or enabled. To disable, use 0, off, false, or disabled.
		"""

		game = self.bot.games[ctx.guild.id]
		if msg is None:
			Dispatcher.add(game.channel, f"Spawning is currently {'en' if game.use_spawn_timer else 'dis'}abled.")
			return

		msg = msg.lower()
		if any(v == msg for v in ['1', 'on', 'true', 'enabled']):
			if not game.use_spawn_timer:
				game.use_spawn_timer = True
				await game.set_spawn_timer()
			else:
				Dispatcher.add(game.channel, "Spawning is already enabled.")

		elif any(v == msg for v in ['0', 'off', 'false', 'disabled']):
			if game.use_spawn_timer:
				game.use_spawn_timer = False
				game.game_clock.remove_routine(game.do_spawn)
			else:
				Dispatcher.add(game.channel, "Spawning is already disabled.")

		else:
			return

		game.save()
		Dispatcher.add(game.channel, "Spawning has been set.")

	@spawn.command(brief="Forces a monster to spawn.")
	async def monster(self, ctx, monster: Optional[str] = None):
		"""
		Forces a monster to spawn.

		:param monster: the filename of the monster to spawn. If not provided, randomly chooses an available monster.
		"""

		game = self.bot.games[ctx.guild.id]
		if game.monster is None:
			game.game_clock.remove_routine(game.do_spawn)
			await game.do_spawn(monster)
			return

		Dispatcher.add(game.channel, f"There is already a {game.monster.name} present!")

	# Forces a monster to die.
	@spawn.command(brief="Forces the current monster to die.")
	async def kill(self, ctx):
		"""
		Forces the current monster to die.
		"""

		game = self.bot.games[ctx.guild.id]
		if game.monster is None:
			Dispatcher.add(game.channel, "There is no monster present!")
			return

		await game.kill_monster()

	@spawn.command(brief="Spawns the requested item to the given player's inventory.")
	async def item(self, ctx, item_name: str):
		"""
		Spawns the requested item to the given player's inventory.

		:param item_name: The item name.
		"""

		game = self.bot.games[ctx.guild.id]
		target: Player = None

		if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
			target = await self.utils().get_player(ctx.message.mentions[0])

		if target is None:
			target = await self.utils().get_player(ctx)

		if target is None or item_name is None:
			return

		item = Inventory.load_item(item_name)
		if item:
			target.give_item(item)
			Dispatcher.add(game.channel, f"{item.get_full_name().capitalize()} was given to {target.name}.")
			return

		Dispatcher.add(
			game.channel,
			"Unable to spawn item. Please check the spelling of the item name."
		)

	@group(brief="Displays or sets various ambience options.")
	@guild_only()
	@has_permissions(manage_guild=True)
	@cooldown(1, 5, BucketType.guild)
	async def ambience(self, ctx):
		"""
		Displays or sets various ambience options.
		(5-second cool-down server-wide)
		"""

		if not await self.utils().check_game_exists(ctx):
			return

		if ctx.invoked_subcommand is None:
			guild: Guild = ctx.guild
			game = self.bot.games[ctx.guild.id]
			embed = Embed(title="Current Ambience Settings")
			embed.set_thumbnail(url=guild.icon_url)
			embed.add_field(name="Ambience Enabled", value=f"{game.enable_ambience}", inline=True)
			Dispatcher.add(ctx, embed=embed)

	@ambience.command(aliases=['set'], brief="Sets ambience for a game on or off.")
	async def ambience_set(self, ctx, value: str = None):
		"""
		Sets ambience for a game on or off. If no setting is supplied, displays the current setting.

		:param value: To enable ambience use 1, on, true, or enabled. To disable, use 0, off, false, or disabled.
		"""

		game = self.bot.games[ctx.guild.id]
		if value is None:
			Dispatcher.add(game.channel, f"Ambience is currently {'en' if game.enable_ambience else 'dis'}abled.")
			return

		value = value.lower()
		if value.lower() in ['1', 'on', 'true', 'enabled']:
			if not game.enable_ambience:
				game.enable_ambience = True
				game.game_clock.add_routine(game.do_ambience, 1)
			else:
				Dispatcher.add(game.channel, "Ambience is already enabled.")
				return

		elif value.lower() in ['0', 'off', 'false', 'disabled']:
			if game.enable_ambience:
				game.enable_ambience = False
				game.game_clock.remove_routine(game.do_ambience)
			else:
				Dispatcher.add(game.channel, "Ambience is already disabled.")
				return

		else:
			Dispatcher.add(game.channel, f"I'm afraid I didn't understand that.")
			return

		game.save()
		Dispatcher.add(game.channel, "Ambience has been set.")

	# Additional maintenance after cog loads.
	@Cog.listener()
	async def on_ready(self):
		stdout("RpgAdminCommands ready.")


def setup(bot):
	bot.add_cog(RpgAdminCommands(bot))
