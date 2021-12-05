from typing import Dict

from discord.ext.commands import Bot as BotBase
from discord.ext.commands import CommandNotFound, BadArgument, CommandOnCooldown, MissingRequiredArgument, \
	when_mentioned_or, MissingPermissions, NoPrivateMessage
from discord import Intents, Guild
from discord.errors import HTTPException, Forbidden
from glob import glob
from os import path

from Caldanai.lib.rpg import Game
from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.db import MongoDB
from Caldanai.environment import OWNER_IDS, TOKEN


def get_prefix(_bot, message):
	prefix = None
	if message.guild is None:
		prefix = "$"

	elif MongoDB.servers.find_one({'guild_id': message.guild.id}) is None:
		MongoDB.servers.insert_one({'guild_id': message.guild.id, 'prefix': '$'})

	if prefix is None and message.guild is not None:
		prefix = MongoDB.servers.find_one({'guild_id': message.guild.id})['prefix']

	return when_mentioned_or(prefix)(_bot, message)


class Bot(BotBase):
	def __init__(self):
		self.TOKEN = None
		self.COGS = None
		self.IMAGES = None
		self.ready = False
		self.online = False
		self.stdout = None
		self.retry = 0
		self.games: Dict[int, Game] = {}
		intents = Intents.default()
		intents.members = True
		super().__init__(
			command_prefix=get_prefix,
			owner_ids=OWNER_IDS,
			intents=intents,
			case_insensitive=True
		)

	def setup(self):
		stdout("Loading cogs...")
		self.discover_cogs()
		for cog in self.COGS:
			self.load_extension(f'Caldanai.lib.cogs.{cog}')
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

	def run(self):
		self.TOKEN = TOKEN
		self.setup()
		self.retry = 0
		try:
			stdout(f"Running bot...")
			super().run(self.TOKEN, bot=True, reconnect=True)
		except HTTPException as e:
			stdout(e)
			if 'Retry-After' in e.response.headers.keys():
				stdout(f"Retry After {e.response.headers['Retry-After']} seconds")

	async def on_error(self, err, *args, **kwargs):
		if err == 'on_command_error':
			Dispatcher.add(args[0], '*BZZZT* ERROR! DOES NOT COMPUTE!')
		if owner := self.get_user(self.owner_ids[0]):
			Dispatcher.add(owner, repr(args[1]))
		raise

	async def on_command_completion(self, ctx):
		if guild := ctx.guild:
			if game := self.games[guild.id]:
				if ctx.author.id in game.players.keys() and (player := game.players[ctx.author.id]):
					await game.set_player_active(player)

	async def on_command_error(self, ctx, exc):
		if isinstance(
				exc,
				(BadArgument, CommandOnCooldown, MissingRequiredArgument)
		):
			pass

		elif isinstance(exc, CommandNotFound):
			pass

		elif isinstance(exc, (Forbidden, MissingPermissions, NoPrivateMessage)):
			Dispatcher.add(ctx, f"I'm afraid I can't do that, {ctx.author.mention}.")

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
		MongoDB.servers.insert_one({'guild_id': guild.id, 'name': guild.name, 'prefix': '$'})
		stdout(f"Guild joined: {guild.name} ({guild.id})")

	async def on_guild_remove(self, guild: Guild):
		MongoDB.servers.delete_one({'guild_id': guild.id})
		MongoDB.games.delete_many({'guild_id': guild.id})
		MongoDB.players.delete_many({'guild_id': guild.id})
		stdout(f"Guild left: {guild.name} ({guild.id})")

	async def on_ready(self):
		if not self.ready:
			stdout(f'Logged in as {bot.user.name}, {bot.user.id}')
			self.ready = True
		else:
			stdout('Bot reconnected')
		self.online = True


bot = Bot()
