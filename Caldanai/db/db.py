from os import getenv
import pymongo
from dotenv import load_dotenv


load_dotenv()
mongoClient = pymongo.MongoClient(f"{getenv('DBCONNECTION')}")
MongoDB = mongoClient.caldanaiDB