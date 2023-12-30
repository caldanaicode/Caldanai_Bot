import functools
import logging
from collections import defaultdict
from enum import IntEnum, Enum
from queue import Queue

from discord.ext import tasks
from pymongo import DeleteMany, DeleteOne, InsertOne, MongoClient, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError, ServerSelectionTimeoutError

from Caldanai import Observer, Subject
from Caldanai.environment import DB_CONNECTION


class DatabaseConnectionError(Exception):
	"""Represents a database connection error."""
	pass


class DatabaseMessages(IntEnum):
	"""Contains message values for database observer notification."""

	# Connection states
	CONNECTION_SUCCESS = 0
	CONNECTION_RETRY = 1
	CONNECTION_ERROR = 2


class DatabaseCollections(Enum):
	AUTH = 'auth'
	SERVERS = 'servers'
	GAMES = 'games'
	PLAYERS = 'players'
	STATICS = 'statics'
	COMMAND_STATICS = 'user_command_statics'

	@classmethod
	def is_writable(cls, value):
		return value in cls.__members__ and value != cls.AUTH.name


class MongoDatabase(Observer, Subject):
	"""Wrapper for MongoDB operations."""

	class DoubleBuffer:
		"""A double buffer class for queue processing."""
		def __init__(self):
			self.q1 = Queue()
			self.q2 = Queue()
			self.retry = Queue()
			self.active = self.q1
			self.passive = self.q2
		
		def put(self, item):
			"""Puts an item into the active queue."""
			self.active.put(item)
		
		def swap(self):
			"""Swaps the buffer queues."""
			self.active, self.passive = self.passive, self.active
		
		def get_all(self):
			"""Retrieves all items from the active buffer and clears it."""
			self.swap()
			items = list(self.passive.queue)
			self.passive.queue.clear()
			return items
	
	def __init__(self):
		"""Initializes the database connection."""
		self._mongoClient: MongoClient = None
		self._mongoDB: Database = None
		self._is_connected = False
		self._queues = defaultdict(self.DoubleBuffer)
		self._reconnect.start()
	
	@property
	def is_connected(self):
		"""Whether the database was connected when last checked. This gets updated when operations fail due to ServerSelectionTimeoutError, or when successfully reconnected."""
		return self._is_connected

	@tasks.loop(seconds=180)
	async def _reconnect(self):
		"""Attempts reconnection to MongoDB with linear backoff and retry."""
		while not self._is_connected:
			try:
				self._mongoClient = MongoClient(DB_CONNECTION)
				self._mongoDB = self._mongoClient.caldanaiDB
				self._is_connected = True
				self._reconnect.stop()
				await self.notify(DatabaseMessages.CONNECTION_SUCCESS)
			except ServerSelectionTimeoutError:
				self._is_connected = False
				await self.notify(DatabaseMessages.CONNECTION_RETRY)
				logging.error(f"Failed to connect to MongoDB. Retrying in 3 minutes.")
	
	async def update(self, message):
		if isinstance(message, dict):
			for k,v in message.items():
				if isinstance(k, DatabaseCollections) and DatabaseCollections.is_writable(k):
					self._queues[k.value].put(v)
	
	def check_connection(func):
		"""Verifies database connectivity, raising a DatabaseConnectionError if the connection fails."""
		@functools.wraps(func)
		def wrapper(self, *args, **kwargs):
			if self._is_connected:
				try:
					return func(self, *args, **kwargs)
				except ServerSelectionTimeoutError:
					self._is_connected = False
					self._reconnect.start()
		return wrapper

	@check_connection
	def close_db_connection(self):
		"""Closes the database connection."""
		self._mongoClient.close()

	@check_connection
	@tasks.loop(minutes=1)
	async def batch_write(self):
		"""Performs batch writing to the database for the queued items."""
		collections = list(self._queues.keys())
		for collection in collections:
			ops = self._queues[collection].get_all()
			try:
				await self._mongoDB[collection].bulk_write(ops, ordered=False)
			except BulkWriteError as e:
				logging.error(f"Error occurred while performing bulk write operation: {e.details}")
				raise e

	@check_connection
	def find_players_by_user_id(self, user_id):
		"""Finds all players associated with the supplied user ID."""
		return self._mongoDB.players.find({'user_id': user_id})
	
	@check_connection
	def get_player(self, guild_id, user_id):
		"""Returns the player associated with a guild ID and user ID."""
		return self._mongoDB.players.find_one(self, {'guild_id': guild_id, 'user_id': user_id})
	
	@check_connection
	def find_all_games(self):
		"""Find all games in the database."""
		return self._mongoDB.games.find()
	
	@check_connection
	def get_auth(self):
		"""Returns the authorization record."""
		return self._mongoDB.auth.find_one()
	
	@check_connection
	def get_server_by_guild_id(self, id):
		"""Returns the server associated with the given Guild ID."""
		return self._mongoDB.servers.find_one({"guild_id": id})

	def delete_game(self, guild_id):
		"""Enqueues deletion of a game and its associated players from the database."""
		self._queues["games"].put(DeleteOne({'guild_id': guild_id}))
		self._queues["players"].put(DeleteMany({'guild_id': guild_id}))
	
	def update_game(self, guild_id, guild_dict, upsert=False):
		"""Enqueues an update for a game object in the database."""
		self._queues["games"].put(UpdateOne(
			{'guild_id': guild_id},
			{'$set': guild_dict},
			upsert=upsert))
	
	def update_statistic(self, guild_id, inc_doc):
		"""Enqueues an update for the server statistics."""
		self._queues["statics"].put(UpdateOne(
			{'guild_id': guild_id},
			{'$inc': inc_doc },
			upsert=True))

	def update_user_statics(self, doc):
		"""Enqueues an insertion for the given user statistics record."""
		self._queues["user_command_statics"].put(InsertOne(doc))

	def update_player(self, guild_id, user_id, player_dict):
		"""Enqueues a player upsert."""
		self._queues["players"].put(UpdateOne(
			{"guild_id": guild_id, "user_id": user_id},
			{"$set": player_dict},
			upsert=True))

	def insert_server(self, guild_id, name=None, prefix='$'):
		"""Enqueues a server insert."""
		self._queues["servers"].put(InsertOne({'guild_id': guild_id, 'name': name, 'prefix': prefix}))
	
	def delete_server(self, guild_id):
		"""Enqueueus deletion of a server, and all associated games and players."""
		self._queues["servers"].put(DeleteOne({'guild_id': guild_id}))
		self._queues["games"].put(DeleteMany({'guild_id': guild_id}))
		self._queues["players"].put(DeleteMany({'guild_id': guild_id}))
	
	@check_connection
	def find_players_by_guild_id(self, guild_id):
		"""Retrieves all players associated with a guild ID."""
		return self._mongoDB.players.find({'guild_id': guild_id})
	
	def delete_player(self, guild_id, user_id):
		"""Deletes a player from the database."""
		self._queues["players"].put(DeleteOne({'guild_id': guild_id, 'user_id': user_id}))
	
	def delete_all_players(self, guild_id):
		"""Deletes all players in the database associated with the given guild_id."""
		self._queues["players"].put(DeleteMany({'guild_id': guild_id}))
	
	def update_server_prefix(self, guild_id, prefix):
		"""Sets the server's prefix."""
		self._queues["servers"].put(UpdateOne({'guild_id': guild_id}, {'$set': {'prefix': prefix}}))
	
	@check_connection
	def get_game_by_guild_id(self, guild_id):
		"""Retrieves a game by guild ID."""
		return self._mongoDB.games.find_one({'guild_id': guild_id})
	
	def insert_game(self, guild_id, channel_id):
		"""Inserts a game into the database."""
		self._queues["games"].put(InsertOne({'guild_id': guild_id, 'channelId': channel_id}))
	
	@check_connection
	def get_last_command(self, guild_id):
		"""Retrieves the last command recorded in the database."""
		return self._mongoDB.user_command_statics.find({'guild_id': guild_id}).sort('timestamp', -1).limit(1)

DB = MongoDatabase()
DB.batch_write.start()