from typing import List, Union

from discord import Member, User, Forbidden, HTTPException
from discord.ext import tasks
from discord.ext.commands import Cog, Context
from pymongo import UpdateOne
from pymongo.errors import ServerSelectionTimeoutError

from Caldanai.lib.bot import Bot
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.db import MongoDB
from Caldanai.lib.rpg import Game, Area, Roles


class RpgUtilities(Cog):
	def __init__(self, bot: Bot):
		self.bot: Bot = bot
		self.bot.games = {}

	# Checks the given context to see if a game exists for it.
	async def check_game_exists(self, ctx) -> bool:
		if ctx.guild is None:
			Dispatcher.add(ctx, f"I'm afraid I can't do that from here, {ctx.author.display_name}.")
		elif ctx.guild.id not in self.bot.games.keys():
			Dispatcher.add(ctx, f"I'm afraid there is no game on this server, {ctx.author.display_name}")
		else:
			return True
		return False

	@staticmethod
	async def create_roles(game: Game):
		try:
			for role in Roles:
				game.roles[role] = await game.guild.create_role(
					name=role.value,
					mentionable=True,
					reason='Created by Caldanai Bot for directing mentions to only active players.'
				)

			for player in game.players.values():
				await player.member.add_roles(game.roles[Roles.ALL], reason="Is a player in the Caldanai Bot's game.")

		except Forbidden:
			stdout(f"No permission to create roles in guild '{game.guild.name}'.")

		except HTTPException as e:
			stdout("HTTPException while trying to add roles.")
			raise

	@staticmethod
	async def delete_roles(game: Game):
		try:
			for key, role in game.roles.items():
				if role:
					await role.delete(reason="Caldanai Bot's game removed from server")
					game.roles[key] = None

		except Forbidden:
			stdout(f"No permission to remove roles in guild '{game.guild.name}'.")

		except HTTPException as e:
			stdout("HTTPException while trying to remove roles.")
			raise

	# Adds a game to the bot's list of games
	async def add_game(
			self, game: dict = None, gid: int = None, chid: int = None, timer: bool = True,
			spawn_mins_max: int = 60, spawn_mins_min: int = 10, spawn_duration: int = 10, loot_duration: int = 5
	):
		if gid is not None and chid is not None:
			guild = self.bot.get_guild(gid) or await self.bot.fetch_guild(gid)
			channel = self.bot.get_channel(chid) or await self.bot.fetch_channel(chid)
			prefix = MongoDB.servers.find_one({'guild_id': gid})['prefix']

			if game is None:
				game = Game(
					self.bot, None, guild, channel, timer, spawn_mins_max, spawn_mins_min, spawn_duration,
					loot_duration, prefix
				)
				await RpgUtilities.create_roles(game)
				game.save()

		else:
			game = await Game.from_dict(game, self.bot)

		room0 = Area.from_plugin('0')
		game.room0 = room0
		self.bot.games[game.guild.id] = game
		stdout(f"Game added for guild: {game.guild.name} ({game.guild.id})")

	# Removes a game from the bot's list of games
	async def remove_game(self, gid: int):
		if gid in self.bot.games.keys():
			MongoDB.games.delete_one({'guild_id': gid})
			MongoDB.players.delete_many({'guild_id': gid})
			await RpgUtilities.delete_roles(self.bot.games[gid])
			del self.bot.games[gid]

	# Gets a list of games to which a user belongs.
	def get_games_for_user(self, uid: int) -> List[Game]:
		"""
		Returns a list of Games for the given discord user id.
		"""

		games = []
		if uid is None:
			return games

		players = MongoDB.players.find({'user_id': uid})
		for player in players:
			game = self.bot.games[player['guild_id']]
			games.append(game)

		return games

	# Get the game associated with a context, it if exists.
	async def get_game(self, ctx, game_idx: int = None) -> Union[Game, None]:
		"""
		Returns a Game associated with a context, or by index, if it exists. Otherwise returns None.
		"""

		game: Union[Game, None] = None
		games: List[Game] = []
		if ctx.guild is None:
			games = self.get_games_for_user(ctx.author.id)
		else:
			game = self.bot.games[ctx.guild.id]

		if len(games) == 0 and game is None:
			Dispatcher.add(ctx, f"You are not a member of any games at this time.")
			return None

		if game is None:
			if len(games) > 1 and game_idx is None:
				Dispatcher.add(
					ctx,
					f"You are playing more than one game and did not supply the game's index."
					f" Check `{ctx.prefix}games` to get the index of the game from which you wish to"
					f" view your profile, or try again from the game's channel."
				)
				return None
			elif len(games) > 1 and len(games) > game_idx >= 0:
				game = games[game_idx]
			elif len(games) == 1:
				game = games[0]
			else:
				Dispatcher.add(ctx, "No such game exists.")
				return None

		return game

	async def get_player(self, ctx, game: Game = None, notify: bool = True) -> Union[Player, None]:
		"""
		Returns a Player associated with a context, or None if the Player does not exist.
		"""

		if game is None or not isinstance(game, Game):
			game: Game = await self.get_game(ctx)

		if game is None:
			return None

		if isinstance(ctx, Context):
			if ctx.author.id not in game.players.keys():
				if notify:
					Dispatcher.add(
						game.channel,
						f'Why, {ctx.author.display_name}! You are not even playing the game! Try `{ctx.prefix}game '
						f'join`'
					)
			else:
				return game.players[ctx.author.id]
		elif isinstance(ctx, (Member, User)) and ctx.id in game.players.keys():
			return game.players[ctx.id]

		return None

	# Returns a tuple containing (game, player) if both exist.
	async def get_game_and_player(self, ctx, notify: bool = True) -> (Game, Player):
		"""
		Returns a tuple containing a Game and Player if they exist, or None for one or both upon failure.
		"""

		game: Game = await self.get_game(ctx)
		if game is None:
			return None, None

		player: Player = await self.get_player(ctx, game, notify)
		return game, player

	@tasks.loop(minutes=1)
	async def save_game_data(self):
		"""Database loop to save player and game data."""

		try:

			games = [
				UpdateOne(
					{'guild_id': g.guild.id},
					{'$set': g.to_dict()}
				) for g in self.bot.games.values()
			]

			MongoDB["games"].bulk_write(games, ordered=False)

			dirty = [
				(p, UpdateOne(
					{"guild_id": p.guild_id, "user_id": p.user_id},
					{"$set": p.to_dict()},
					upsert=True
				)) for g in self.bot.games.values() for p in g.players.values() if p.is_dirty
			]

			if len(dirty) > 0:
				result = MongoDB["players"].bulk_write([d[1] for d in dirty], ordered=False)

				for idx, _id in result.upserted_ids.items():
					dirty[idx][0].id = _id

				for p, _ in dirty:
					p.is_dirty = False

		except ServerSelectionTimeoutError:
			stdout("Unable to connect to DB.")

	# Additional maintenance after cog loads.
	@Cog.listener()
	async def on_ready(self):
		games = MongoDB.games.find()
		for g in games:
			await self.add_game(game=g)
		self.save_game_data.start()
		stdout("RpgUtilities ready.")


def setup(bot):
	bot.add_cog(RpgUtilities(bot))
