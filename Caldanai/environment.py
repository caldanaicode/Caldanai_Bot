from os import getenv
from dotenv import load_dotenv

load_dotenv()

DB_CONNECTION = getenv("DB_CONNECTION")