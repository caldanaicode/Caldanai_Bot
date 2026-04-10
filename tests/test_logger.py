"""Tests for Caldanai.Logger."""

import logging
from unittest.mock import MagicMock, patch

from Caldanai.DoubleBuffer import DoubleBuffer


# We need to import carefully since Logger imports environment
with patch("Caldanai.environment.DB_CONNECTION", "mongodb://localhost:27017"), \
     patch("Caldanai.environment.LOG_LEVEL", "DEBUG"), \
     patch("Caldanai.environment.STAGE", "TEST"):
    from Caldanai.Logger import MongoHandler, get_logger, set_app_log_level, MicrosecondFormatter


class TestMongoHandler:
    def _make_handler(self, ignored=()):
        collection = MagicMock()
        handler = MongoHandler(collection, ignored=ignored)
        # The format string must include %(asctime)s so that Formatter.format()
        # populates record.asctime (via usesTime() check).
        handler.setFormatter(MicrosecondFormatter(fmt="%(asctime)s %(levelname)s %(name)s %(message)s"))
        return handler

    def test_emit_queues_entry(self):
        handler = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello world", args=(), exc_info=None,
        )
        with patch("Caldanai.Logger.stdout"):
            handler.emit(record)
        items = handler.queue.get_all()
        assert len(items) == 1
        assert items[0]["message"] == "hello world"
        assert items[0]["level"] == "INFO"
        assert items[0]["name"] == "test"

    def test_emit_filters_ignored_messages(self):
        handler = self._make_handler(ignored=("IGNORE_THIS",))
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="IGNORE_THIS is filtered", args=(), exc_info=None,
        )
        with patch("Caldanai.Logger.stdout"):
            handler.emit(record)
        items = handler.queue.get_all()
        assert len(items) == 0

    def test_emit_does_not_filter_non_ignored(self):
        handler = self._make_handler(ignored=("IGNORE_THIS",))
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="This is fine", args=(), exc_info=None,
        )
        with patch("Caldanai.Logger.stdout"):
            handler.emit(record)
        items = handler.queue.get_all()
        assert len(items) == 1

    def test_emit_entry_has_asctime(self):
        handler = self._make_handler()
        record = logging.LogRecord(
            name="test", level=logging.WARNING, pathname="", lineno=0,
            msg="warn msg", args=(), exc_info=None,
        )
        with patch("Caldanai.Logger.stdout"):
            handler.emit(record)
        items = handler.queue.get_all()
        assert "asctime" in items[0]

    def test_empty_ignored_tuple(self):
        handler = self._make_handler(ignored=())
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="anything", args=(), exc_info=None,
        )
        with patch("Caldanai.Logger.stdout"):
            handler.emit(record)
        assert len(handler.queue.get_all()) == 1

    def test_none_ignored_defaults_to_empty_tuple(self):
        collection = MagicMock()
        handler = MongoHandler(collection, ignored=None)
        assert handler.ignored == ()


class TestGetLogger:
    def test_returns_named_logger(self):
        logger = get_logger("Caldanai.test_module")
        assert logger.name == "Caldanai.test_module"

    def test_caldanai_logger_has_level_set(self):
        logger = get_logger("Caldanai.something")
        # LOG_LEVEL is patched to "DEBUG" above
        assert logger.level == logging.DEBUG

    def test_non_caldanai_logger_not_forced(self):
        logger = get_logger("some.other.module")
        # Should not have been explicitly set to DEBUG by get_logger
        # (it inherits from root, which defaults to WARNING)
        assert logger.level != logging.DEBUG or logger.level == logging.WARNING

    def test_none_name(self):
        logger = get_logger(None)
        assert logger is logging.getLogger(None)


class TestSetAppLogLevel:
    def test_changes_caldanai_loggers(self):
        # Create a couple of Caldanai loggers
        log1 = logging.getLogger("Caldanai.module_a")
        log1.setLevel(logging.DEBUG)
        log2 = logging.getLogger("Caldanai.module_b")
        log2.setLevel(logging.DEBUG)

        set_app_log_level(logging.ERROR)

        assert log1.level == logging.ERROR
        assert log2.level == logging.ERROR

        # Cleanup: reset
        set_app_log_level(logging.DEBUG)

    def test_does_not_change_non_caldanai_loggers(self):
        other = logging.getLogger("discord.gateway")
        other.setLevel(logging.DEBUG)

        set_app_log_level(logging.CRITICAL, app_prefix="Caldanai")

        assert other.level == logging.DEBUG

        # Cleanup
        set_app_log_level(logging.DEBUG)
