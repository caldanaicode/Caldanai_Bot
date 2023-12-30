from flask import Flask, render_template
from Caldanai.db.__init__ import MongoDB
from pymongo import DESCENDING

app = Flask('', static_folder='site/static', template_folder='site/templates')


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
	app.run(host="0.0.0.0", port=8080)
