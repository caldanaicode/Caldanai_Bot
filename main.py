from logging import getLogger, DEBUG, Formatter
from MongoHandler import MongoHandler
from Caldanai.db.db import MongoDB
from Caldanai.lib.bot import bot
from threading import Thread
from server import run as runServer

logger = getLogger('discord')
logger.setLevel(DEBUG)
formatter = Formatter('%(asctime)23s | %(levelname)-8s | %(name)-20s | %(message)s')

# DB logging
ignore = (
	'Dispatching event socket_response',
	'Dispatching event socket_raw_receive',
	'For Shard ID None: WebSocket Event: {\'t\': None, \'s\': None, \'op\': 11',
	'Dispatching event message',
	'Dispatching event typing',
	'Dispatching event socket_raw_send',
	'Keeping shard ID None websocket alive'
)
mHandler = MongoHandler(MongoDB.logs_discord, ignore)
mHandler.setFormatter(formatter)
logger.addHandler(mHandler)

serverThread = Thread(target=runServer)
serverThread.start()

bot.run()