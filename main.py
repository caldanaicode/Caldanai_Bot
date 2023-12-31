import asyncio
import sys
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

async def start_bot(bot, loop):
	running = False
	stdout("Running bot.")
	while not running:
		try:
			running = True
			loop.run_until_complete(bot.start(bot.TOKEN, reconnect=True))
			loop.run_forever()
			
			logger.handlers.clear()
			stdout("Closing DB connection.")
			DB.close_db_connection()

		except HTTPException as e:
			running = False
			err = traceback.format_exc(e)
			logger.error(f"Error running bot. Retrying in 30 seconds: {err}")
			await asyncio.sleep(30)
			
if __name__ == "__main__":
	loop = asyncio.get_event_loop()
	bot: Bot = loop.run_until_complete(setup())
	start_bot(bot, loop)
