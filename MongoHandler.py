import logging
from pymongo.collection import Collection

class MongoHandler(logging.Handler):
	def __init__(self, collection: Collection, ignored: tuple = ()):
		logging.Handler.__init__(self)
		self.collection = collection
		self.ignored = ignored or ()
	
	def emit(self, record: logging.LogRecord):
		self.format(record)

		if any(record.message.startswith(msg) for msg in self.ignored):
			return

		entry = {
			'asctime': record.asctime,
			'level': record.levelname,
			'name': record.name,
			'message': record.message
		}
		
		self.collection.insert_one(entry)