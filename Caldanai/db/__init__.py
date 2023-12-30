import functools
import logging
from collections import defaultdict
from enum import IntEnum, Enum
from queue import Queue

from discord.ext import tasks
from pymongo import DeleteMany, DeleteOne, InsertOne, MongoClient, UpdateOne
from pymongo.database import Database
from pymongo.errors import BulkWriteError, ConnectionFailure

from Caldanai import Observer, Subject
from Caldanai.environment import DB_CONNECTION


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


class DoubleBuffer:
		"""A double buffer class for queue processing."""
		def __init__(self):
			DB.q1 = Queue()
			DB.q2 = Queue()
			DB.retry = Queue()
			DB.active = DB.q1
			DB.passive = DB.q2
		
		def put(item):
			"""Puts an item into the active queue."""
			DB.active.put(item)
		
		def swap(self):
			"""Swaps the buffer queues."""
			DB.active, DB.passive = DB.passive, DB.active
		
		def get_all(self):
			"""Retrieves all items from the active buffer and clears it."""
			DB.swap()
			items = list(DB.passive.queue)
			DB.passive.queue.clear()
			return items


class DB(Observer, Subject):
	"""Wrapper for MongoDB operations."""
	_mongoClient: MongoClient = MongoClient(DB_CONNECTION)
	_mongoDB: Database = _mongoClient.caldanaiDB
	_queues = defaultdict(DoubleBuffer)
	
	@staticmethod
	def is_connected() -> bool:
		"""Pings the MongoDB client to verify connectivity."""
		try:
			DB._mongoClient.admin.command('ping')
			return True
		except ConnectionFailure:
			return False
	
	@staticmethod
	async def update(message):
		if isinstance(message, dict):
			for k,v in message.items():
				if isinstance(k, DatabaseCollections) and DatabaseCollections.is_writable(k):
					DB._queues[k.value].put(v)
	
	@staticmethod
	def check_connection(func):
		"""Verifies database connectivity, raising a DatabaseConnectionError if the connection fails."""
		@functools.wraps(func)
		def wrapper(*args, **kwargs):
			if DB.is_connected:
				return func(*args, **kwargs)
			else:
				logging.error(f"Error occurred while performing connection test for {func}.")
		return wrapper

	@check_connection
	@staticmethod
	def close_db_connection():
		"""Closes the database connection."""
		DB._mongoClient.close()

	@tasks.loop(minutes=1)
	async def batch_write(self):
		"""Performs batch writing to the database for the queued items."""
		collections = list(DB._queues.keys())
		for collection in collections:
			if DB.is_connected():
				ops = DB._queues[collection].get_all()
				try:
					DB._mongoDB[collection].bulk_write(ops, ordered=False)
				except BulkWriteError as e:
					logging.error(f"Error occurred while performing bulk write operation: {e.details}")
					raise e
			else:
				logging.error("No connection for batch_write operation.")

	@check_connection
	@staticmethod
	def find_players_by_user_id(user_id):
		"""Finds all players associated with the supplied user ID."""
		return DB._mongoDB.players.find({'user_id': user_id})
	
	@check_connection
	@staticmethod
	def get_player(guild_id, user_id):
		"""Returns the player associated with a guild ID and user ID."""
		return DB._mongoDB.players.find_one({'guild_id': guild_id, 'user_id': user_id})
	
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
		DB._queues["games"].put(DeleteOne({'guild_id': guild_id}))
		DB._queues["players"].put(DeleteMany({'guild_id': guild_id}))
	
	@staticmethod
	def update_game(guild_id, guild_dict, upsert=False):
		"""Enqueues an update for a game object in the database."""
		DB._queues["games"].put(UpdateOne(
			{'guild_id': guild_id},
			{'$set': guild_dict},
			upsert=upsert))
	
	@staticmethod
	def update_statistic(guild_id, inc_doc):
		"""Enqueues an update for the server statistics."""
		DB._queues["statics"].put(UpdateOne(
			{'guild_id': guild_id},
			{'$inc': inc_doc },
			upsert=True))

	@staticmethod
	def update_user_statics(doc):
		"""Enqueues an insertion for the given user statistics record."""
		DB._queues["user_command_statics"].put(InsertOne(doc))

	@staticmethod
	def update_player(guild_id, user_id, player_dict):
		"""Enqueues a player upsert."""
		DB._queues["players"].put(UpdateOne(
			{"guild_id": guild_id, "user_id": user_id},
			{"$set": player_dict},
			upsert=True))

	@staticmethod
	def insert_server(guild_id, name=None, prefix='$'):
		"""Enqueues a server insert."""
		DB._queues["servers"].put(InsertOne({'guild_id': guild_id, 'name': name, 'prefix': prefix}))
	
	@staticmethod
	def delete_server(guild_id):
		"""Enqueueus deletion of a server, and all associated games and players."""
		DB._queues["servers"].put(DeleteOne({'guild_id': guild_id}))
		DB._queues["games"].put(DeleteMany({'guild_id': guild_id}))
		DB._queues["players"].put(DeleteMany({'guild_id': guild_id}))
	
	@check_connection
	@staticmethod
	def find_players_by_guild_id(guild_id):
		"""Retrieves all players associated with a guild ID."""
		return DB._mongoDB.players.find({'guild_id': guild_id})
	
	@staticmethod
	def delete_player(guild_id, user_id):
		"""Deletes a player from the database."""
		DB._queues["players"].put(DeleteOne({'guild_id': guild_id, 'user_id': user_id}))
	
	@staticmethod
	def delete_all_players(guild_id):
		"""Deletes all players in the database associated with the given guild_id."""
		DB._queues["players"].put(DeleteMany({'guild_id': guild_id}))
	
	@staticmethod
	def update_server_prefix(guild_id, prefix):
		"""Sets the server's prefix."""
		DB._queues["servers"].put(UpdateOne({'guild_id': guild_id}, {'$set': {'prefix': prefix}}))
	
	@check_connection
	@staticmethod
	def get_game_by_guild_id(guild_id):
		"""Retrieves a game by guild ID."""
		return DB._mongoDB.games.find_one({'guild_id': guild_id})
	
	@staticmethod
	def insert_game(guild_id, channel_id):
		"""Inserts a game into the database."""
		DB._queues["games"].put(InsertOne({'guild_id': guild_id, 'channelId': channel_id}))
	
	@check_connection
	@staticmethod
	def get_last_command(guild_id):
		"""Retrieves the last command recorded in the database."""
		return DB._mongoDB.user_command_statics.find({'guild_id': guild_id}).sort('timestamp', -1).limit(1)
