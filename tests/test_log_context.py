"""Tests for ``caldanai.log_context`` + the ``MongoHandler``
channel-id surfacing behavior.

The channel context is a ``ContextVar`` set at two entry points
(``GameClock.tick`` and ``Bot.invoke``) and read at log-emit time
by :class:`caldanai.logger.MongoHandler`. These tests pin:

- The contextvar defaults to ``None`` outside any scope.
- ``channel_log_context`` sets and resets cleanly (token-based
  so nested scopes don't corrupt the outer value).
- The MongoHandler surfaces ``(channel_id)`` in stdout and as a
  field on the Mongo log entry when the var is set.
- Absent the var, the handler's output is byte-identical to the
  pre-refactor shape so Dispatcher / main / db logs don't
  accidentally gain a mysterious suffix.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from caldanai.log_context import channel_id_var, channel_log_context


# ---------------------------------------------------------------------------
# Contextvar semantics
# ---------------------------------------------------------------------------


class TestChannelLogContext:
    def test_default_is_none(self):
        """Outside any ``channel_log_context`` the var reads as
        ``None`` — non-game code paths see no channel context."""
        assert channel_id_var.get() is None

    def test_scope_sets_value(self):
        with channel_log_context(12345):
            assert channel_id_var.get() == 12345

    def test_scope_resets_on_exit(self):
        with channel_log_context(12345):
            pass
        assert channel_id_var.get() is None

    def test_nested_scope_restores_outer(self):
        """Token-based reset restores the outer value, not the
        global default. A game-scoped coroutine that calls into
        another game-scoped helper keeps the outer context visible
        after the inner block exits."""
        with channel_log_context(1000):
            with channel_log_context(2000):
                assert channel_id_var.get() == 2000
            assert channel_id_var.get() == 1000
        assert channel_id_var.get() is None

    def test_exception_still_resets(self):
        """``with`` contract — the finally-branch reset fires even
        when the block body raises, so a crash inside a game-scoped
        routine doesn't leak context into the next task."""
        with pytest.raises(RuntimeError):
            with channel_log_context(9999):
                raise RuntimeError("boom")
        assert channel_id_var.get() is None

    def test_explicit_none_scopes_out(self):
        """Passing ``None`` into the context manager explicitly
        scopes out of the outer game context — useful when a
        game-scoped coroutine needs to invoke a cross-game helper
        whose logs shouldn't be misattributed."""
        with channel_log_context(1000):
            with channel_log_context(None):
                assert channel_id_var.get() is None
            # Outer still restored.
            assert channel_id_var.get() == 1000


# ---------------------------------------------------------------------------
# MongoHandler formatting
# ---------------------------------------------------------------------------


def _make_record(message: str = "hello") -> logging.LogRecord:
    record = logging.LogRecord(
        name="caldanai.lib.rpg.time",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    return record


def _make_handler():
    """Build a MongoHandler with a fake collection + a stubbed
    queue so emit() doesn't try to talk to real infrastructure."""
    from caldanai.logger import MongoHandler
    collection = MagicMock()
    handler = MongoHandler(collection)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    return handler


class TestMongoHandlerChannelContext:
    def test_queue_entry_has_channel_id_when_set(self):
        handler = _make_handler()
        record = _make_record()
        with patch("caldanai.logger.stdout"):
            with channel_log_context(42):
                handler.emit(record)
        # Pull the most recently queued entry.
        queued = handler.queue.get_all()
        assert len(queued) == 1
        assert queued[0]["channel_id"] == 42

    def test_queue_entry_omits_channel_id_when_unset(self):
        handler = _make_handler()
        record = _make_record()
        with patch("caldanai.logger.stdout"):
            handler.emit(record)
        queued = handler.queue.get_all()
        assert len(queued) == 1
        assert "channel_id" not in queued[0]

    def test_stdout_bracket_carries_channel_id_when_set(self):
        handler = _make_handler()
        record = _make_record(message="routine fired")
        with patch("caldanai.logger.stdout") as mock_stdout:
            with channel_log_context(987654321):
                handler.emit(record)
        # Find the rendered line in the mock call args.
        rendered = mock_stdout.call_args.args[0]
        assert "[caldanai.lib.rpg.time (987654321)]" in rendered

    def test_stdout_bracket_unchanged_when_unset(self):
        """Legacy bracket shape preserved for non-game logs."""
        handler = _make_handler()
        record = _make_record(message="dispatcher pumped")
        with patch("caldanai.logger.stdout") as mock_stdout:
            handler.emit(record)
        rendered = mock_stdout.call_args.args[0]
        assert "[caldanai.lib.rpg.time]" in rendered
        # No stray parens in the bracket.
        assert "(None)" not in rendered
