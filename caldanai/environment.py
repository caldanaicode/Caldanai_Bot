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

# Comma-separated list of Discord user ids whose ``Message.author.bot``
# is True but who should be treated as real players by the RPG
# command layer (i.e. bypass the bot-shoo HAL9000 response). Intended
# for a dedicated tester bot driving playtest from a script; scoped
# to whoever is listed, never all-bots.
#
# Example::
#
#     PLAYER_BOT_ALLOWLIST=1234567890123456789
#     PLAYER_BOT_ALLOWLIST=1234...,2345...
#
# IDs can be found in the Discord Developer Portal for the bot
# application. Empty / unset means no allowlist (default behavior:
# every bot is shooed away).
_raw_allowlist = getenv("PLAYER_BOT_ALLOWLIST", "")
PLAYER_BOT_ALLOWLIST = frozenset(
    int(s.strip()) for s in _raw_allowlist.split(",") if s.strip().isdigit()
)

if not DB_CONNECTION:
    raise RuntimeError("DB_CONNECTION environment variable is required. Check your .env file.")
