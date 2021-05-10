from discord import Embed, Guild
from discord.ext import tasks
from discord.ext.commands import Cog, guild_only, has_permissions, group
from pymongo import UpdateOne

from Caldanai.lib.bot import Bot
from ...db.db import MongoDB
from ..rpg.game import Game


class RpgAdmin(Cog):
	def __init__(self, bot: Bot):
		self.bot: Bot = bot
		self.bot.games = {}

	# Checks the given context to see if a game exists for it.
	async def check_game_exists(self, ctx) -> bool:
		if ctx.guild is None:
			await ctx.send(f"I'm afraid I can't do that from here, {ctx.author.display_name}.")
		elif ctx.guild.id not in self.bot.games.keys():
			await ctx.send(f"I'm afraid there is no game on this server, {ctx.author.display_name}")
		else:
			return True
		return False

	# Adds a game to the bot's list of games
	async def add_game(
			self, game: dict = None, gid: int = None, chid: int = None, timer: bool = True,
			spawnMinutesMax: int = 60, spawnMinutesMin: int = 10, spawnDuration: int = 10, lootDuration: int = 5
	):
		if gid is not None and chid is not None:
			guild = self.bot.get_guild(gid) or await self.bot.fetch_guild(gid)
			channel = self.bot.get_channel(chid) or await self.bot.fetch_channel(chid)
			prefix = MongoDB.servers.find_one({'guildId': gid})['prefix']
		
			if game is None:
				game = Game(
					self.bot, None, guild, channel, timer, spawnMinutesMax, spawnMinutesMin, spawnDuration,
					lootDuration, prefix
				)
				game.save()
		
		else:
			game = await Game.from_dict(game, self.bot)

		self.bot.games[game.guild.id] = game
		print(f"Game added for guild: {game.guild.name} ({game.guild.id})")

	# Removes a game from the bot's list of games
	def remove_game(self, gid: int):
		if gid in self.bot.games.keys():
			MongoDB.games.delete_one({'guildId': gid})
			MongoDB.players.delete_many({'guildId': gid})
			del self.bot.games[gid]
		
	# ----------------------------------------------------------

	@group(aliases=["rpg"])
	@guild_only()
	@has_permissions(manage_guild=True)
	async def game_cmd(self, ctx):
		if ctx.invoked_subcommand is None:
			await ctx.send("This command cannot be used on its own.")
			return

		if ctx.guild is None:
			await ctx.send("A game cannot be started or ended from a direct message or a group message.")
			return

	# Adds a game to the bot
	@game_cmd.command(brief="Begins an RPG game on the server in the current channel.")
	async def create(self, ctx) -> bool:
		"""Begins an RPG game on the server in the current channel.

		Only a single game per server is supported.
		"""
		if MongoDB.games.find_one({'guildId': ctx.guild.id}) is not None:
			await ctx.send("Only a single game per server is supported.")

		else:
			if MongoDB.games.insert_one({'guildId': ctx.guild.id, 'channelId': ctx.id}):
				await self.add_game(gid=ctx.guild.id, chid=ctx.id)
				await ctx.send("A new game has been started in this channel!")
				return True
		
		return False
	
	# Removes a game from the bot and the database
	@game_cmd.command(brief="Removes the RPG game for this server. WARNING: Cannot be undone.")
	async def remove(self, ctx) -> None:
		"""Removes the RPG game for this server. WARNING: Cannot be undone.

		Upon removal, a new game may be created but data from the removed game in not recoverable.
		"""
		if not await self.check_game_exists(ctx):
			return

		self.remove_game(ctx.guild.id)
		await ctx.send("The game has been removed.")

	@group()
	@guild_only()
	@has_permissions(manage_guild=True)
	async def spawn(self, ctx):
		if not await self.check_game_exists(ctx):
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
			await ctx.send(embed=embed)

	# Sets the minimum time between monster spawns for a game, in minutes
	@spawn.command(aliases=["min"], brief="Sets the minimum time between monster spawns for a game, in minutes")
	async def minimum(self, ctx, minutes: int = None):
		"""Sets the minimum time between monster spawns for a game, in minutes"""
		game = self.bot.games[ctx.guild.id]		
		if minutes is None:
			await game.send(f"Minimum spawn time is {game.minutes_min} minutes.")
			return

		if minutes <= 1:
			await game.send("Minimum spawn time must be more than 1 minute.")
			return

		game.minutes_min = minutes
		game.save()
		await game.send("Minimum spawn time has been set.")

	# Sets the maximum time between monster spawns for a game, in minutes
	@spawn.command(aliases=["max"], brief="Sets the maximum time between monster spawns for a game, in minutes.")
	async def maximum(self, ctx, minutes: int = None):
		"""Sets the maximum time between monster spawns for a game, in minutes."""
		game = self.bot.games[ctx.guild.id]
		if minutes is None:
			await game.send(f"Maximum spawn time is {game.minutes_max} minutes.")
			return
		
		if minutes <= 1:
			await game.send("Maximum spawn time must be more than 1 minute.")
			return

		game.minutes_max = minutes
		game.save()
		await game.send("Maximum spawn time has been set.")

	# Sets the spawn duration for a game, in minutes
	@spawn.command(aliases=["dur", "d"], brief="Sets the spawn duration for a game, in minutes.")
	async def duration(self, ctx, minutes: int = None):
		"""Sets the spawn duration for a game, in minutes."""
		game = self.bot.games[ctx.guild.id]
		if minutes is None:
			await game.send(f"Spawn duration is {game.spawn_duration} minutes.")
			return

		if minutes <= 1:
			await game.send("Spawn duration must be more than 1 minute.")
			return

		game.spawn_duration = minutes
		game.save()
		await game.send("Spawn duration has been set.")

	# Sets the loot duration for a game, in minutes
	@spawn.command(brief="Sets the loot duration for a game, in minutes.")
	async def loot(self, ctx, minutes: int = None):
		game = self.bot.games[ctx.guild.id]
		if minutes is None:
			await game.send(f"Loot duration is {game.loot_duration} minutes.")
			return

		if minutes <= 1:
			await game.send("Loot duration must be more than 1 minute.")
			return

		game.loot_duration = minutes
		game.save()
		await game.send("Loot duration has been set.")
	
	# Sets the spawning for a game on or off
	@spawn.command(brief="Sets the spawning for a game on or off.")
	async def set(self, ctx, value: str = None):
		game = self.bot.games[ctx.guild.id]
		if value is None:
			await game.send(f"Spawning is currently {'en' if game.use_spawn_timer else 'dis'}abled.")
			return

		value = value.lower()
		if any(v == value for v in ['1', 'on', 'true', 'enabled']):
			if not game.use_spawn_timer:
				game.use_spawn_timer = True
				game.spawn_check.start()
			else:
				await game.send("Spawning is already enabled.")
		
		elif any(v == value for v in ['0', 'off', 'false', 'disabled']):
			if game.use_spawn_timer:
				game.use_spawn_timer = False
			else:
				await game.send("Spawning is already disabled.")

		else:
			return
		
		game.save()
		await game.send("Spawning has been set.")
	
	# Forces a monster to spawn.
	@spawn.command(brief="Forces a monster to spawn.")
	async def monster(self, ctx):
		game = self.bot.games[ctx.guild.id]
		if game.monster is None:
			await game.spawn()
			return
		
		await game.send(f"There is already a {game.monster.name} present!")
	
	# Forces a monster to die.
	@spawn.command(brief="Forces a monster to die.")
	async def kill(self, ctx):
		game = self.bot.games[ctx.guild.id]
		if game.monster is None:
			await game.send("There is no monster present!")
			return
		
		await game.kill_monster()

	# ------------------------------------------------------

	@tasks.loop(minutes=1)
	async def save_players(self):
		dirty = [
			(p, UpdateOne(
				{"guildId": p.guildId, "userId": p.userId},
				{"$set": p.to_dict()},
				upsert=True
			)) for g in self.bot.games.values() for p in g.players.values() if p.isDirty
		]

		if len(dirty) > 0:
			result = MongoDB["players"].bulk_write([d[1] for d in dirty], ordered=False)
			for idx, _id in result.upserted_ids.items():
				dirty[idx][0].id = _id

		# dirty_players = []
		# upserted_players = []
		# for g in self.bot.games.values():
		# 	for p in g.players.values():
		# 		if p.isDirty:
		# 			dirty_players.append(
		# 				UpdateOne(
		# 					{"guildId": p.guildId, "userId": p.userId},
		# 					{"$set": p.to_dict()},
		# 					upsert=True
		# 				)
		# 			)
		# 			upserted_players.append(p)
		#
		# if len(dirty_players) > 0:
		# 	result = MongoDB["players"].bulk_write(dirty_players, ordered=False)
		# 	for idx, _id in result.upserted_ids.items():
		# 		upserted_players[idx].id = _id

	# Additional maintenance after cog loads.
	@Cog.listener()
	async def on_ready(self):
		games = MongoDB.games.find()
		for g in games:
			await self.add_game(game=g)
		self.save_players.start()
		print("RPG Admin Cog ready.")


def setup(bot):
	bot.add_cog(RpgAdmin(bot))
