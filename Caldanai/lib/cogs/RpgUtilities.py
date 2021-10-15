from typing import List, Union

from discord.ext import tasks
from discord.ext.commands import Cog
from pymongo import UpdateOne
from pymongo.errors import ServerSelectionTimeoutError

from Caldanai.lib.bot import Bot
from ..rpg.creatures.player import Player
from ...Dispatcher import Dispatcher
from ...Logger import stdout
from ...db.db import MongoDB
from ..rpg.game import Game


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
		stdout(f"Game added for guild: {game.guild.name} ({game.guild.id})")

	# Removes a game from the bot's list of games
	def remove_game(self, gid: int):
		if gid in self.bot.games.keys():
			MongoDB.games.delete_one({'guildId': gid})
			MongoDB.players.delete_many({'guildId': gid})
			del self.bot.games[gid]

	# Gets a list of games to which a user belongs.
	def get_games_for_user(self, uid: int) -> List[Game]:
		"""
		Returns a list of Games for the given discord user id.
		"""

		games = []
		if uid is None:
			return games

		players = MongoDB.players.find({'userId': uid})
		for player in players:
			game = self.bot.games[player['guildId']]
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

	# Gets the player associated with a context, if any exists
	async def get_player(self, ctx, game: Game = None, notify: bool = True) -> Union[Player, None]:
		"""
		Returns a Player associated with a context, or None if the Player does not exist.
		"""

		if game is None or not isinstance(game, Game):
			game: Game = await self.get_game(ctx)

		if game is None:
			return None

		if ctx.author.id not in game.players.keys():
			if notify:
				Dispatcher.add(
					game.channel,
					f'Why, {ctx.author.display_name}! You are not even playing the game! Try `{ctx.prefix}game join`'
				)
		else:
			return game.players[ctx.author.id]
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
	async def save_players(self):
		"""Database loop to save player data."""

		try:
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

		except ServerSelectionTimeoutError:
			stdout("Unable to connect to DB.")

	# Additional maintenance after cog loads.
	@Cog.listener()
	async def on_ready(self):
		games = MongoDB.games.find()
		for g in games:
			await self.add_game(game=g)
		self.save_players.start()
		stdout("RpgUtilities ready.")


def setup(bot):
	bot.add_cog(RpgUtilities(bot))
