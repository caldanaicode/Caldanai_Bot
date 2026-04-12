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
from pymongo.errors import BulkWriteError

from caldanai.double_buffer import DoubleBuffer
from caldanai.environment import DB_CONNECTION, STAGE
from caldanai.logger import MongoHandler, get_logger

_log = get_logger(__name__)

# Seconds without a successful DB write before an alert is sent.
_WRITE_ALERT_THRESHOLD = 300


class DB:
    """Wrapper for MongoDB operations."""

    _mongoClient: MongoClient = MongoClient(DB_CONNECTION)
    _mongoDB: Database = _mongoClient.caldanaiTest if STAGE == "TEST" else _mongoClient.caldanaiDB
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

        if not DB.batch_write.is_running():
            DB.batch_write.start()
            _log.debug("batch_write() started")

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
        """Closes the database connection."""

        DB.batch_write.stop()
        DB._mongoClient.close()

    @tasks.loop(minutes=1)
    async def batch_write():
        """Performs batch writing to the database for the queued items.

        Handles its own connection checking inline so that a failed ping
        skips the current cycle without ever stopping the task loop.
        """

        try:
            DB._mongoClient.admin.command("ping")
            if not DB._is_connected:
                DB.on_connected()
        except Exception:
            _log.error("DB ping failed during batch_write.", exc_info=True)
            if DB._is_connected:
                DB.on_disconnected()
            return  # skip this cycle; the task stays alive

        attempts = 0
        successes = 0
        collections = list(DB._queues.keys())
        for collection in collections:
            if ops := DB._queues[collection].get_all():
                _log.debug(
                    f"Writing {len(ops)} queued DB update{'s' if len(ops) != 1 else ''} to '{collection.full_name}'"
                )
                attempts += 1
                try:
                    result = collection.bulk_write(ops, ordered=False)
                    _log.debug(f"{result=}")
                    successes += 1
                except BulkWriteError:
                    error_info = traceback.format_exc()
                    _log.error(f"Error occurred while performing bulk write operation: {error_info}")

        if DB._mongoHandler and (errors := [InsertOne(item) for item in DB._mongoHandler.queue.get_all()]):
            attempts += 1
            try:
                DB._logs.bulk_write(errors)
                successes += 1
            except BulkWriteError:
                error_info = traceback.format_exc()
                _log.error(f"Error occurred while performing bulk write operation: {error_info}")

        # Only bump the watchdog timestamp if we either had nothing to write
        # (connection is healthy, confirmed by the earlier ping) or at least
        # one bulk_write actually succeeded. If we attempted writes and every
        # one raised, leave the timestamp alone so the watchdog can fire.
        if attempts == 0 or successes > 0:
            DB._last_successful_write = datetime.now()
            DB._write_alert_sent = False

    @batch_write.error
    async def batch_write_error(e):
        error_info = traceback.format_exc()
        _log.error(f"batch_write task error: {error_info}")

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
    def get_player(guild_id, user_id):
        """Returns the player associated with a guild ID and user ID."""
        return DB._mongoDB.players.find_one({"guild_id": guild_id, "user_id": user_id})

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
    def delete_game(guild_id):
        """Enqueues deletion of a game and its associated players from the database."""
        DB._queues[DB._games].put(DeleteOne({"guild_id": guild_id}))
        DB._queues[DB._players].put(DeleteMany({"guild_id": guild_id}))

    @staticmethod
    def update_game(guild_id, guild_dict, upsert=False):
        """Enqueues an update for a game object in the database."""
        DB._queues[DB._games].put(UpdateOne({"guild_id": guild_id}, {"$set": guild_dict}, upsert=upsert))

    @staticmethod
    def update_statistic(guild_id, inc_doc):
        """Enqueues an update for the server statistics."""
        DB._queues[DB._statics].put(UpdateOne({"guild_id": guild_id}, {"$inc": inc_doc}, upsert=True))

    @staticmethod
    def update_user_statics(doc):
        """Enqueues an insertion for the given user statistics record."""
        DB._queues[DB._command_statics].put(InsertOne(doc))

    @staticmethod
    def update_player(guild_id, user_id, player_dict):
        """Enqueues a player upsert."""
        DB._queues[DB._players].put(
            UpdateOne({"guild_id": guild_id, "user_id": user_id}, {"$set": player_dict}, upsert=True)
        )

    @staticmethod
    def insert_server(guild_id, name=None, prefix="$"):
        """Enqueues a server insert."""
        DB._queues[DB._servers].put(InsertOne({"guild_id": guild_id, "name": name, "prefix": prefix}))

    @staticmethod
    def delete_server(guild_id):
        """Enqueueus deletion of a server, and all associated games and players."""
        DB._queues[DB._servers].put(DeleteOne({"guild_id": guild_id}))
        DB._queues[DB._games].put(DeleteMany({"guild_id": guild_id}))
        DB._queues[DB._players].put(DeleteMany({"guild_id": guild_id}))

    @check_connection
    @staticmethod
    def find_players_by_guild_id(guild_id):
        """Retrieves all players associated with a guild ID."""
        return DB._players.find({"guild_id": guild_id})

    @staticmethod
    def delete_player(guild_id, user_id):
        """Deletes a player from the database."""
        DB._queues[DB._players].put(DeleteOne({"guild_id": guild_id, "user_id": user_id}))

    @staticmethod
    def delete_all_players(guild_id):
        """Deletes all players in the database associated with the given guild_id."""
        DB._queues[DB._players].put(DeleteMany({"guild_id": guild_id}))

    @staticmethod
    def update_server_prefix(guild_id, prefix):
        """Sets the server's prefix."""
        DB._queues[DB._servers].put(UpdateOne({"guild_id": guild_id}, {"$set": {"prefix": prefix}}))

    @check_connection
    @staticmethod
    def get_game_by_guild_id(guild_id):
        """Retrieves a game by guild ID."""
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

    @tasks.loop(minutes=5)
    async def watchdog():
        """Monitors critical task loops and alerts if DB writes have stalled."""

        from caldanai.dispatcher import send
        from caldanai.lib.rpg.helpers.utils import save_game_data, generate_report

        restarted = []

        if not DB.batch_write.is_running():
            _log.error("WATCHDOG: batch_write was not running — restarting.")
            DB.batch_write.start()
            restarted.append("batch_write")

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
                            f"batch_write running: {DB.batch_write.is_running()}\n"
                            f"DB connected flag: {DB._is_connected}\n"
                            f"Tasks restarted this cycle: {restarted or 'none'}"
                        ),
                    )
                except Exception:
                    _log.error("WATCHDOG: Failed to send alert.", exc_info=True)
                DB._write_alert_sent = True

        elif DB.batch_write.is_running():
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
