from os import getenv
from dotenv import load_dotenv


load_dotenv()

DB_CONNECTION = getenv("DB_CONNECTION")
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")
STAGE = getenv("STAGE", "PROD")

if not DB_CONNECTION:
    raise RuntimeError("DB_CONNECTION environment variable is required. Check your .env file.")
