from os import getenv
from dotenv import load_dotenv


load_dotenv()

DB_CONNECTION = getenv("DB_CONNECTION")
LOG_LEVEL = getenv("LOG_LEVEL", "INFO")
STAGE = getenv("STAGE", "PROD")

# Mongo database names — separated so forks of this project can
# point at their own DBs without code changes. Defaults are
# generic placeholders; deployments should set explicit names in
# ``.env``. ``LIVE_DB_NAME`` is what tooling under ``tools/``
# always targets (see ``tools/_common.py``); the bot itself
# selects between live and test based on ``STAGE``.
LIVE_DB_NAME = getenv("LIVE_DB_NAME", "caldanai")
TEST_DB_NAME = getenv("TEST_DB_NAME", "caldanai_test")

if not DB_CONNECTION:
    raise RuntimeError("DB_CONNECTION environment variable is required. Check your .env file.")
