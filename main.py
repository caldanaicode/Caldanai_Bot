import asyncio
from logging import getLogger, Formatter, INFO
from threading import Thread
from flask import Flask, render_template
from pymongo import DESCENDING

from Caldanai.Logger import MongoHandler, stdout
from Caldanai.db.__init__ import MongoDB
from Caldanai.lib.bot import Bot

app = Flask(__name__, static_folder='site/static', template_folder='site/templates')


@app.route('/')
def main_web():
	return render_template('main.html', content='Caldanai Bot is alive and breathing heavily, staring hungrily at you.')


@app.route('/formatter')
def formatter():
	return render_template('formatter.html')


@app.route('/logviewer')
def logviewer() -> list:
	entries = ()
	headers = ('When', 'Level', 'Module', 'Message')
	results = MongoDB.logs_discord.find().sort('_id', DESCENDING).limit(200)
	if results is not None:
		entries = ((e['asctime'], e['level'], e['name'], e['message']) for e in results)
	return render_template('logviewer.html', headers=headers, entries=entries)


def run():
	app.run(host='0.0.0.0', port=8080)


bot = Bot()


async def main():
	logger = getLogger('discord')
	logger.setLevel(INFO)  # logger.setLevel(DEBUG)
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
		'Keeping shard ID None websocket alive'
	)
	mHandler = MongoHandler(MongoDB.logs_discord, ignore)
	mHandler.setFormatter(f)
	logger.addHandler(mHandler)

	stdout("Setting up bot...")
	await bot.setup()

srv_thread = Thread(target=run)
srv_thread.start()
asyncio.run(main())
stdout(f"Running bot...")
bot.run(bot.TOKEN, reconnect=True)
