import smtplib
import sys
import textwrap

from datetime import datetime
from email.message import EmailMessage
from typing import List, Tuple, Union

from discord import Forbidden, HTTPException, Member, User, File
from discord.ext import tasks

from Caldanai.lib.bot import Bot
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.db import DB
from Caldanai.lib.rpg import Game, Area, Roles


def generate_report(
		author_id,
		author_display_name,
		message: str,
		player_name=None,
		guild_id=None,
		channel_id=None,
	):
	auth_rec = DB.get_auth()
	if not auth_rec:
		stdout('Reporting error: unable to retrieve authentication information from database.')
		return False

	msg = EmailMessage()
	msg['Subject'] = "Problem report from Caldanai Bot."
	msg['From'] = auth_rec['DEV_EMAIL']
	msg['To'] = auth_rec['DEV_EMAIL']
	msg.set_content(
		textwrap.dedent(
			f"""\
			Timestamp: {datetime.now().isoformat()}
			Author: {author_id} ({author_display_name} / {player_name})
			Guild ID: {guild_id}
			Channel ID: {channel_id}
			Details:
			{message}
			"""
		)
	)

	# Send full email
	with smtplib.SMTP('smtp.gmail.com', 587) as s:
		s.starttls()
		s.login(auth_rec['SMTP_USER'], auth_rec['SMTP_PASSWORD'])
		s.send_message(msg)

		# Send text alert
		msg.set_content("A new alert has been received. Please check your email.")
		del msg['To']
		msg['To'] = auth_rec['SMS_EMAIL']
		s.send_message(msg)
		s.quit()
		return True


class RpgUtilities:
	bot: Bot = None
	is_initialized: bool = False
	new_players = set()

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
						name=f"{role.value}",
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
				prefix = DB.get_server_by_guild_id(gid)['prefix']
			except Exception as e:
				stdout(f'Error in utils.py --> add_game(): {e}')
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
		Dispatcher.add(game.channel, "Caldanai Bot has just started!")

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
			players = DB.find_players_by_user_id(uid)
			for player in players:
				game = RpgUtilities.bot.games[player['guild_id']]
				games.append(game)

			return games

		except Exception as e:
			stdout(f'Error in utils.py --> get_games_for_user(): {e}')
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
			if isinstance(ctx, (Member, User)) and ctx.bot:
				file = File(f"./site/static/images/hal9000.gif", filename='hal9000.gif')
				Dispatcher.add(game.channel, file=file)
				return None

			Dispatcher.add(
				game.channel,
				f'Why, {ctx.author.display_name if ctx.author else ctx.display_name}! You are not even playing the '
				f'game! Try `{ctx.prefix}game join`'
			)
		return None

	# Returns a tuple containing (game, player) if both exist.
	@staticmethod
	async def get_game_and_player(ctx, game_idx: int = None, notify: bool = True) -> Tuple[Game, Player]:
		"""
		Returns a tuple containing a Game and Player if they exist, or None for one or both upon failure.
		"""

		game: Game = await RpgUtilities.get_game(ctx, game_idx)
		if game is None:
			return None, None

		player: Player = await RpgUtilities.get_player(ctx, game, notify)
		return game, player

	@staticmethod
	async def init(bot: Bot):
		try:
			RpgUtilities.bot = bot
			games = DB.find_all_games()
			for g in games:
				await RpgUtilities.add_game(game=g)
			RpgUtilities.save_game_data.start()
			RpgUtilities.is_initialized = True

		except Exception as e:
			stdout(f"Error initializing RpgUtilities: {e}")
			RpgUtilities.is_initialized = False

	# Removes a game from the bot's list of games
	@staticmethod
	async def remove_game(guild_id: int):
		if guild_id in RpgUtilities.bot.games.keys():
			try:
				DB.delete_game(guild_id)
				await RpgUtilities.delete_roles(RpgUtilities.bot.games[guild_id])
				del RpgUtilities.bot.games[guild_id]

			except Exception as e:
				stdout(f'Error in utils.py --> remove_game(): {e}')

	@tasks.loop(minutes=1)
	async def save_game_data(self):
		"""Database loop to save player and game data."""
		try:
			for g in RpgUtilities.bot.games.values():
				DB.update_game(g.guild.id, g.to_dict())
				for p in g.player_manager.players.values():
					if p.is_dirty:
						DB.update_player(g.guild.id, p.user_id, p.to_dict())
						p.is_dirty = False
			
			for player in RpgUtilities.new_players.copy():
				if player.id is None:
					p = DB.get_player(player.guild_id, player.user_id)
					if p:
						player.id = p.id
						RpgUtilities.new_players.remove(player)

			RpgUtilities.update_statics()
		except Exception as e:
			stdout("Error in save_game_data: " + e)

	@staticmethod
	def update_statics():
		command_totals = {}
		server_totals = {}
		try:
			cmd_copy = RpgUtilities.bot.command_usage.copy()
			RpgUtilities.bot.command_usage.clear()
			mon_copy = {g: g.monster_statics.copy() for g in RpgUtilities.bot.games.values()}
			for g in RpgUtilities.bot.games.values():
				g.monster_statics.clear()

			for entry in cmd_copy:
				DB.update_user_statics(entry)
				gid = entry['guild_id']
				cmd = f'commands.{entry["command"]}.{entry["alias"]}'
				guild_totals = command_totals.setdefault(gid, {})
				guild_totals[cmd] = guild_totals.get(cmd, 0) + 1
				server_totals[gid] = guild_totals[cmd] + server_totals.get(gid, 0)
			
			for guild_id, commands in command_totals.items():
				DB.update_statistic(guild_id, {**commands, 'total': server_totals.get(guild_id, 0)})

			for g, statics in mon_copy.items():
				for key, count in statics.items():
					DB.update_statistic(g.guild.id, {f'monsters.{key}': count})

		except Exception:
			e = sys.exception()
			stdout(f'Error in utils.py --> update_games() for guild_id {e}')