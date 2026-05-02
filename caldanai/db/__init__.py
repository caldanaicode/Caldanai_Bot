import asyncio
import functools
import inspect
import os
import traceback

from collections import defaultdict
from datetime import datetime
from discord.ext import tasks
from pymongo import DESCENDING, DeleteMany, DeleteOne, InsertOne, MongoClient, UpdateOne
from pymongo.database import Database
from pymongo.errors import (
    AutoReconnect,
    BulkWriteError,
    ConnectionFailure,
    NetworkTimeout,
    ServerSelectionTimeoutError,
)

from caldanai.double_buffer import DoubleBuffer
from caldanai.environment import DB_CONNECTION, LIVE_DB_NAME, STAGE, TEST_DB_NAME
from caldanai.logger import MongoHandler, get_logger

_log = get_logger(__name__)

# Seconds without a successful DB write before an alert is sent.
_WRITE_ALERT_THRESHOLD = 300


class DB:
    """Wrapper for MongoDB operations."""

    _mongoClient: MongoClient = MongoClient(DB_CONNECTION)
    # Database selected by ``STAGE`` env. Names live in
    # ``caldanai.environment`` so they aren't hardcoded here —
    # forks point at their own DBs via ``LIVE_DB_NAME`` /
    # ``TEST_DB_NAME`` in ``.env`` without needing a code change.
    _mongoDB: Database = _mongoClient[TEST_DB_NAME if STAGE == "TEST" else LIVE_DB_NAME]
    _mongoHandler: MongoHandler = None
    _queues = defaultdict(DoubleBuffer)
    _auth = _mongoDB.auth
    _servers = _mongoDB.servers
    _games = _mongoDB.games
    _players = _mongoDB.players
    _statics = _mongoDB.statics
    _command_statics = _mongoDB.user_command_statics
    _logs = _mongoDB.logs_discord
    _is_connected = False
    _last_successful_write: datetime = None
    _write_alert_sent = False

    @staticmethod
    def on_connected() -> None:
        """Things to do when connection is (re-)established."""

        _log.info("Database connected")
        DB._is_connected = True
        DB._write_alert_sent = False
        if DB.poll_for_connection.is_running():
            DB.poll_for_connection.stop()
            _log.debug("poll_for_connection() stopped")

    @staticmethod
    def on_disconnected() -> None:
        """Things to do when connection fails."""

        _log.error("Database disconnected")
        DB._is_connected = False

        if not DB.poll_for_connection.is_running():
            DB.poll_for_connection.start()
            _log.debug("poll_for_connection() started")

    @staticmethod
    def handle_connection(func, invoke):
        """Common logic for connection handling."""

        module_path = os.path.relpath(__file__, start=os.getcwd()).replace(os.sep, ".")
        if module_path.endswith(".py"):
            module_path = module_path[:-3]
        method_path = f"{module_path}:{func.__name__}"
        _log.debug(f"Checking connection for {method_path}()")
        try:
            DB._mongoClient.admin.command("ping")
            if not DB._is_connected:
                DB.on_connected()
            return invoke()  # This is where sync/async behavior is determined
        except Exception:
            _log.error(f"Connection test failed for {method_path}.", exc_info=True)
            DB.on_disconnected()

    @staticmethod
    def check_connection(func):
        """Decorator to verify database connectivity."""

        if inspect.iscoroutinefunction(func):

            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                return await DB.handle_connection(func, lambda: func(*args, **kwargs))

            return async_wrapper

        else:

            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                return DB.handle_connection(func, lambda: func(*args, **kwargs))

            return sync_wrapper

    @check_connection
    @staticmethod
    def close_db_connection():
        """Closes the database connection.

        The periodic-write loop that used to live here as
        ``batch_write`` has been collapsed into ``save_game_data``
        (rpg/helpers/utils.py) so the shutdown order is now "stop
        save_game_data → flush_all → close mongo client" rather
        than separately stopping two loops.
        """
        DB._mongoClient.close()

    @staticmethod
    def flush_all() -> None:
        """Synchronously drain every queued write to Mongo — call
        during shutdown after stopping :func:`batch_write` so no
        pending DB operations are lost when the process exits.

        Mirrors the queue-draining portion of
        :func:`batch_write`'s body (sans the periodic ping and the
        watchdog-timestamp bump) so the two paths agree on which
        queues get drained and how errors are logged. Single-shot,
        not scheduled on the clock.

        Intentionally skips the connection-check decorator: on
        shutdown we want to attempt the write regardless of the
        cached ``_is_connected`` flag — if Mongo is genuinely down
        we'll log the error and exit with ops left in the queue,
        but that's no worse than the connectivity check short-
        circuiting us out.
        """
        collections = list(DB._queues.keys())
        for collection in collections:
            ops = DB._queues[collection].get_all()
            if not ops:
                continue
            _log.debug(
                f"flush_all: writing {len(ops)} queued update"
                f"{'s' if len(ops) != 1 else ''} to '{collection.full_name}'"
            )
            try:
                collection.bulk_write(ops, ordered=False)
            except BulkWriteError:
                error_info = traceback.format_exc()
                _log.error(
                    f"flush_all: bulk_write on '{collection.full_name}' "
                    f"failed: {error_info}"
                )

        # Mongo log handler mirrors the same drain/bulk_write shape
        # — keep it in lockstep with ``batch_write``.
        if DB._mongoHandler and (
            errors := [InsertOne(item) for item in DB._mongoHandler.queue.get_all()]
        ):
            try:
                DB._logs.bulk_write(errors)
            except BulkWriteError:
                error_info = traceback.format_exc()
                _log.error(
                    f"flush_all: log bulk_write failed: {error_info}"
                )

    @staticmethod
    async def drain_queues_once():
        """Drain every queued DB op to Mongo in one pass.

        Called from the ``save_game_data`` task loop right after
        ``save_all_now()`` populates the queues — so queued ops land
        in Mongo within the same 1-minute tick rather than waiting
        for a second, independent ``batch_write`` tick (which in
        the pre-collapse architecture produced a 0–2 minute
        write-visibility window, depending on phase offset between
        the two loops).

        Retry handling: each :class:`DoubleBuffer` exposes a
        ``retry`` sub-queue. Ops that failed on a previous cycle
        with a *transient* error (connection drops, server-selection
        timeouts) are pushed there and drained ahead of fresh ops
        on the next cycle, so a momentary Mongo blip doesn't lose
        writes. Data-validation failures inside a ``BulkWriteError``
        are logged and dropped — retrying a malformed op loops
        forever.
        """
        try:
            DB._mongoClient.admin.command("ping")
            if not DB._is_connected:
                DB.on_connected()
        except Exception:
            _log.error("DB ping failed during drain_queues_once.", exc_info=True)
            if DB._is_connected:
                DB.on_disconnected()
            return  # skip this cycle; queued ops stay put for next one

        attempts = 0
        successes = 0
        collections = list(DB._queues.keys())
        for collection in collections:
            buf = DB._queues[collection]
            # Retry sub-queue is drained ahead of the fresh batch so
            # previously-failed ops take priority (they've already
            # waited a cycle). Both lists get merged into a single
            # bulk_write so the DB round-trip count doesn't balloon.
            retry_ops = []
            while not buf.retry.empty():
                try:
                    retry_ops.append(buf.retry.get_nowait())
                except Exception:
                    break
            fresh_ops = buf.get_all()
            ops = retry_ops + fresh_ops
            if not ops:
                continue
            _log.debug(
                f"Writing {len(ops)} queued DB update"
                f"{'s' if len(ops) != 1 else ''} to "
                f"'{collection.full_name}'"
                f"{f' (incl. {len(retry_ops)} retried)' if retry_ops else ''}"
            )
            attempts += 1
            try:
                result = collection.bulk_write(ops, ordered=False)
                _log.debug(f"{result=}")
                successes += 1
            except BulkWriteError as e:
                # Partial failure: some ops succeeded, some didn't.
                # Data-shape errors (schema violation, duplicate key,
                # etc.) won't heal on retry, so we log + drop.
                error_info = traceback.format_exc()
                _log.error(
                    f"BulkWriteError on '{collection.full_name}': "
                    f"{error_info}"
                )
                # Still count as a partial success — at least one
                # op likely landed (MongoDB's ordered=False keeps
                # going past individual failures).
                if e.details.get("nInserted", 0) or e.details.get("nModified", 0):
                    successes += 1
            except (
                AutoReconnect, ConnectionFailure,
                NetworkTimeout, ServerSelectionTimeoutError,
            ) as e:
                # Transient connection problems: requeue the whole
                # batch so the next cycle tries again. ``buf.retry``
                # is the explicit "these need re-drive" holding pen.
                _log.error(
                    f"Transient write failure on "
                    f"'{collection.full_name}' ({type(e).__name__}): "
                    f"requeuing {len(ops)} op(s) for retry."
                )
                for op in ops:
                    buf.retry.put(op)
                if DB._is_connected:
                    DB.on_disconnected()

        if DB._mongoHandler and (errors := [InsertOne(item) for item in DB._mongoHandler.queue.get_all()]):
            attempts += 1
            try:
                DB._logs.bulk_write(errors)
                successes += 1
            except BulkWriteError:
                error_info = traceback.format_exc()
                _log.error(f"Log bulk_write failed: {error_info}")
            except (
                AutoReconnect, ConnectionFailure,
                NetworkTimeout, ServerSelectionTimeoutError,
            ) as e:
                # Log queue doesn't have a retry-sub-queue analogue
                # today; dropped log lines are less catastrophic than
                # dropped gameplay state. Note the loss and move on.
                _log.error(
                    f"Transient log-write failure "
                    f"({type(e).__name__}): {len(errors)} log "
                    "line(s) dropped."
                )

        # Only bump the watchdog timestamp if we either had nothing to write
        # (connection is healthy, confirmed by the earlier ping) or at least
        # one bulk_write actually succeeded. If we attempted writes and every
        # one raised, leave the timestamp alone so the watchdog can fire.
        if attempts == 0 or successes > 0:
            DB._last_successful_write = datetime.now()
            DB._write_alert_sent = False

    @tasks.loop(minutes=1)
    async def poll_for_connection():
        _log.debug("Polling for DB connection")
        try:
            DB._mongoClient.admin.command("ping")
            DB.on_connected()
        except Exception:
            _log.debug("Connection not available.")

    @check_connection
    @staticmethod
    def find_players_by_user_id(user_id):
        """Finds all players associated with the supplied user ID."""
        return DB._mongoDB.players.find({"user_id": user_id})

    @check_connection
    @staticmethod
    def get_player(guild_id, channel_id, user_id):
        """Returns the player identified by (guild_id, channel_id,
        user_id), or ``None``. Players are game-scoped: one character
        per (guild, channel) pair per user."""
        return DB._mongoDB.players.find_one(
            {"guild_id": guild_id, "channel_id": channel_id, "user_id": user_id}
        )

    @check_connection
    @staticmethod
    def find_all_games():
        """Find all games in the database."""
        return DB._mongoDB.games.find()

    @check_connection
    @staticmethod
    def get_auth():
        """Returns the authorization record."""
        return DB._mongoDB.auth.find_one()

    @check_connection
    @staticmethod
    def get_server_by_guild_id(id):
        """Returns the server associated with the given Guild ID."""
        return DB._mongoDB.servers.find_one({"guild_id": id})

    @staticmethod
    def delete_game(guild_id, channel_id):
        """Enqueues deletion of a single game document and all its
        associated players, identified by the (guild_id, channel_id)
        pair. Players are game-scoped so this only removes players
        belonging to this specific game, not players in other games
        on the same guild."""
        DB._queues[DB._games].put(
            DeleteOne({"guild_id": guild_id, "channel_id": channel_id})
        )
        DB._queues[DB._players].put(
            DeleteMany({"guild_id": guild_id, "channel_id": channel_id})
        )

    @staticmethod
    def update_game(guild_id, channel_id, guild_dict, upsert=False):
        """Enqueues an update for a single game document identified
        by the (guild_id, channel_id) pair."""
        DB._queues[DB._games].put(
            UpdateOne(
                {"guild_id": guild_id, "channel_id": channel_id},
                {"$set": guild_dict},
                upsert=upsert,
            )
        )

    @staticmethod
    def update_statistic(guild_id, inc_doc, channel_id=None):
        """Enqueues an update for the server statistics. When
        ``channel_id`` is provided the doc is game-scoped; otherwise
        guild-scoped for backward compat with legacy callers."""
        query = {"guild_id": guild_id}
        if channel_id is not None:
            query["channel_id"] = channel_id
        DB._queues[DB._statics].put(UpdateOne(query, {"$inc": inc_doc}, upsert=True))

    @staticmethod
    def update_user_statics(doc):
        """Enqueues an insertion for the given user statistics record."""
        DB._queues[DB._command_statics].put(InsertOne(doc))

    @staticmethod
    def update_player(guild_id, channel_id, user_id, player_dict):
        """Enqueues a player upsert. Players are game-scoped:
        identified by (guild_id, channel_id, user_id)."""
        DB._queues[DB._players].put(
            UpdateOne(
                {"guild_id": guild_id, "channel_id": channel_id, "user_id": user_id},
                {"$set": player_dict},
                upsert=True,
            )
        )

    @staticmethod
    def insert_server(guild_id, name=None, prefix="$"):
        """Enqueues a server upsert — idempotent. Multiple call
        paths can invoke this for the same guild (``on_guild_join``
        fires once; ``get_prefix`` fires on the first message the
        bot sees from a guild that isn't yet cached). Using UpdateOne
        with ``upsert=True`` and ``$setOnInsert`` means concurrent
        or repeated calls produce exactly one row per guild_id,
        never duplicates.

        ``$setOnInsert`` (not ``$set``) is deliberate: if the row
        already exists, we don't overwrite a user-configured prefix
        with the default. Only the initial insert writes values."""
        DB._queues[DB._servers].put(
            UpdateOne(
                {"guild_id": guild_id},
                {"$setOnInsert": {"guild_id": guild_id, "name": name, "prefix": prefix}},
                upsert=True,
            )
        )

    @staticmethod
    def delete_server(guild_id):
        """Enqueueus deletion of a server, and all associated games and players."""
        DB._queues[DB._servers].put(DeleteOne({"guild_id": guild_id}))
        DB._queues[DB._games].put(DeleteMany({"guild_id": guild_id}))
        DB._queues[DB._players].put(DeleteMany({"guild_id": guild_id}))

    @check_connection
    @staticmethod
    def find_players_by_guild_id(guild_id):
        """Retrieves all players associated with a guild ID.

        **Use sparingly.** For per-game player loading, use
        :meth:`find_players_by_game` instead — a guild can host
        multiple games (one per channel), and a guild-scoped query
        will pull every player across every game into one
        ``PlayerManager``, causing cross-game state bleed.
        """
        return DB._players.find({"guild_id": guild_id})

    @check_connection
    @staticmethod
    def find_players_by_game(guild_id, channel_id):
        """Retrieves all players associated with a specific game
        (guild_id + channel_id pair).

        Compound query — required for guilds hosting multiple
        concurrent games (e.g. test guild running a Vael-facing
        game alongside an OOC engineering channel). Without this
        scoping, ``PlayerManager.load_players`` for game B would
        pull game A's players into B's in-memory roster and
        report them as "already a player" on ``$join`` while
        showing skills from game A on ``$skills``.

        Legacy adoption for ``channel_id``-less docs (pre-
        compound era) was previously handled by a permissive
        guild-only query plus a stamping pass; that path is
        retired now that all extant docs (LIVE + TEST as of
        2026-05-02) are channel-scoped. If a future migration
        ever needs to backfill unscoped docs, do it as a one-
        shot ``tools/`` script rather than re-introducing the
        in-load adoption that caused the bleed bug.
        """
        return DB._players.find(
            {"guild_id": guild_id, "channel_id": channel_id}
        )

    @staticmethod
    def delete_player(guild_id, channel_id, user_id):
        """Deletes a player from the database. Game-scoped: compound
        (guild_id, channel_id, user_id) filter."""
        DB._queues[DB._players].put(
            DeleteOne({"guild_id": guild_id, "channel_id": channel_id, "user_id": user_id})
        )

    @staticmethod
    def delete_all_players(guild_id):
        """Deletes all players in the database associated with the given guild_id."""
        DB._queues[DB._players].put(DeleteMany({"guild_id": guild_id}))

    @staticmethod
    def update_server_prefix(guild_id, prefix):
        """Sets the server's prefix."""
        DB._queues[DB._servers].put(UpdateOne({"guild_id": guild_id}, {"$set": {"prefix": prefix}}))

    # Guild-scoped channel registry. Stored under a nested
    # ``channels`` dict on each server document so adding a new
    # category later (e.g. ``debug``, ``alerts``) doesn't need a
    # schema migration. Each value is a Discord channel id (int).
    GUILD_CHANNEL_KEYS = ("updates", "ideas")

    @staticmethod
    def set_guild_channel(guild_id: int, key: str, channel_id: int) -> None:
        """Set a per-guild named channel id (e.g. updates,
        ideas). ``key`` must be in :attr:`GUILD_CHANNEL_KEYS` —
        unknown keys raise so a typo at the call site doesn't
        silently write a garbage field. Stored as
        ``channels.<key>`` on the server document; an upsert so a
        guild that hasn't been seen by the bot yet still gets
        the channel registered."""
        if key not in DB.GUILD_CHANNEL_KEYS:
            raise ValueError(
                f"Unknown guild channel key {key!r}; "
                f"expected one of {DB.GUILD_CHANNEL_KEYS}"
            )
        DB._queues[DB._servers].put(
            UpdateOne(
                {"guild_id": guild_id},
                {"$set": {f"channels.{key}": channel_id}},
                upsert=True,
            )
        )

    @check_connection
    @staticmethod
    def get_guild_channels(guild_id: int) -> dict:
        """Return the per-guild channel-id dict for the given
        guild (e.g. ``{"updates": 123, "ideas": 456}``).
        Empty dict when the guild has no channels configured or
        no server document exists yet — callers can ``.get(key)``
        without pre-checking."""
        server = DB._mongoDB.servers.find_one({"guild_id": guild_id})
        if not server:
            return {}
        return dict(server.get("channels") or {})

    @check_connection
    @staticmethod
    def get_game(guild_id, channel_id):
        """Retrieves the game document identified by the
        (guild_id, channel_id) pair, or ``None`` if none exists.
        Returning None does not imply the guild is gameless — use
        ``find_any_game_in_guild`` / ``find_all_games`` for that."""
        return DB._games.find_one(
            {"guild_id": guild_id, "channel_id": channel_id}
        )

    @check_connection
    @staticmethod
    def find_any_game_in_guild(guild_id):
        """Returns the first game document found for ``guild_id``, or
        ``None`` if the guild has no games. Used by the ``$game create``
        admin check to guard against creating a second game in a guild
        that already has one. Distinct from ``get_game`` which requires
        both guild_id and channel_id."""
        return DB._games.find_one({"guild_id": guild_id})

    @staticmethod
    def insert_game(guild_id, channel_id):
        """Inserts a game into the database."""
        DB._queues[DB._games].put(InsertOne({"guild_id": guild_id, "channel_id": channel_id}))

    @check_connection
    @staticmethod
    def get_last_command(guild_id):
        """Retrieves the last command recorded in the database."""
        return DB._command_statics.find_one({"guild_id": guild_id}, sort=[("timestamp", DESCENDING)])

    @check_connection
    @staticmethod
    def get_command_usage(guild_id=None, channel_id=None, user_id=None,
                          limit=None, ascending=False):
        """Aggregates command usage counts. Filter by guild, channel,
        and/or user — omit all for bot-wide. ``limit=None`` returns
        all; negative-style "bottom N" is handled by the caller via
        ``ascending=True``."""
        match = {}
        if guild_id is not None:
            match["guild_id"] = guild_id
        if channel_id is not None:
            match["channel_id"] = channel_id
        if user_id is not None:
            match["user_id"] = user_id
        pipeline = [
            {"$group": {"_id": "$command", "count": {"$sum": 1}}},
            {"$sort": {"count": 1 if ascending else -1}},
        ]
        if match:
            pipeline.insert(0, {"$match": match})
        if limit:
            pipeline.append({"$limit": limit})
        return list(DB._command_statics.aggregate(pipeline))

    @check_connection
    @staticmethod
    def get_alias_breakdown(command, guild_id=None, channel_id=None,
                            user_id=None, limit=None, ascending=False):
        """Breaks down usage of a single command by alias — what users
        actually type to invoke it. Returns ``{"_id": alias, "count":
        int}``."""
        match = {"command": command}
        if guild_id is not None:
            match["guild_id"] = guild_id
        if channel_id is not None:
            match["channel_id"] = channel_id
        if user_id is not None:
            match["user_id"] = user_id
        pipeline = [
            {"$match": match},
            {"$group": {"_id": "$alias", "count": {"$sum": 1}}},
            {"$sort": {"count": 1 if ascending else -1}},
        ]
        if limit:
            pipeline.append({"$limit": limit})
        return list(DB._command_statics.aggregate(pipeline))

    @tasks.loop(minutes=5)
    async def watchdog():
        """Monitors critical task loops and alerts if DB writes have stalled."""

        from caldanai.dispatcher import send
        from caldanai.lib.rpg.helpers.utils import save_game_data, generate_report

        restarted = []

        # ``batch_write`` was removed in the 2026-04-21 loop-collapse;
        # ``save_game_data`` now drives both the dirty-state sweep
        # AND the DB drain in the same 1-minute tick, so only one
        # task loop needs watchdog-style heartbeat checking for the
        # DB write pipeline.
        if not save_game_data.is_running():
            _log.error("WATCHDOG: save_game_data was not running — restarting.")
            save_game_data.start()
            restarted.append("save_game_data")

        if not send.is_running():
            _log.error("WATCHDOG: Dispatcher.send was not running — restarting.")
            send.start()
            restarted.append("send")

        # Check each game's GameClock tick. Only monitor games that have
        # enabled features which require the clock (ambience or spawn timer).
        from caldanai.lib.rpg.helpers.utils import RpgUtilities
        bot = getattr(RpgUtilities, "bot", None)
        if bot is not None:
            for game in list(bot.games.values()):
                if not (game.enable_ambience or game.use_spawn_timer):
                    continue
                if not game.game_clock.tick.is_running():
                    guild_name = game.guild.name if game.guild else "unknown"
                    _log.error(
                        f"WATCHDOG: GameClock.tick for '{guild_name}' was not running — restarting."
                    )
                    game.game_clock.tick.start()
                    restarted.append(f"game_clock.tick[{guild_name}]")

        if DB._last_successful_write is not None:
            elapsed = (datetime.now() - DB._last_successful_write).total_seconds()
            if elapsed > _WRITE_ALERT_THRESHOLD and not DB._write_alert_sent:
                _log.critical(
                    f"WATCHDOG: No successful DB write in {int(elapsed)} seconds!"
                )
                try:
                    generate_report(
                        author_id="SYSTEM",
                        author_display_name="Watchdog",
                        message=(
                            f"No successful database write in {int(elapsed)} seconds.\n"
                            f"save_game_data running: {save_game_data.is_running()}\n"
                            f"DB connected flag: {DB._is_connected}\n"
                            f"Tasks restarted this cycle: {restarted or 'none'}"
                        ),
                    )
                except Exception:
                    _log.error("WATCHDOG: Failed to send alert.", exc_info=True)
                DB._write_alert_sent = True

        elif save_game_data.is_running():
            # First cycle after startup — seed the timestamp
            DB._last_successful_write = datetime.now()

        if restarted:
            try:
                generate_report(
                    author_id="SYSTEM",
                    author_display_name="Watchdog",
                    message=f"Restarted dead task(s): {', '.join(restarted)}",
                )
            except Exception:
                _log.error("WATCHDOG: Failed to send restart alert.", exc_info=True)

    @watchdog.error
    async def watchdog_error(e):
        error_info = traceback.format_exc()
        _log.error(f"Watchdog task error: {error_info}")
