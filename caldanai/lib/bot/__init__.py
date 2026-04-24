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
from caldanai.environment import PLAYER_BOT_ALLOWLIST
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
        # Per-user cooldown on command-error hint responses so a
        # fast typo session (``$equip foo``, ``$equip bar``, ...)
        # doesn't spam the channel with "I didn't catch that" hints.
        # Keyed by (user_id, exception-class-name); value is the
        # datetime of the last hint we sent. See ``on_command_error``.
        self._error_hint_cooldowns: Dict[tuple, datetime] = {}
        _log.info("Bot init complete.")

    async def process_commands(self, message) -> None:
        """Override the default bot-filter so dedicated tester-bot
        accounts (listed in ``PLAYER_BOT_ALLOWLIST``) can drive the
        bot like real players — used by ``tools.bot_player`` to
        run scripted playtest sweeps against the bestiary.

        Still filters out self-authored messages (recursion guard)
        and any bot account NOT in the allowlist, so random bots
        present in the guild stay silent. A human-player command
        path is unchanged.
        """
        if message.author.id == self.user.id:
            return
        if message.author.bot and message.author.id not in PLAYER_BOT_ALLOWLIST:
            return
        ctx = await self.get_context(message)
        await self.invoke(ctx)

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
        # ``return_exceptions=True`` so a failing cog surfaces a
        # clean error instead of stalling the gather while discord.py's
        # other in-flight cog-loading tasks unwind. Previously a
        # ``CommandRegistrationError`` (e.g. alias collision) would
        # leave startup hanging until SIGINT — the exception had been
        # raised but the gather's cancellation cascade couldn't
        # complete, so the process appeared frozen.
        results = await asyncio.gather(
            *[
                self.load_extension(f"caldanai.lib.cogs.{cog}")
                for cog in self.COGS
            ],
            return_exceptions=True,
        )
        failures = [
            (cog, result)
            for cog, result in zip(self.COGS, results)
            if isinstance(result, BaseException)
        ]
        if failures:
            for cog, exc in failures:
                _log.error(f"Failed to load cog {cog!r}: {exc}")
            # Re-raise the first failure so startup fails fast and
            # loud — the log lines above name every failed cog, so
            # even when multiple fail the operator sees the full
            # picture before the traceback.
            _, first_exc = failures[0]
            raise first_exc
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

    async def invoke(self, ctx: Context):
        """Wrap every command invocation in a per-channel log
        context so any ``_log`` call fired by the command handler
        or anything it dispatches into carries the channel id.

        Overriding ``invoke`` (rather than hooking ``before_invoke``
        + ``after_invoke``) guarantees the ``with`` block's reset
        fires on exit, even if the command raises — we don't want a
        leaked channel id bleeding into whatever the next task on
        this worker pulls off the event loop.
        """
        from caldanai.log_context import channel_log_context
        channel_id = ctx.channel.id if ctx.channel else None
        with channel_log_context(channel_id):
            await super().invoke(ctx)

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

        # Audit-log every admin/owner command at INFO level so the
        # live trace captures who did what with elevated permissions
        # without tangling with the noisier player-level commands.
        # Detection heuristic: cog name contains "admin" — covers
        # ``BotAdminCommands`` + ``RpgAdminCommands`` + anything
        # future that follows the same naming. Simpler and more
        # robust than walking ``ctx.command.checks`` for
        # ``is_owner`` / ``has_permissions`` predicates.
        cog_name = ctx.cog.qualified_name if ctx.cog else ""
        if cog_name and "admin" in cog_name.lower():
            author = getattr(ctx.author, "name", None) or "unknown"
            _log.info(
                f"Admin command: {author} ({player}) ran "
                f"`{ctx.message.content}`"
            )

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

    def _maybe_hint(self, ctx: Context, exc, cmd: str) -> None:
        """Send a one-liner hint to the invoker, suppressing
        repeats within :attr:`_ERROR_HINT_COOLDOWN_SECONDS` so fast
        typo sessions don't spam the channel.

        Keyed by ``(user_id, exception-class-name)`` — a user
        triggering the same error class repeatedly gets one hint
        per window; a genuinely distinct error (``BadArgument``
        after ``MissingRequiredArgument``, say) gets its own hint.
        Unknown user (no ``ctx.author``) skips the cooldown table
        entirely and is allowed through each time, since we can't
        dedupe anyway.
        """
        user_id = getattr(ctx.author, "id", None)
        exc_key = type(exc).__name__
        now = datetime.now()
        if user_id is not None:
            cooldown_key = (user_id, exc_key)
            last = self._error_hint_cooldowns.get(cooldown_key)
            if last is not None:
                elapsed = (now - last).total_seconds()
                if elapsed < self._ERROR_HINT_COOLDOWN_SECONDS:
                    return
            self._error_hint_cooldowns[cooldown_key] = now
        hint = (
            f"I didn't quite catch that, <@!{user_id}>. "
            f"Try `{ctx.prefix}help {cmd}`."
            if user_id is not None
            else f"I didn't quite catch that. Try `{ctx.prefix}help {cmd}`."
        )
        Dispatcher.add(ctx, hint)

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

    # How long (seconds) a per-user hint is suppressed after one
    # lands, keyed by (user_id, exception class). Long enough that a
    # fast typo session doesn't spam; short enough that a later
    # genuine mistake still gets the hint.
    _ERROR_HINT_COOLDOWN_SECONDS = 10

    async def on_command_error(self, ctx: Context, exc):
        if isinstance(exc, (BadArgument, MissingRequiredArgument)):
            # These are user-input errors — historically silently
            # dropped, which meant a typo like
            # ``$equip wand.1 left wand.2 right`` (``wand.2`` fails
            # to parse as ``gid: int``) produced no feedback and no
            # log. Surface at DEBUG for the dev trail and, once per
            # user per error-class per cooldown, nudge the user at
            # ``$help <command>``.
            cmd = ctx.command.qualified_name if ctx.command else "?"
            _log.debug(
                f"{cmd}: {type(exc).__name__} from "
                f"user {getattr(ctx.author, 'id', '?')}: {exc}"
            )
            self._maybe_hint(ctx, exc, cmd)

        elif isinstance(exc, CommandOnCooldown):
            # Cooldowns stay silent — echoing to the channel on
            # every cooldown-blocked attempt would be noisier than
            # the silence the user was already annoyed by.
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
                # Rate-limit context for the error above — upgrade to
                # warning since it sits on an error path.
                _log.warning(
                    f"Retry After {exc.response.headers['Retry-After']} seconds"
                )

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
