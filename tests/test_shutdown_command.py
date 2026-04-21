"""Tests for the graceful-shutdown sequencing.

The shutdown command is a cross-cutting coordinator: it touches the
Dispatcher, per-game daemons, the DB batch-write task, the DB
watchdog, and the process itself. These tests pin the ordering
contract because getting the order wrong silently loses player
state or reintroduces the hang we're fixing.

Actual process exit is mocked — the tests observe the call sequence
instead of letting ``os._exit`` take the test runner down.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.console_commands.shutdown import ShutdownCommand


@pytest.fixture
def mock_state():
    state = MagicMock()
    state.get_bot = AsyncMock()
    state.set_shutdown = MagicMock()
    return state


@pytest.fixture
def mock_bot():
    bot = MagicMock()
    bot.is_closed.return_value = False
    bot.close = AsyncMock()
    bot.games = {}
    return bot


@pytest.fixture
def dispatcher_patch():
    """Patch the Dispatcher class globals + the module-level
    ``send`` tasks.Loop in ``caldanai.dispatcher``. The two are
    distinct: ``Dispatcher`` is the message-queue gateway,
    ``send`` is the per-second tick that ships queued messages
    out — they live in the same module but at different scopes,
    and shutdown touches both. Returns the Dispatcher class
    mock; the send-task mock is reachable via the imported
    dispatcher module the shutdown command goes through."""
    with patch("caldanai.console_commands.shutdown.Dispatcher") as D, \
         patch("caldanai.dispatcher.send") as send:
        D.queue = MagicMock()
        D.queue.empty.return_value = True
        D.queue.qsize.return_value = 0
        D.flush = False
        send.is_running.return_value = True
        send.cancel = MagicMock()
        inner = MagicMock()
        inner.done.return_value = True
        send._task = inner
        # Stash the send mock on D for tests that want to
        # observe its cancellation directly.
        D.send = send
        yield D


@pytest.fixture
def db_patch():
    """Patch the DB module's task loops and flush_all so tests can
    assert the shutdown command drives them in the right order.

    Post-2026-04-21 loop collapse: only ``watchdog`` remains on DB —
    ``batch_write`` was merged into ``save_game_data`` (patched via
    ``save_patch``)."""
    with patch("caldanai.console_commands.shutdown.DB") as DB:
        # ``watchdog`` is a ``tasks.Loop`` instance; replace with a
        # mock carrying the subset of the Loop API the shutdown
        # command actually uses.
        loop = MagicMock()
        loop.is_running.return_value = True
        loop.cancel = MagicMock()
        inner = MagicMock()
        inner.done.return_value = True
        loop._task = inner
        DB.watchdog = loop
        DB.flush_all = MagicMock()
        DB._mongoClient = MagicMock()
        yield DB


@pytest.fixture
def save_patch():
    """Patch both ``save_all_now`` and ``save_game_data`` on the
    utils module — shutdown imports both."""
    with patch("caldanai.lib.rpg.helpers.utils.save_all_now") as save_now, \
         patch("caldanai.lib.rpg.helpers.utils.save_game_data") as save_task:
        save_task.is_running.return_value = True
        save_task.cancel = MagicMock()
        inner = MagicMock()
        inner.done.return_value = True
        save_task._task = inner
        yield save_now, save_task


@pytest.fixture
def os_exit_patch():
    """Prevent os._exit from actually exiting the test process."""
    with patch("caldanai.console_commands.shutdown.os._exit") as e:
        yield e


# ---------------------------------------------------------------------------
# Ordering / contract
# ---------------------------------------------------------------------------


class TestShutdownOrder:
    @pytest.mark.asyncio
    async def test_full_sequence_runs_in_order(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """Full-sequence order contract (post-2026-04-21 loop collapse,
        where ``batch_write`` was merged into ``save_game_data``):

        1. Dispatcher.flush flipped to True
        2. Per-game daemons + clock ticks stopped
        3. state.set_shutdown() — arms main.start_bot's exit check
        4. bot.close() — no new commands can enter
        5. watchdog cancelled (so it can't restart save_game_data)
        6. save_game_data cancelled
        7. save_all_now() — final enqueue
        8. DB.flush_all() — synchronous drain
        9. Mongo client closed
        10. os._exit(0)

        The critical invariants this encodes:
        - bot.close BEFORE stopping save_game_data, so in-flight
          command saves still make it through the flush.
        - watchdog dies BEFORE save_game_data, so it can't restart
          the stopped loop mid-shutdown.
        - save_all_now + flush_all atomic (no await between).
        """
        mock_state.get_bot.return_value = mock_bot
        save_now, save_task = save_patch

        calls = []

        def record(name):
            return lambda *a, **kw: calls.append(name)

        # AsyncMock side_effect can be a plain function; AsyncMock
        # just calls it (no coroutine wrapping needed) and awaits
        # the returned value if it's awaitable. A lambda that
        # returns None is fine — AsyncMock handles the async
        # resolution.
        mock_bot.close.side_effect = record("bot.close")
        dispatcher_patch.send.cancel.side_effect = record("dispatcher.send.cancel")
        db_patch.watchdog.cancel.side_effect = record("watchdog.cancel")
        save_task.cancel.side_effect = record("save_game_data.cancel")
        save_now.side_effect = record("save_all_now")
        db_patch.flush_all.side_effect = record("flush_all")
        mock_state.set_shutdown.side_effect = record("set_shutdown")
        db_patch._mongoClient.close.side_effect = record("mongo_close")
        os_exit_patch.side_effect = record("os._exit")

        await ShutdownCommand.execute([], mock_state)

        def assert_before(a, b):
            assert a in calls and b in calls, f"{a!r} or {b!r} not in {calls}"
            assert calls.index(a) < calls.index(b), (
                f"expected {a!r} before {b!r}, got order {calls}"
            )

        # Dispatcher.send.cancel must happen after the drain
        # but before bot.close — otherwise its per-second tick
        # fires against a half-closed discord.py session and
        # raises a ClientException that bubbles to
        # discord.ext.tasks's catch-all (benign but noisy).
        assert_before("dispatcher.send.cancel", "bot.close")
        # set_shutdown must precede bot.close — otherwise
        # ``main.start_bot``'s ``while state.should_restart()``
        # loop sees the bot close, its ``bot.start`` return, and
        # stands up a *new* bot mid-shutdown (regression observed
        # in playtest 2026-04-18).
        assert_before("set_shutdown", "bot.close")
        assert_before("bot.close", "watchdog.cancel")
        assert_before("bot.close", "save_game_data.cancel")
        assert_before("watchdog.cancel", "save_game_data.cancel")
        assert_before("save_game_data.cancel", "save_all_now")
        assert_before("save_all_now", "flush_all")
        assert_before("flush_all", "mongo_close")
        assert_before("mongo_close", "os._exit")
        os_exit_patch.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_save_and_flush_are_not_separated_by_await(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """save_all_now and flush_all must be atomic on the single-
        threaded event loop — no ``await`` between them — so nothing
        can interleave and enqueue new ops that never get drained."""
        mock_state.get_bot.return_value = mock_bot
        save_now, _ = save_patch

        def fail_if_flushed_first(*a, **kw):
            db_patch.flush_all.assert_not_called()

        save_now.side_effect = fail_if_flushed_first

        await ShutdownCommand.execute([], mock_state)

        save_now.assert_called_once()
        db_patch.flush_all.assert_called_once()

    @pytest.mark.asyncio
    async def test_dispatcher_flush_flag_set_before_drain(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """``Dispatcher.flush = True`` must flip BEFORE the drain
        loop starts — otherwise incoming messages keep landing in
        the queue and the drain runs forever."""
        mock_state.get_bot.return_value = mock_bot

        observed_flush = []
        original_empty = dispatcher_patch.queue.empty
        def observe_empty():
            observed_flush.append(dispatcher_patch.flush)
            return original_empty()

        dispatcher_patch.queue.empty = observe_empty

        await ShutdownCommand.execute([], mock_state)

        assert observed_flush, "queue.empty was never polled"
        assert all(flag is True for flag in observed_flush)

    @pytest.mark.asyncio
    async def test_watchdog_stopped_before_save_game_data(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """Critical for correctness: if we stop ``save_game_data``
        before ``watchdog``, the watchdog's next tick can restart
        ``save_game_data`` while we're mid-flush, letting it race the
        synchronous drain. Order must be watchdog → save_game_data.

        Post-2026-04-21 loop collapse: the old ``batch_write`` task
        loop was merged into ``save_game_data``, so the ordering
        invariant applies to the merged loop."""
        mock_state.get_bot.return_value = mock_bot
        _save_now, save_task = save_patch

        calls = []
        db_patch.watchdog.cancel.side_effect = lambda: calls.append("watchdog")
        save_task.cancel.side_effect = lambda: calls.append("save_game_data")

        await ShutdownCommand.execute([], mock_state)

        assert "watchdog" in calls and "save_game_data" in calls
        assert calls.index("watchdog") < calls.index("save_game_data")


# ---------------------------------------------------------------------------
# Task-cancel semantics
# ---------------------------------------------------------------------------


class TestStopTaskLoop:
    @pytest.mark.asyncio
    async def test_awaits_inner_task_after_cancel(self):
        """cancel() alone is non-blocking — shutdown then drains
        synchronously, which races an in-flight iteration. The
        helper must await the task's completion so any iteration
        that was running finishes before we proceed."""
        async def pretend_tick():
            await asyncio.sleep(10)

        inner = asyncio.create_task(pretend_tick())
        # Give the task a chance to start before we cancel.
        await asyncio.sleep(0)

        task_loop = MagicMock()
        task_loop.is_running.return_value = True
        task_loop._task = inner

        def cancel():
            inner.cancel()

        task_loop.cancel = cancel

        await ShutdownCommand._stop_task_loop(task_loop, "pretend")

        # After ``_stop_task_loop`` returns, the inner task has
        # finished — no race window where a concurrent tick body
        # could enqueue between our flush's enqueue phase and its
        # drain phase.
        assert inner.done()

    @pytest.mark.asyncio
    async def test_timeout_on_wedged_task_does_not_hang(self):
        """If a task doesn't respond to cancel within the timeout,
        we log and move on — shutdown can't block forever. Guard
        against a misbehaving coroutine wedging the entire
        shutdown."""
        async def stubborn():
            with contextlib_suppress():
                while True:
                    try:
                        await asyncio.sleep(100)
                    except asyncio.CancelledError:
                        # Swallow the cancel — this simulates a
                        # buggy task that ignores cancellation.
                        continue

        inner = asyncio.create_task(stubborn())
        task_loop = MagicMock()
        task_loop.is_running.return_value = True
        task_loop._task = inner
        task_loop.cancel = lambda: inner.cancel()

        with patch.object(
            ShutdownCommand, "_TASK_CANCEL_TIMEOUT_SECONDS", 0.1,
        ):
            # Must not raise, must return in bounded time.
            await ShutdownCommand._stop_task_loop(task_loop, "stubborn")

        inner.cancel()
        # Give the event loop a chance to tear down the stubborn task.
        await asyncio.sleep(0)

    @pytest.mark.asyncio
    async def test_none_task_loop_is_tolerated(self):
        """Early-startup shutdowns may see None for tasks that
        haven't been registered yet. Must not crash."""
        await ShutdownCommand._stop_task_loop(None, "missing")

    @pytest.mark.asyncio
    async def test_non_running_task_loop_is_tolerated(self):
        """A loop that was never started should be a no-op —
        no cancel call, no await, no error."""
        task_loop = MagicMock()
        task_loop.is_running.return_value = False
        task_loop.cancel = MagicMock()
        task_loop._task = None

        await ShutdownCommand._stop_task_loop(task_loop, "never_started")

        task_loop.cancel.assert_not_called()


# A small helper so the stubborn-task test is readable without a
# top-level import for one use.
def contextlib_suppress():
    import contextlib
    return contextlib.nullcontext()


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestShutdownFailureModes:
    @pytest.mark.asyncio
    async def test_bot_close_exception_does_not_block_exit(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """If ``bot.close()`` raises, we still need to hit
        ``os._exit`` — the DB flush still needs to happen and
        leaving the process hanging is worse than logging the
        error."""
        mock_state.get_bot.return_value = mock_bot
        mock_bot.close.side_effect = RuntimeError("close failed")
        save_now, _ = save_patch

        await ShutdownCommand.execute([], mock_state)

        save_now.assert_called_once()
        db_patch.flush_all.assert_called_once()
        os_exit_patch.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_mongo_client_close_exception_does_not_block_exit(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        mock_state.get_bot.return_value = mock_bot
        db_patch._mongoClient.close.side_effect = RuntimeError("close failed")

        await ShutdownCommand.execute([], mock_state)

        os_exit_patch.assert_called_once_with(0)

    @pytest.mark.asyncio
    async def test_no_live_bot_still_exits_cleanly(
        self, mock_state, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """If ``state.get_bot()`` returns None (shutdown invoked
        before the bot finished standing up), we shouldn't crash —
        just set shutdown and exit."""
        mock_state.get_bot.return_value = None
        save_now, _ = save_patch

        await ShutdownCommand.execute([], mock_state)

        mock_state.set_shutdown.assert_called_once()
        os_exit_patch.assert_called_once_with(0)
        db_patch.flush_all.assert_not_called()
        save_now.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatcher_drain_timeout_still_flushes_db(
        self, mock_state, mock_bot, dispatcher_patch, db_patch,
        save_patch, os_exit_patch,
    ):
        """A stuck Dispatcher (queue that never empties) must not
        prevent the DB flush — the drain is bounded and shutdown
        continues with a warning."""
        mock_state.get_bot.return_value = mock_bot
        dispatcher_patch.queue.empty.return_value = False
        dispatcher_patch.queue.qsize.return_value = 5
        save_now, _ = save_patch

        with patch.object(
            ShutdownCommand, "_DISPATCHER_DRAIN_TIMEOUT_SECONDS", 0,
        ):
            await ShutdownCommand.execute([], mock_state)

        save_now.assert_called_once()
        db_patch.flush_all.assert_called_once()
        os_exit_patch.assert_called_once_with(0)


# ---------------------------------------------------------------------------
# Per-game routine teardown
# ---------------------------------------------------------------------------


class TestStopPerGameRoutines:
    @pytest.mark.asyncio
    async def test_stops_daemons_and_clocks(self):
        bot = MagicMock()
        game_a = MagicMock()
        game_a.weather = MagicMock()
        game_a.celestial = MagicMock()
        game_a.game_clock.tick.is_running.return_value = True
        game_b = MagicMock()
        game_b.weather = None
        game_b.celestial = None
        game_b.game_clock.tick.is_running.return_value = False
        bot.games = {111: game_a, 222: game_b}

        await ShutdownCommand._stop_per_game_routines(bot)

        game_a.weather.stop.assert_called_once()
        game_a.celestial.stop.assert_called_once()
        game_a.game_clock.tick.stop.assert_called_once()
        game_b.game_clock.tick.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_one_game_failure_does_not_skip_others(self):
        bot = MagicMock()
        bad = MagicMock()
        bad.weather = MagicMock()
        bad.weather.stop.side_effect = RuntimeError("stop failed")
        good = MagicMock()
        good.weather = MagicMock()
        good.celestial = MagicMock()
        good.game_clock.tick.is_running.return_value = True
        bot.games = {111: bad, 222: good}

        await ShutdownCommand._stop_per_game_routines(bot)

        good.weather.stop.assert_called_once()
        good.celestial.stop.assert_called_once()
