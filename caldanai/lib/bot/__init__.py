import asyncio
import sys
from datetime import datetime
from typing import Any, Dict

from discord.ext.commands import Bot as BotBase
from discord.ext.commands import (
    CommandNotFound,
    BadArgument,
    CommandOnCooldown,
    MissingRequiredArgument,
    when_mentioned_or,
    MissingPermissions,
    NoPrivateMessage,
    Context,
)
from discord import Intents, Guild, Member
from discord.errors import HTTPException, Forbidden
from glob import glob
from os import path
from random import choice

from caldanai import Subject
from caldanai.lib.bot.events import *
from caldanai.lib.rpg import Game
from caldanai.dispatcher import Dispatcher, send
from caldanai.logger import get_logger
from caldanai.db import DB


_log = get_logger(__name__)


def get_prefix(_bot, message):
    prefix = "$"
    try:
        if message.guild:
            if server := DB.get_server_by_guild_id(message.guild.id):
                prefix = server["prefix"]
            else:
                DB.insert_server(message.guild.id, message.guild.name)

    except Exception as e:
        _log.error(e)

    return when_mentioned_or(prefix)(_bot, message)


class Bot(BotBase, Subject):
    """Combines the functionality of the Discord Bot class and the Subject class, and provides additional features."""

    def __init__(self):
        _log.info(f"Bot initializing...")
        auth = DB.get_auth()
        intents = Intents.all()
        intents.presences = False
        super().__init__(
            command_prefix=get_prefix,
            owner_ids=auth["OWNER_IDS"] if auth else None,
            intents=intents,
            case_insensitive=True,
        )
        Subject.__init__(self)
        self.TOKEN = auth["TOKEN"] if auth else None
        self.COGS = None
        self.IMAGES = None
        self.ready = False
        self.is_online_discord = False
        self.stdout = None
        self.retry = 0
        self.games: Dict[int, Game] = {}
        self.command_usage = []
        self.last_command: Dict[str, Any] = {}
        _log.info("Bot init complete.")

    async def setup(self):
        _log.info("Loading cogs...")
        self.discover_cogs()
        await asyncio.gather(*[self.load_extension(f"caldanai.lib.cogs.{cog}") for cog in self.COGS])
        _log.info("Cogs loaded. Bot is setup.")

    def discover_cogs(self):
        self.COGS = [filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/cogs/*.py")]

    async def load_cog(self, cog: str):
        self.discover_cogs()
        if cog in self.COGS:
            await self.load_extension(f"caldanai.lib.cogs.{cog}")
        else:
            _log.error(f"{cog} Cog not found.")

    async def reload_cog(self, cog: str):
        if cog in self.COGS:
            await self.reload_extension(f"caldanai.lib.cogs.{cog}")

    async def reload_all_cogs(self):
        await asyncio.gather(*[self.reload_extension(f"caldanai.lib.cogs.{cog}") for cog in self.COGS])

    async def on_command(self, ctx: Context):
        # Track by user id and guild id
        guild = ctx.guild.id if ctx.guild else "dm"
        player = ctx.author.id if ctx.author else "unknown"
        cmd = ctx.command.qualified_name.lower()
        alias = ctx.invoked_with.lower()
        dt = datetime.now().isoformat()
        entry = {"guild_id": guild, "user_id": player, "command": cmd, "alias": alias, "timestamp": dt}
        self.command_usage.append(entry)
        self.last_command = entry

    async def on_command_completion(self, ctx: Context):
        if guild := ctx.guild:
            if game := self.games.get(guild.id):
                if ctx.author.id in game.player_manager.players.keys() and (
                    player := game.player_manager.players[ctx.author.id]
                ):
                    await game.player_manager.set_player_active(player)

    async def on_error(self, err, *args, **kwargs):
        if err == "on_command_error" and args:
            Dispatcher.add(args[0], "*BZZZT* ERROR! DOES NOT COMPUTE!")
        exc = args[1] if len(args) > 1 else sys.exc_info()[1]
        for oid in self.owner_ids:
            if owner := self.get_user(oid):
                Dispatcher.add(owner, repr(exc))
        if exc is not None:
            raise exc

    @staticmethod
    async def get_forbidden_response(ctx: Context) -> str:
        return choice(
            [
                f"I'm afraid I can't do that, <@!{ctx.author.id}>.",
                f"Perhaps, one day, you shall hold that kind of power over me, <@!{ctx.author.id}>. But today is not "
                f"that day.",
                f"You're not the boss of me, <@!{ctx.author.id}>! Just who do you think you are?!",
                f"Unable to comply, <@!{ctx.author.id}>, please elevate status and try again.",
                "```\nOne of these days\nI'm gonna love me.\nOne of these days\nI'll rise above me.\nOne of these days...```",
                "We're sorry. The number you have dialed is no longer in service. Please hang up, and try your call again.",
            ]
        )

    async def on_command_error(self, ctx: Context, exc):
        if isinstance(exc, (BadArgument, CommandOnCooldown, MissingRequiredArgument)):
            pass

        elif isinstance(exc, CommandNotFound):
            pass

        elif isinstance(exc, (Forbidden, MissingPermissions, NoPrivateMessage)):
            Dispatcher.add(ctx, await Bot.get_forbidden_response(ctx))

        elif hasattr(exc, "original"):
            raise exc.original

        elif isinstance(exc, HTTPException):
            _log.error("HTTPException occurred.", exc_info=True)
            if "Retry-After" in exc.response.headers.keys():
                _log.info(f"Retry After {exc.response.headers['Retry-After']} seconds")

        else:
            raise exc

    async def on_connect(self):
        _log.info("Connected to discord")
        await self.notify(DiscordConnectedEvent())

    async def on_disconnect(self):
        _log.warning("Disconnected from discord")
        self.is_online_discord = False
        await self.notify(DiscordDisconnectedEvent())

    async def on_resumed(self):
        _log.info("Resumed discord session")
        await self.notify(DiscordConnectedEvent())

    async def on_guild_join(self, guild: Guild):
        try:
            DB.insert_server(guild.id, guild.name)
            _log.info(f"Guild joined: {guild.name} ({guild.id})")
        except Exception as e:
            _log.error(f"Unable to add guild {guild.id} due to database error.", exc_info=True)

    async def on_guild_remove(self, guild: Guild):
        try:
            DB.delete_server(guild.id)
            DB.delete_game(guild.id)
            DB.delete_all_players(guild.id)
            _log.info(f"Guild left: {guild.name} ({guild.id})")
        except Exception as e:
            _log.error(f"Unable to remove guild {guild.id} due to database error.", exc_info=True)

    async def on_ready(self):
        if not self.ready:
            _log.info(f"Logged in as {self.user.name}, {self.user.id}")
            self.ready = True
            await self.notify(BotReadyEvent())
            send.start()
        else:
            _log.info("Bot reconnected")
        self.is_online_discord = True

    async def on_member_update(self, before: Member, after: Member):
        await self.notify(MemberUpdatedEvent(before, after))
