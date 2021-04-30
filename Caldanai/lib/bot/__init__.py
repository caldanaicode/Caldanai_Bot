from typing import Dict

from discord.ext.commands import Bot as BotBase
from discord.ext.commands import CommandNotFound, BadArgument, CommandOnCooldown, MissingRequiredArgument, \
    when_mentioned_or, MissingPermissions, NoPrivateMessage
from discord import Intents, Guild
from discord.errors import HTTPException, Forbidden
from glob import glob
from os import getenv, path

from ..rpg.game import Game
from ...db.db import MongoDB
from dotenv import load_dotenv

load_dotenv()
OWNER_IDS = [getenv('OWNERID')]


def get_prefix(bot, message):
    prefix = None
    if message.guild is None:
        prefix = "$"

    elif MongoDB.servers.find_one({'guildId': message.guild.id}) is None:
        MongoDB.servers.insert_one({'guildId': message.guild.id, 'prefix': '$'})

    if prefix is None and message.guild is not None:
        prefix = MongoDB.servers.find_one({'guildId': message.guild.id})['prefix']

    return when_mentioned_or(prefix)(bot, message)


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
        self.discover_cogs()
        for cog in self.COGS:
            self.load_extension(f'Caldanai.lib.cogs.{cog}')

    def discover_cogs(self):
        self.COGS = [filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/cogs/*.py")]

    def load_cog(self, cog: str):
        self.discover_cogs()
        if cog in self.COGS:
            self.load_extension(f'Caldanai.lib.cogs.{cog}')
        else:
            print(f'{cog} Cog not found.')

    def reload_cog(self, cog: str):
        if cog in self.COGS:
            self.reload_extension(f'Caldanai.lib.cogs.{cog}')

    def reload_all_cogs(self):
        for cog in self.COGS:
            self.reload_cog(cog)

    def run(self):
        self.TOKEN = getenv('TOKEN')
        self.setup()
        self.retry = 0
        try:
            print('Running bot...')
            super().run(self.TOKEN, bot=True, reconnect=True)
        except HTTPException as e:
            print(e)
            if 'Retry-After' in e.response.headers.keys():
                print(f"Retry After {e.response.headers['Retry-After']} seconds")

    async def on_error(self, err, *args, **kwargs):
        if err == 'on_command_error':
            await args[0].send('*BZZZT* ERROR! DOES NOT COMPUTE!')
        raise

    async def on_command_error(self, ctx, exc):
        if isinstance(exc,
                      (BadArgument, CommandOnCooldown, MissingRequiredArgument)
                      ):
            pass

        elif isinstance(exc, CommandNotFound):
            pass

        elif isinstance(exc, (Forbidden, MissingPermissions, NoPrivateMessage)):
            await ctx.send(f"I'm afraid I can't do that, {ctx.author.mention}.")

        elif hasattr(exc, 'original'):
            raise exc.original

        elif isinstance(exc, HTTPException):
            print(exc)
            if 'Retry-After' in exc.response.headers.keys():
                print(f"Retry After {exc.response.headers['Retry-After']} seconds")

        else:
            raise exc

    async def on_connect(self):
        print("Bot connected.")
        self.online = True

    async def on_disconnect(self):
        print("Bot disconnected.")
        self.online = False

    async def on_resumed(self):
        print("Bot resumed.")
        self.online = True

    async def on_guild_join(self, guild: Guild):
        MongoDB.servers.insert_one({'guildId': guild.id, 'name': guild.name, 'prefix': '$'})
        print(f"Guild joined: {guild.name} ({guild.id})")

    async def on_guild_remove(self, guild: Guild):
        MongoDB.servers.delete_one({'guildId': guild.id})
        MongoDB.games.delete_many({'guildId': guild.id})
        MongoDB.players.delete_many({'guildId': guild.id})
        print(f"Guild left: {guild.name} ({guild.id})")

    async def on_ready(self):
        if not self.ready:
            print(f'Logged in as {bot.user.name}, {bot.user.id}')
            self.ready = True
        else:
            print('Bot reconnected')
        self.online = True


bot = Bot()
