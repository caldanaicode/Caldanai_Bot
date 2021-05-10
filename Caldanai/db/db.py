from pymongo import MongoClient
from pymongo.database import Database
from Caldanai.environment import DB_CONNECTION


mongoClient = MongoClient(DB_CONNECTION)
MongoDB: Database = mongoClient.caldanaiDB
