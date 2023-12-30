from datetime import datetime
import traceback
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
			stdout(f'{record.levelname} - {record.name}: {record.message}')
		except Exception as e:
			error_info = traceback.format_exc(e)
			stdout(error_info)

def stdout(msg):
	print(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {msg}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('CaldanaiBot')
logger.setLevel(logging.DEBUG)
