from os import getenv
import pymongo
import dns

mongoClient = pymongo.MongoClient(f"{getenv('DBCONNECTION')}")
MongoDB = mongoClient.caldanaiDB