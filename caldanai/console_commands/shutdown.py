import asyncio
import contextlib
import os
from typing import Any, List, Optional

from caldanai.console_commands import CommandPlugin
from caldanai.db import DB
from caldanai.dispatcher import Dispatcher
from caldanai.lib.bot.bot_state import BotState
from caldanai.logger import get_logger


_log = get_logger(__name__)


class ShutdownCommand(CommandPlugin):
    """
    Shuts down the server after sending an optional message to each guild's game channel.

    Usage:
        `shutdown [message]` - Sends message to each guild, if present, before shutting down the bot's loops.

    Example:
        `shutdown Expect 30 minutes of downtime for maintenance`
    """

    COMMAND = "shutdown"
    ALIASES = ["exit", "stop", "terminate"]

    # How long to wait for the Dispatcher queue to drain before
    # giving up and proceeding with DB flush anyway. Dispatcher
    # sends ≤ 10 messages per second (see dispatcher.py); 30 s is
    # enough for ~300 queued messages, which is more than any
    # realistic shutdown announcement produces.
    _DISPATCHER_DRAIN_TIMEOUT_SECONDS = 30

    # Upper bound on how long we wait for a cancelled task loop to
    # settle. Tasks that take longer than this to acknowledge
    # cancellation get left behind — os._exit will take them down.
    _TASK_CANCEL_TIMEOUT_SECONDS = 5

    @staticmethod
    async def execute(args: List[Any], state: BotState):
        msg = "Shutting down"
        if args:
            msg += f" with message: {' '.join(args)}"
        bot = await state.get_bot()
        if not bot:
            _log.warning("Shutdown invoked with no live bot — hard-exiting.")
            state.set_shutdown()
            os._exit(0)
            return

        _log.info(msg)

        # 1. Announce shutdown to every active game channel, then
        #    drain the Dispatcher so those announcements actually
        #    reach Discord before we start tearing anything down.
        #    Cancel the per-second ``Dispatcher.send`` task once
        #    the queue is empty — otherwise it ticks during the
        #    later ``bot.close()`` window with a half-closed
        #    discord.py session and raises a ``ClientException``
        #    that bubbles to ``discord.ext.tasks``'s catch-all
        #    (benign, but noisy in the shutdown log).
        for game in bot.games.values():
            Dispatcher.add(game.channel, msg)
        Dispatcher.flush = True
        await ShutdownCommand._drain_dispatcher()
        # ``send`` is a module-level ``tasks.Loop`` in
        # ``caldanai.dispatcher`` (not an attribute on the
        # ``Dispatcher`` class) — local import gets the right
        # reference. Without this, the cancel target is None
        # and the per-second send tick fires against a
        # half-closed discord.py session a moment later, raising
        # a ``ClientException`` that bubbles to
        # ``discord.ext.tasks``'s catch-all (benign but noisy).
        from caldanai import dispatcher as _dispatcher_module
        await ShutdownCommand._stop_task_loop(
            getattr(_dispatcher_module, "send", None), "dispatcher.send",
        )

        # 2. Stop the per-game write-generators (clock ticks +
        #    ambience daemons) so no automated tick can mutate
        #    player/game state after this point. We deliberately
        #    leave ``save_game_data`` running for one more beat
        #    until step 5 — its job is to flush dirty state that
        #    existing tick bodies may have just produced.
        await ShutdownCommand._stop_per_game_routines(bot)

        # 3. Signal shutdown to ``main()``'s outer loops BEFORE
        #    closing the bot. ``main.start_bot`` is structured as
        #    ``while state.should_restart(): await bot.start(...)``
        #    with a ``setup()`` spin-up between iterations, so if
        #    we close the bot while ``should_restart()`` is still
        #    True, ``start_bot`` sees ``bot.start`` return, falls
        #    through to ``finally`` / the next iteration, and
        #    stands up a *new* bot mid-shutdown (observed in
        #    playtest 2026-04-18). Flipping the shutdown flag
        #    first makes the while-loop check exit cleanly the
        #    moment ``bot.start`` unblocks.
        state.set_shutdown()

        # 4. Close discord.py cleanly. Any in-flight command
        #    coroutines complete (their ``game.save()`` calls land
        #    in ``DB._queues``) before the websocket closes.
        #    Must happen BEFORE we stop ``batch_write`` —
        #    otherwise a long-running command racing the shutdown
        #    could still enqueue writes after our final flush.
        try:
            if not bot.is_closed():
                await bot.close()
        except Exception:
            _log.error("bot.close() raised during shutdown.", exc_info=True)

        # 5. Now that no new writes can enter the queues, cancel
        #    both the watchdog (which would otherwise restart
        #    ``batch_write`` on its next 5-minute tick) and
        #    ``batch_write`` itself. Cancel + await rather than
        #    just ``stop()`` so any in-flight iteration is
        #    guaranteed to be done before we proceed. ``stop()``
        #    is cooperative and leaves a mid-execution tick still
        #    running, which could enqueue or drain concurrently
        #    with our synchronous flush.
        await ShutdownCommand._stop_task_loop(
            _get_task(DB, "watchdog"), "watchdog",
        )
        # save_game_data is only used by the loop — it delegates
        # to save_all_now which we're about to call directly.
        from caldanai.lib.rpg.helpers import utils as _utils
        await ShutdownCommand._stop_task_loop(
            _get_task(_utils, "save_game_data"), "save_game_data",
        )
        await ShutdownCommand._stop_task_loop(
            _get_task(DB, "batch_write"), "batch_write",
        )

        # 6. One-shot final enqueue — mirror save_game_data once
        #    so every game and every dirty player lands in the
        #    queues before we drain them.
        _utils.save_all_now()

        # 7. Synchronous drain. Steps 6 and 7 are pure synchronous
        #    Python with no ``await`` between them, so nothing can
        #    interleave on the single-threaded event loop — the
        #    enqueue-then-flush pair is atomic by construction.
        DB.flush_all()
        _log.info("DB queues flushed.")

        # 8. Close the Mongo client so sockets get released
        #    cleanly. If it raises, log and continue — the flush
        #    already happened, and leaving the process hanging is
        #    worse than a noisy close.
        try:
            DB._mongoClient.close()
        except Exception:
            _log.error("Mongo client close raised during shutdown.", exc_info=True)

        # 9. Hard-exit. The stdin input thread (main.py's
        #    ``input_loop``) is blocked in ``input()`` inside a
        #    non-daemon executor thread and holds the interpreter
        #    open even after the event loop wants to exit.
        #    Everything that needed to persist is already written,
        #    every outbound message already sent, and the Discord
        #    socket already closed — there is no clean work left
        #    to do, so a hard exit is the right coda here.
        _log.info("Shutdown complete — exiting.")
        os._exit(0)

    @staticmethod
    async def _drain_dispatcher() -> None:
        """Wait for the Dispatcher queue to empty, bounded by
        ``_DISPATCHER_DRAIN_TIMEOUT_SECONDS``. Dispatcher is
        configured to stop accepting new messages once
        ``Dispatcher.flush`` is True, and its send task drains at
        ≤ 10 msg/s, so a bounded wait is enough — we don't want a
        stuck send coroutine to block shutdown forever."""
        deadline = asyncio.get_event_loop().time() + ShutdownCommand._DISPATCHER_DRAIN_TIMEOUT_SECONDS
        while not Dispatcher.queue.empty():
            if asyncio.get_event_loop().time() >= deadline:
                _log.warning(
                    "Dispatcher drain timed out with "
                    f"{Dispatcher.queue.qsize()} message(s) still queued; "
                    "continuing shutdown."
                )
                return
            await asyncio.sleep(1)
        _log.info("Dispatcher is flushed.")

    @staticmethod
    async def _stop_per_game_routines(bot) -> None:
        """Stop every per-game clock tick and ambience daemon so
        automated ticks can't enqueue new writes or emit new
        narration during the final flush phase.

        One game failing to stop its routines must not skip the
        others — wrap each game individually.
        """
        games = list(bot.games.values())
        _log.info(f"Stopping per-game routines for {len(games)} game(s).")
        for game in games:
            try:
                if getattr(game, "weather", None) is not None:
                    game.weather.stop()
                if getattr(game, "celestial", None) is not None:
                    game.celestial.stop()
                if game.game_clock.tick.is_running():
                    game.game_clock.tick.stop()
            except Exception:
                _log.error(
                    f"Failed to stop routines for game on "
                    f"channel {getattr(game, 'channel_id', '?')} during shutdown.",
                    exc_info=True,
                )

    @staticmethod
    async def _stop_task_loop(task_loop, label: str) -> None:
        """Cancel a ``discord.ext.tasks.Loop`` and await its
        underlying asyncio task so any in-flight iteration is done
        before we return. ``.stop()`` alone is cooperative and
        leaves a mid-execution tick running — on the shutdown path
        that would race the synchronous drain. Bounded by
        ``_TASK_CANCEL_TIMEOUT_SECONDS`` so a wedged task can't
        block shutdown forever.

        Accepts ``None`` for the task_loop so callers don't have to
        precondition — early-startup shutdowns may find some loops
        unregistered.
        """
        if task_loop is None:
            return
        try:
            if task_loop.is_running():
                task_loop.cancel()
        except Exception:
            _log.error(f"{label}.cancel() raised during shutdown.", exc_info=True)
            return

        inner_task: Optional[asyncio.Task] = getattr(task_loop, "_task", None)
        if inner_task is None or inner_task.done():
            _log.debug(f"{label} task already done")
            return
        with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError, Exception):
            await asyncio.wait_for(
                inner_task, timeout=ShutdownCommand._TASK_CANCEL_TIMEOUT_SECONDS,
            )
        # INFO so LIVE logs (which usually run at INFO) show the
        # shutdown sequence beat-by-beat. Knowing which task loops
        # stopped when is essential for diagnosing a hang; leaving
        # this at DEBUG silently elides the whole middle of the
        # shutdown timeline in production.
        _log.info(f"{label} task stopped")


def _get_task(module_or_cls, name: str):
    """Safely look up a ``tasks.Loop`` attribute by name. Returns
    ``None`` when the attribute is missing — shutdown must tolerate
    early/partial initialization states where not every loop has
    been registered yet."""
    return getattr(module_or_cls, name, None)
