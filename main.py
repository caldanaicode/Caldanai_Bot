from logging import getLogger, DEBUG, Formatter
from Caldanai.Logger import MongoHandler
from Caldanai.db.db import MongoDB
from Caldanai.lib.bot import bot
from threading import Thread
from flask import Flask, render_template
from pymongo import DESCENDING

app = Flask(__name__, static_folder='site/static', template_folder='site/templates')


@app.route('/')
def main():
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


logger = getLogger('discord')
logger.setLevel(DEBUG)
f = Formatter('%(asctime)23s | %(levelname)-8s | %(name)-20s | %(message)s')

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
mHandler.setFormatter(f)
logger.addHandler(mHandler)

if __name__ == "__main__":
	srv_thread = Thread(target=run)
	srv_thread.start()
	bot.run()
