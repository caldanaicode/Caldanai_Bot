import asyncio
import functools
import os
import traceback

from collections import defaultdict
from discord.ext import tasks
from pymongo import DESCENDING, DeleteMany, DeleteOne, InsertOne, MongoClient, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError

from Caldanai.DoubleBuffer import DoubleBuffer
from Caldanai.environment import DB_CONNECTION, STAGE
from Caldanai.Logger import MongoHandler, get_logger

_log = get_logger(__name__)


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

    @staticmethod
    def on_connected() -> None:
        """Things to do when connection is (re-)established."""

        _log.info("Database connected")
        DB._is_connected = True
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
        if DB.batch_write.is_running():
            DB.batch_write.stop()
            _log.debug("batch_write() stopped")

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

        if asyncio.iscoroutinefunction(func):

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
    @check_connection
    async def batch_write():
        """Performs batch writing to the database for the queued items."""

        collections = DB._queues.keys()
        for collection in collections:
            if ops := DB._queues[collection].get_all():
                _log.debug(
                    f"Writing {len(ops)} queued DB update{'s' if len(ops) != 1 else ''} to '{collection.full_name}'"
                )
                try:
                    result = collection.bulk_write(ops, ordered=False)
                    _log.debug(f"{result=}")
                except BulkWriteError:
                    error_info = traceback.format_exc()
                    _log.error(f"Error occurred while performing bulk write operation: {error_info}")

        if errors := [InsertOne(item) for item in DB._mongoHandler.queue.get_all()]:
            try:
                DB._logs.bulk_write(errors)
            except BulkWriteError:
                error_info = traceback.format_exc()
                _log.error(f"Error occurred while performing bulk write operation: {error_info}")

    @batch_write.error
    async def batch_write_error(e):
        error_info = traceback.format_exc()
        _log.error(error_info)

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
        DB._queues[DB._games].put(InsertOne({"guild_id": guild_id, "channelId": channel_id}))

    @check_connection
    @staticmethod
    def get_last_command(guild_id):
        """Retrieves the last command recorded in the database."""
        return DB._command_statics.find_one({"guild_id": guild_id}, sort=[("timestamp", DESCENDING)])
