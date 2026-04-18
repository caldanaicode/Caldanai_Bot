import asyncio
import logging
import signal
import traceback
import sys
from logging import Logger
from typing import Union

from discord import HTTPException

from caldanai import PluginManager
from caldanai.console_commands import CommandPlugin
from caldanai.lib.bot import Bot
from caldanai.lib.bot.bot_state import BotState
from caldanai.db import DB
from caldanai.logger import (
    MicrosecondFormatter, MongoHandler, get_logger, stdout
)

# Clear existing handlers on the root logger
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

_log = get_logger("caldanai")

stdout(f"Default system encoding: {sys.getdefaultencoding()}")
stdout(f"Standard I/O encoding: {sys.stdout.encoding}")


def setup_logging(lgr: Logger, level=None, propagate: bool = None):
    _log.info(f"Setting up logging for {lgr.name}...")

    if DB._mongoHandler is None:
        f = MicrosecondFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        ignore = (
            "Dispatching event socket_response",
            "Dispatching event socket_raw_receive",
            "For Shard ID None: WebSocket Event: {'t': None, 's': None, 'op': 11",
            "Shard ID None has successfully RESUMED session",
            "Dispatching event message",
            "Dispatching event typing",
            "Dispatching event socket_raw_send",
            "Keeping shard ID None websocket alive",
            "Shard ID None has successfully RESUMED session",
        )
        mHandler = MongoHandler(DB._mongoDB.logs_discord, ignore)
        mHandler.setFormatter(f)
        DB._mongoHandler = mHandler

    if level is not None:
        lgr.setLevel(level)

    lgr.addHandler(DB._mongoHandler)
    if propagate is not None:
        lgr.propagate = propagate

    _log.info("Logging setup complete.")


async def setup():
    _log.info("Setting up bot.")
    bot = Bot()
    await bot.setup()
    setup_logging(logging.getLogger("discord"), "INFO")
    return bot


async def start_bot(state: BotState):
    _log.info("Running bot.")
    bot = await setup()

    await state.put_bot(bot)

    while state.should_restart():
        try:
            await bot.start(bot.TOKEN, reconnect=True)
        except HTTPException:
            err = traceback.format_exc()
            _log.error(f"Error running bot. Retrying in 5 minutes: {err}")
            await asyncio.sleep(300)
        except Exception:
            err = traceback.format_exc()
            _log.error(f"Unexpected error: {err}")
            return
        finally:
            if not bot.is_closed():
                await bot.close()

        if state.should_restart():
            bot = await setup()
            await state.put_bot(bot)


async def cmd_loop(state: BotState):
    bot: Bot = await state.get_bot()
    CommandPlugin.load_plugins()
    while state.should_restart():
        cmd: str = await state.get_command()

        tokens = cmd.split(' ')
        cmd = tokens.pop(0).lower()
        handled = False

        for Command in PluginManager.LOADED_PLUGINS.get(CommandPlugin):
            if Command.has_alias(cmd):
                # A console command raising must not take down the
                # whole bot process. Log and continue; operator can
                # retry or fix the command.
                try:
                    await Command.execute(tokens, state)
                except Exception as e:
                    _log.error(
                        f"Console command `{cmd}` raised: {e}",
                        exc_info=True,
                    )
                    stdout(f"Command `{cmd}` failed: {e}")
                handled = True
                break

        if not handled:
            stdout(f"Unrecognized command '{cmd}'")

        state._command_queue.task_done()

        if bot.is_closed() and state.should_restart():
            bot = await state.get_bot()
            CommandPlugin.load_plugins()



async def input_loop(state: BotState):
    while state.should_restart():
        try:
            cmd = await asyncio.get_event_loop().run_in_executor(None, input)
        except EOFError:
            # Windows Ctrl+C closes stdin as a side-effect of
            # raising SIGINT. Our signal handler has already
            # enqueued the shutdown command on the command queue;
            # if we let the EOFError propagate, ``asyncio.gather``
            # in ``main`` sees an unhandled exception and cancels
            # ``cmd_task`` mid-``ShutdownCommand.execute``, which
            # kills the graceful shutdown before it can flush.
            # Exiting the input loop here lets ``gather`` wait on
            # the other tasks (bot + cmd) and ``cmd_task`` runs
            # the already-enqueued shutdown to completion.
            _log.debug("input_loop: stdin closed; exiting.")
            return
        await state.put_command(cmd)


def _install_shutdown_signals(state: BotState, loop: asyncio.AbstractEventLoop) -> None:
    """Route POSIX-style termination signals through the same
    graceful shutdown path as the ``shutdown`` console command.

    ``SIGINT`` (Ctrl+C), ``SIGTERM`` (``kill``, ``systemctl stop``,
    ``docker stop``), and ``SIGBREAK`` (Windows Ctrl+Break) all
    enqueue a ``"shutdown"`` command onto the state's command queue,
    which ``cmd_loop`` picks up and dispatches to
    ``ShutdownCommand.execute`` — so the Dispatcher drain / task
    cancel / DB flush / ``os._exit`` sequence fires identically
    regardless of trigger. Durability over responsiveness: Ctrl+C
    now takes ~1.5 s (bounded by the Dispatcher drain and final DB
    flush) instead of aborting instantly, but no DB writes are lost.

    Does NOT cover:
    - ``SIGKILL`` and Windows ``TerminateProcess`` — uncatchable
      by design. The OS yanks the process; Python never runs
      cleanup code. Nothing we can do.
    - Hosting-platform "stop" buttons vary by host. If the host
      sends SIGTERM first with a grace period, we get the
      graceful path; if it goes straight to SIGKILL-equivalent,
      we don't. The log line emitted on signal receipt surfaces
      which signal the host actually sends, which helps diagnose
      a given panel's shutdown behavior.
    """
    def _handler(signum, _frame):
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = f"signal {signum}"
        _log.info(f"Received {sig_name}; initiating graceful shutdown.")
        try:
            loop.call_soon_threadsafe(
                state._command_queue.put_nowait, "shutdown",
            )
        except RuntimeError:
            # Event loop already closed — shutdown is already in
            # flight, this signal is just a late echo. Nothing to
            # do; the process is on its way out.
            pass

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue  # Signal not defined on this platform.
        try:
            signal.signal(sig, _handler)
            _log.debug(f"Installed shutdown handler for {sig_name}")
        except (OSError, ValueError) as e:
            # Signal not settable in this context — e.g. some
            # platform/runtime combinations reject SIGTERM. Skip
            # quietly; the other signals still work.
            _log.debug(f"Couldn't install shutdown handler for {sig_name}: {e}")


async def main():
    setup_logging(_log)
    state = BotState()
    _install_shutdown_signals(state, asyncio.get_running_loop())
    bot_task = asyncio.create_task(start_bot(state))
    cmd_task = asyncio.create_task(cmd_loop(state))
    input_task = asyncio.create_task(input_loop(state))

    await asyncio.gather(bot_task, cmd_task, input_task)

    _log.handlers.clear()
    _log.info("Closing DB connection.")
    DB.close_db_connection()


if __name__ == "__main__":
    asyncio.run(main())
