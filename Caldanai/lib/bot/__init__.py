from datetime import datetime
from typing import Dict

from discord.ext.commands import Bot as BotBase
from discord.ext.commands import CommandNotFound, BadArgument, CommandOnCooldown, MissingRequiredArgument, \
	when_mentioned_or, MissingPermissions, NoPrivateMessage, Context
from discord import Intents, Guild
from discord.errors import HTTPException, Forbidden
from glob import glob
from os import path
from random import choice

from Caldanai.lib.rpg import Game
from Caldanai.Dispatcher import Dispatcher, send
from Caldanai.Logger import stdout
from Caldanai.db import DB


def get_prefix(_bot, message):
	prefix = None
	try:
		if message.guild is None:
			prefix = "$"

		elif DB.get_server_by_guild_id(message.guild.id) is None:
			DB.insert_server(message.guild.id, prefix=prefix)

		if prefix is None and message.guild is not None:
			prefix = DB.get_server_by_guild_id(message.guild.id)['prefix']

	except Exception as e:
		stdout(e)

	return when_mentioned_or(prefix)(_bot, message)


class Bot(BotBase):
	def __init__(self):
		auth = DB.get_auth() or {}
		self.TOKEN = auth.get('TOKEN')
		self.COGS = None
		self.IMAGES = None
		self.ready = False
		self.online = False
		self.stdout = None
		self.retry = 0
		self.games: Dict[int, Game] = {}
		self.command_usage = []
		intents = Intents.default()
		intents.members = True
		intents.message_content = True
		super().__init__(
			command_prefix=get_prefix,
			owner_ids=auth.get('OWNER_IDS'),
			intents=intents,
			case_insensitive=True
		)

	async def setup(self):
		stdout("Loading cogs...")
		self.discover_cogs()
		for cog in self.COGS:
			await self.load_extension(f'Caldanai.lib.cogs.{cog}')
		stdout("Cogs loaded. Bot is setup.")

	def discover_cogs(self):
		self.COGS = [filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/cogs/*.py")]

	def load_cog(self, cog: str):
		self.discover_cogs()
		if cog in self.COGS:
			self.load_extension(f'Caldanai.lib.cogs.{cog}')
		else:
			stdout(f'{cog} Cog not found.')

	def reload_cog(self, cog: str):
		if cog in self.COGS:
			self.reload_extension(f'Caldanai.lib.cogs.{cog}')

	def reload_all_cogs(self):
		for cog in self.COGS:
			self.reload_cog(cog)

	async def on_command(self, ctx: Context):
		# Track by user id and guild id
		guild = ctx.guild.id if ctx.guild else "dm"
		player = ctx.author.id if ctx.author else "unknown"
		cmd = ctx.command.qualified_name.lower()
		alias = ctx.invoked_with.lower()
		dt = datetime.now().isoformat()
		self.command_usage.append(
			{
				'guild_id': guild,
				'user_id': player,
				'command': cmd,
				'alias': alias,
				'timestamp': dt
			}
		)

	async def on_command_completion(self, ctx: Context):
		if guild := ctx.guild:
			if game := self.games[guild.id]:
				if ctx.author.id in game.player_manager.players.keys() \
						and (player := game.player_manager.players[ctx.author.id]):
					await game.player_manager.set_player_active(player)

	async def on_error(self, err, *args, **kwargs):
		if err == 'on_command_error':
			Dispatcher.add(args[0], '*BZZZT* ERROR! DOES NOT COMPUTE!')
		for oid in self.owner_ids:
			owner = self.get_user(oid)
			Dispatcher.add(owner, repr(args[1]))
		raise

	@staticmethod
	async def get_forbidden_response(ctx: Context) -> str:
		return choice([
			f"I'm afraid I can't do that, <@!{ctx.author.id}>.",
			f"Perhaps, one day, you shall hold that kind of power over me, <@!{ctx.author.id}>. But today is not "
			f"that day.",
			f"You're not the boss of me, <@!{ctx.author.id}>! Just who do you think you are?!",
			f"Unable to comply, <@!{ctx.author.id}>, please elevate status and try again.",
			"```\nOne of these days\nI'm gonna love me.\nOne of these days\nI'll rise above me.\nOne of these days...```",
			"We're sorry. The number you have dialed is no longer in service. Please hang up, and try your call again."
		])

	async def on_command_error(self, ctx: Context, exc):
		if isinstance(
				exc,
				(BadArgument, CommandOnCooldown, MissingRequiredArgument)
		):
			pass

		elif isinstance(exc, CommandNotFound):
			pass

		elif isinstance(exc, (Forbidden, MissingPermissions, NoPrivateMessage)):
			Dispatcher.add(ctx, await Bot.get_forbidden_response(ctx))

		elif hasattr(exc, 'original'):
			raise exc.original

		elif isinstance(exc, HTTPException):
			stdout(exc)
			if 'Retry-After' in exc.response.headers.keys():
				stdout(f"Retry After {exc.response.headers['Retry-After']} seconds")

		else:
			raise exc

	async def on_connect(self):
		stdout("Bot connected.")
		self.online = True

	async def on_disconnect(self):
		self.online = False

	async def on_resumed(self):
		self.online = True

	async def on_guild_join(self, guild: Guild):
		DB.insert_server(guild.id, guild.name)
		stdout(f"Guild joined: {guild.name} ({guild.id})")

	async def on_guild_remove(self, guild: Guild):
		DB.delete_server(guild.id)
		stdout(f"Guild left: {guild.name} ({guild.id})")
	
	async def on_ready(self):
		if not self.ready:
			stdout(f'Logged in as {self.user.name}, {self.user.id}')
			self.ready = True
			send.start()
		else:
			stdout('Bot reconnected')
		self.online = True
