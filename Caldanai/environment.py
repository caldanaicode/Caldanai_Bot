from dotenv import load_dotenv
from os import getenv

load_dotenv()

DB_CONNECTION = getenv("DBCONNECTION")
OWNER_IDS = getenv('OWNERIDS').split(',')
TOKEN = getenv("TOKEN")
