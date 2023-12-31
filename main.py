import asyncio
from logging import DEBUG, getLogger, Formatter, INFO
import traceback

from discord import HTTPException

from Caldanai.Logger import MongoHandler, logger, stdout
from Caldanai.db import DB
from Caldanai.lib.bot import Bot

def setup_logging():
	stdout("Setting up logging...")
	disclog = getLogger('discord')
	disclog.setLevel(INFO)
	logger.setLevel(DEBUG)
	
	f = Formatter('%(asctime)23s | %(levelname)-8s | %(name)-20s | %(message)s')

	# DB logging
	ignore = (
		'Dispatching event socket_response',
		'Dispatching event socket_raw_receive',
		'For Shard ID None: WebSocket Event: {\'t\': None, \'s\': None, \'op\': 11',
		'Shard ID None has successfully RESUMED session',
		'Dispatching event message',
		'Dispatching event typing',
		'Dispatching event socket_raw_send',
		'Keeping shard ID None websocket alive',
		'Shard ID None has successfully RESUMED session'
	)
	mHandler = MongoHandler(DB._mongoDB.logs_discord, ignore)
	mHandler.setFormatter(f)
	disclog.addHandler(mHandler)
	disclog.propagate = False
	logger.addHandler(mHandler)
	logger.propagate = False
	stdout("Logging setup complete.")


async def setup():
	setup_logging()
	stdout("Setting up bot.")
	bot = Bot()
	await bot.setup()
	return bot

async def start_bot(*, bot: Bot):
	stdout("Running bot.")
	while True:
		try:
			await bot.start(bot.TOKEN, reconnect=True)

		except HTTPException as e:
			err = traceback.format_exc(e)
			logger.error(f"Error running bot. Retrying in 5 minutes: {err}")
			await asyncio.sleep(300)
		
		except Exception as e:
			err = traceback.format_exc(e)
			logger.error(f"Unexpected error: {err}")
			return

if __name__ == "__main__":
	bot = asyncio.run(setup())
	asyncio.run(start_bot(bot=bot))
	logger.handlers.clear()
	stdout("Closing DB connection.")
	DB.close_db_connection()