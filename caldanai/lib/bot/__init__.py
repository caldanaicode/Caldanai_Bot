import asyncio
import sys
from datetime import datetime
from types import MappingProxyType
from typing import Any, Dict, Mapping

from discord.ext.commands import Bot as BotBase
from discord.ext.commands import (
    CommandNotFound,
    BadArgument,
    CheckFailure,
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


# ---------------------------------------------------------------------------
# Per-guild prefix cache
# ---------------------------------------------------------------------------
#
# discord.py calls the prefix resolver on *every message the bot sees* to
# decide whether a given line of chat begins a command. Without caching,
# that's one DB round-trip per message — multiplied across every guild,
# every channel, every non-command chatter line. The prefix changes almost
# never, so an in-memory dict gets us essentially all the DB hits back.
#
# Invalidation touches three spots:
#   - ``$prefix`` admin command updates the cache after writing the DB.
#   - ``on_guild_remove`` evicts when the bot leaves a guild.
#   - ``get_prefix`` itself populates on miss (lazy warm-up).
#
# The cache stores only the prefix string keyed by guild_id, so there's
# no stale-document risk — only the prefix needs to stay in sync.

_DEFAULT_PREFIX = "$"
_prefix_cache: Dict[int, str] = {}


def cache_prefix(guild_id: int, prefix: str) -> None:
    """Record / overwrite the cached prefix for a guild. Call after any
    successful DB write that changes the prefix."""
    _prefix_cache[guild_id] = prefix


def evict_prefix(guild_id: int) -> None:
    """Drop the cached prefix entry for a guild (no-op if absent). Call
    on guild removal so a future rejoin re-reads from DB."""
    _prefix_cache.pop(guild_id, None)


def clear_prefix_cache() -> None:
    """Wipe every entry. Intended for tests; production code shouldn't
    need this outside of reconfiguration scenarios."""
    _prefix_cache.clear()


def get_prefix(_bot, message):
    """Discord.py prefix resolver. Cached per-guild; falls back to DB
    on miss, populating the cache. See the cache docstring above for
    invalidation points."""
    if not message.guild:
        return when_mentioned_or(_DEFAULT_PREFIX)(_bot, message)

    gid = message.guild.id
    prefix = _prefix_cache.get(gid)
    if prefix is None:
        try:
            server = DB.get_server_by_guild_id(gid)
            if server:
                prefix = server["prefix"]
            else:
                # First-seen guild without a DB row — insert a default
                # so the next prefix change has a document to update.
                DB.insert_server(gid, message.guild.name)
                prefix = _DEFAULT_PREFIX
        except Exception as e:
            _log.error(e)
            prefix = _DEFAULT_PREFIX

        _prefix_cache[gid] = prefix

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
        # ``games`` is exposed as a property below — a read-only live
        # view over ``Game._channel_routes`` (the single source of
        # truth for channel-id → Game routing). The field is no longer
        # stored here; see the ``games`` property.
        self.command_usage = []
        self.last_command: Dict[str, Any] = {}
        _log.info("Bot init complete.")

    @property
    def games(self) -> "Mapping[int, Game]":
        """Read-only live view of channel_id → Game routing.

        Historically this was a dict owned by the Bot and mutated
        independently of ``Game._channel_routes``, forcing every
        add/remove to touch two registries (and leaking one when a
        caller forgot the other — the 2026-04-15 guild-id/channel-id
        rekey bug was exactly that class of drift). The class-level
        ``Game._channel_routes`` is now the single source of truth;
        this property returns a live ``MappingProxyType`` view so
        existing callers — ``bot.games.get(id)``, ``bot.games.values()``,
        ``id in bot.games``, iteration — keep working unchanged.
        Writes go through ``Game.register_channel`` /
        ``Game.unregister_channel``.
        """
        return MappingProxyType(Game._channel_routes)

    async def setup(self):
        _log.info("Loading cogs...")
        self.discover_cogs()
        await asyncio.gather(*[self.load_extension(f"caldanai.lib.cogs.{cog}") for cog in self.COGS])
        _log.info("Cogs loaded. Bot is setup.")

    def discover_cogs(self):
        self.COGS = [filepath.split(path.sep)[-1][:-3] for filepath in glob("./caldanai/lib/cogs/*.py")]

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
        channel = ctx.channel.id if ctx.channel else None
        entry = {"guild_id": guild, "channel_id": channel, "user_id": player, "command": cmd, "alias": alias, "timestamp": dt}
        self.command_usage.append(entry)
        self.last_command = entry

    async def on_command_completion(self, ctx: Context):
        if ctx.guild and ctx.channel:
            # bot.games is channel-keyed post-rekey (2026-04-15);
            # this hook was still using guild.id, so set_player_active
            # never fired and players stayed ``is_dirty=False`` after
            # commands — breaking last_active tracking and save-on-
            # activity semantics.
            if game := self.games.get(ctx.channel.id):
                if player := game.get_player_by_user_id(ctx.author.id):
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

        elif isinstance(exc, (Forbidden, MissingPermissions, NoPrivateMessage, CheckFailure)):
            # CheckFailure is the parent of MissingPermissions,
            # NoPrivateMessage, CheckAnyFailure, NotOwner, etc. —
            # any failed permission / context check gets the
            # "you can't do that" flavor response rather than a
            # generic error.
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
            # ``delete_server`` already DeleteMany's every game and
            # every player for this guild; the explicit delete_game
            # / delete_all_players calls that used to be here were
            # redundant (and delete_game's signature is now per-
            # channel, so it couldn't express the bulk-cleanup
            # intent anyway).
            DB.delete_server(guild.id)
            evict_prefix(guild.id)
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
