from datetime import datetime
from pymongo.collection import Collection
import logging


class MongoHandler(logging.Handler):
	def __init__(self, collection: Collection, ignored: tuple = ()):
		logging.Handler.__init__(self)
		self.collection = collection
		self.ignored = ignored or ()

	def emit(self, record: logging.LogRecord):
		try:
			self.format(record)

			if any(record.message.startswith(msg) for msg in self.ignored):
				return

			entry = {
				'asctime': record.asctime,
				'level'  : record.levelname,
				'name'   : record.name,
				'message': record.message
			}

			self.collection.insert_one(entry)
			stdout(f'Error from {record.name}: {record.message}')
		except Exception as e:
			stdout(e)


def stdout(msg):
	print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}")
