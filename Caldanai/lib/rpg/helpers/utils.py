from typing import List, Union

from discord import Forbidden, HTTPException
from discord.ext import tasks
from pymongo import UpdateOne
from pymongo.errors import ServerSelectionTimeoutError

from Caldanai.lib.bot import Bot
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.db import MongoDB
from Caldanai.lib.rpg import Game, Area, Roles


class RpgUtilities:
	bot: Bot = None
	is_initialized: bool = False

	# Checks the given context to see if a game exists for it.
	@staticmethod
	async def check_game_exists(ctx) -> bool:
		if ctx.guild is None:
			Dispatcher.add(ctx, f"I'm afraid I can't do that from here, {ctx.author.display_name}.")
		elif ctx.guild.id not in RpgUtilities.bot.games.keys():
			Dispatcher.add(ctx, f"I'm afraid there is no game on this server, {ctx.author.display_name}")
		else:
			return True
		return False

	@staticmethod
	async def create_roles(game: Game):
		try:
			pmgr = game.player_manager
			for role in Roles:
				if role not in pmgr.roles.keys() or (role in pmgr.roles.keys() and not pmgr.roles[role]):
					pmgr.roles[role] = await game.guild.create_role(
						name=role.value,
						mentionable=True,
						reason='Created by Caldanai Bot for directing mentions to only active players.'
					)

			for player in pmgr.players.values():
				if pmgr.roles[Roles.ALL] not in player.member.roles:
					await player.member.add_roles(
						pmgr.roles[Roles.ALL], reason="Is a player in the Caldanai Bot's game."
					)

		except Forbidden:
			stdout(f"No permission to create roles in guild '{game.guild.name}'.")

		except HTTPException as e:
			stdout(f"HTTPException while trying to add roles: {e}")
			raise

	@staticmethod
	async def delete_roles(game: Game):
		try:
			for key, role in game.player_manager.roles.items():
				if role:
					await role.delete(reason="Caldanai Bot's game removed from server")
					game.player_manager.roles[key] = None

		except Forbidden:
			stdout(f"No permission to remove roles in guild '{game.guild.name}'.")

		except HTTPException as e:
			stdout(f"HTTPException while trying to remove roles: {e}")
			raise

	# Adds a game to the bot's list of games
	@staticmethod
	async def add_game(
			game: dict = None, gid: int = None, chid: int = None, timer: bool = True,
			spawn_mins_max: int = 60, spawn_mins_min: int = 10, spawn_duration: int = 10, loot_duration: int = 5
	):
		if gid is not None and chid is not None:
			guild = RpgUtilities.bot.get_guild(gid) or await RpgUtilities.bot.fetch_guild(gid)
			channel = RpgUtilities.bot.get_channel(chid) or await RpgUtilities.bot.fetch_channel(chid)

			try:
				prefix = MongoDB.servers.find_one({'guild_id': gid})['prefix']
			except Exception as e:
				stdout(e)
				return

			if game is None:
				game = Game(
					RpgUtilities.bot, None, guild, channel, timer, spawn_mins_max, spawn_mins_min, spawn_duration,
					loot_duration, prefix
				)
				await RpgUtilities.create_roles(game)
				game.save()

		else:
			game = await Game.from_dict(game, RpgUtilities.bot)

		room0 = Area.from_plugin('0')
		game.room0 = room0
		RpgUtilities.bot.games[game.guild.id] = game
		stdout(f"Game added for guild: {game.guild.name} ({game.guild.id})")

	# Removes a game from the bot's list of games
	@staticmethod
	async def remove_game(gid: int):
		if gid in RpgUtilities.bot.games.keys():
			try:
				MongoDB.games.delete_one({'guild_id': gid})
				MongoDB.players.delete_many({'guild_id': gid})
				await RpgUtilities.delete_roles(RpgUtilities.bot.games[gid])
				del RpgUtilities.bot.games[gid]

			except Exception as e:
				stdout(e)

	# Gets a list of games to which a user belongs.
	@staticmethod
	def get_games_for_user(uid: int) -> List[Game]:
		"""
		Returns a list of Games for the given discord user id.
		"""

		games = []
		if uid is None:
			return games
		try:
			players = MongoDB.players.find({'user_id': uid})
			for player in players:
				game = RpgUtilities.bot.games[player['guild_id']]
				games.append(game)

			return games

		except Exception as e:
			stdout(e)
			return []

	# Get the game associated with a context, if it exists.
	@staticmethod
	async def get_game(ctx, game_idx: int = None) -> Union[Game, None]:
		"""
		Returns a Game associated with a context, or by index, if it exists. Otherwise returns None.
		"""

		game: Union[Game, None] = None
		games: List[Game] = []
		if ctx.guild is None:
			games = RpgUtilities.get_games_for_user(ctx.author.id)
		else:
			game = RpgUtilities.bot.games[ctx.guild.id]

		if len(games) == 0 and game is None:
			Dispatcher.add(ctx, f"You are not a member of any games at this time.")

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
				return games[game_idx]
			elif len(games) == 1:
				return games[0]
			else:
				Dispatcher.add(ctx, f'The game is a lie! (No seriously... there seems to be no game available.)')

		return game

	@staticmethod
	async def get_player(ctx, game: Game = None, notify: bool = True) -> Union[Player, None]:
		"""
		Returns a Player associated with a context, or None if the Player does not exist.
		"""

		if game is None or not isinstance(game, Game):
			if (game := await RpgUtilities.get_game(ctx)) is None:
				return None

		if player := await game.player_manager.get_player(ctx):
			return player

		if notify:
			Dispatcher.add(
				game.channel,
				f'Why, {ctx.author.display_name if ctx.author else ctx.display_name}! You are not even playing the '
				f'game! Try `{ctx.prefix}game join`'
			)
		return None

	# Returns a tuple containing (game, player) if both exist.
	@staticmethod
	async def get_game_and_player(ctx, game_idx: int = None, notify: bool = True) -> (Game, Player):
		"""
		Returns a tuple containing a Game and Player if they exist, or None for one or both upon failure.
		"""

		game: Game = await RpgUtilities.get_game(ctx, game_idx)
		if game is None:
			return None, None

		player: Player = await RpgUtilities.get_player(ctx, game, notify)
		return game, player

	@staticmethod
	@tasks.loop(minutes=1)
	async def save_game_data():
		"""Database loop to save player and game data."""

		try:

			games = [
				UpdateOne(
					{'guild_id': g.guild.id},
					{'$set': g.to_dict()}
				) for g in RpgUtilities.bot.games.values()
			]

			MongoDB["games"].bulk_write(games, ordered=False)

			dirty = [
				(p, UpdateOne(
					{"guild_id": p.guild_id, "user_id": p.user_id},
					{"$set": p.to_dict()},
					upsert=True
				)) for g in RpgUtilities.bot.games.values() for p in g.player_manager.players.values() if p.is_dirty
			]

			if len(dirty) > 0:
				result = MongoDB["players"].bulk_write([d[1] for d in dirty], ordered=False)

				for idx, _id in result.upserted_ids.items():
					dirty[idx][0].id = _id

				for p, _ in dirty:
					p.is_dirty = False

		except ServerSelectionTimeoutError as e:
			stdout(f"Unable to connect to DB: {e}")

		except Exception as e:
			stdout(e)

	@staticmethod
	async def init(bot: Bot):
		try:
			RpgUtilities.bot = bot
			games = MongoDB.games.find()
			for g in games:
				await RpgUtilities.add_game(game=g)
			RpgUtilities.save_game_data.start()
			RpgUtilities.is_initialized = True

		except Exception as e:
			stdout(f"Error initializing RpgUtilities: {e}")
			RpgUtilities.is_initialized = False
