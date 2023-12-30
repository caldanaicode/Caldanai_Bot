import asyncio
import sys
from logging import getLogger, Formatter, INFO
from threading import Thread
from flask import Flask, render_template
# from pymongo import DESCENDING

from Caldanai.Logger import MongoHandler, stdout
from Caldanai.db import DB
from Caldanai.environment import FLASK_PORT, FLASK_HOST
from Caldanai.lib.bot import Bot
from Caldanai.Dispatcher import Dispatcher

app = Flask(__name__, static_folder='site/static', template_folder='site/templates')
logger = getLogger('discord')
bot = Bot()
bot_thread = None


@app.route('/')
def main_web():
	return render_template('main.html', content='Caldanai Bot is alive and breathing heavily, staring hungrily at you.')


# @app.route('/formatter')
# def formatter():
# 	return render_template('formatter.html')


# @app.route('/logviewer')
# def logviewer() -> list:
# 	entries = ()
# 	headers = ('When', 'Level', 'Module', 'Message')
# 	results = MongoDB.logs_discord.find().sort('_id', DESCENDING).limit(200)
# 	if results is not None:
# 		entries = ((e['asctime'], e['level'], e['name'], e['message']) for e in results)
# 	return render_template('logviewer.html', headers=headers, entries=entries)


def run():
	app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False)


def setup_logging():
	stdout("Setting up logging...")
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
		'Keeping shard ID None websocket alive',
		'Shard ID None has successfully RESUMED session'
	)
	mHandler = MongoHandler(DB._mongoDB.logs_discord, ignore)
	mHandler.setFormatter(f)
	logger.addHandler(mHandler)
	stdout("Logging setup complete.")


def notify_servers(message: str):
	if bot.is_closed():
		stdout("Unable to notify servers: bot is shut down.")
		return

	if isinstance(message, list):
		message = ' '.join(message)

	stdout(f"Sending '{message}' to all servers.")
	msg = []
	for game in bot.games.values():
		Dispatcher.add(game.channel, message)
		msg.append(f'Channel {game.channel.name}')
	stdout(f"Queued for {', '.join(msg)}")


async def shutdown(message):
	if bot.is_closed():
		stdout("Bot is already shut down.")
		return

	stdout("Shutting down bot.")
	if message:
		notify_servers(message)
	Dispatcher.flush = True
	while not Dispatcher.queue.empty():
		await asyncio.sleep(1.0)

	await bot.close()


commands = {
	'shutdown': shutdown,
	'notify': notify_servers
}


async def console_loop():
	stdout("Running console loop...")
	while (line := sys.stdin.readline().strip()).lower() != 'exit':
		cmd, *arg = line.split(' ')
		cmd = cmd.lower()
		if len(cmd) == 0:
			continue

		if cmd in commands.keys():
			if asyncio.iscoroutinefunction(commands[cmd]):
				await commands[cmd](arg)
			else:
				commands[cmd](arg)
		await asyncio.sleep(0.25)

	stdout("Console loop has ended.")
	loop.close()


async def setup():
	setup_logging()
	# stdout("Running web server.")
	# srv_thread = Thread(target=run)
	# srv_thread.start()
	stdout("Setting up bot.")
	await bot.setup()


if __name__ == "__main__":
	loop = asyncio.get_event_loop()
	loop.run_until_complete(setup())

	# TODO: Need to figure out a non-blocking solution for reading from command line.
	# stdout("Running input loop.")
	# loop.create_task(console_loop())

	stdout("Running bot.")
	loop.run_until_complete(bot.start(bot.TOKEN, reconnect=True))

	loop.run_forever()

	logger.handlers.clear()
	DB.close_db_connection()

sys.exit()
