from enum import Enum
import logging
from datetime import datetime

from pymongo.collection import Collection

from caldanai.double_buffer import DoubleBuffer
from caldanai.environment import LOG_LEVEL


class Colors(Enum):
    grey = "\x1b[0;37m"
    white = "\x1b[1;37m"
    green = "\x1b[1;32m"
    yellow = "\x1b[1;33m"
    red = "\x1b[1;31m"
    purple = "\x1b[1;35m"
    blue = "\x1b[1;34m"
    light_blue = "\x1b[1;36m"
    reset = "\x1b[0m"
    blink_red = "\x1b[5m\x1b[1;31m"


def stdout(msg, prepend_timestamp: bool = True, prepend_stdout: bool = False, log_level: int = logging.NOTSET):
    colors = {
        logging.NOTSET: Colors.grey.value,
        logging.DEBUG: Colors.green.value,
        logging.INFO: Colors.white.value,
        logging.WARNING: Colors.yellow.value,
        logging.ERROR: Colors.red.value,
        logging.CRITICAL: Colors.blink_red.value,
    }
    print(
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f ') if prepend_timestamp else ''}"
        f"{'STDOUT - ' if prepend_stdout else ''}{colors.get(log_level, '')}{msg}{Colors.reset.value}"
    )


class MicrosecondFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created)
        formatted = dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S.%f")
        return formatted


class MongoHandler(logging.Handler):
    def __init__(self, collection: Collection, ignored: tuple = ()):
        logging.Handler.__init__(self)
        self.collection = collection
        self.ignored = ignored or ()
        self.queue = DoubleBuffer()

    def emit(self, record: logging.LogRecord):
        self.format(record)

        if any(record.message.startswith(msg) for msg in self.ignored):
            return

        entry = {"asctime": record.asctime, "level": record.levelname, "name": record.name, "message": record.message}

        self.queue.put(entry)
        stdout(
            f"{record.asctime} {record.levelname:8s} [{record.name}] - {record.message}", False, False, record.levelno
        )


def get_logger(name: str = None) -> logging.Logger:
    logger = logging.getLogger(name)
    if name and name.startswith("caldanai"):
        logger.setLevel(LOG_LEVEL)
    return logger


def set_app_log_level(new_level, app_prefix="caldanai"):
    for logger_name, logger_obj in logging.Logger.manager.loggerDict.items():
        if isinstance(logger_obj, logging.Logger):
            # Only update loggers that are part of this application
            if logger_name.startswith(app_prefix):
                logger_obj.setLevel(new_level)
