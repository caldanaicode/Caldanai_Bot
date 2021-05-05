import pymongo
from Caldanai.environment import DB_CONNECTION


mongoClient = pymongo.MongoClient(DB_CONNECTION)
MongoDB = mongoClient.caldanaiDB
