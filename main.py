import asyncio
import logging
import traceback
import sys
from logging import Logger
from typing import Union

from discord import HTTPException

from Caldanai import PluginManager
from Caldanai.consolecommands import CommandPlugin
from Caldanai.lib.bot import Bot
from Caldanai.lib.bot.BotState import BotState
from Caldanai.db import DB
from Caldanai.Logger import (
    MicrosecondFormatter, MongoHandler, get_logger, stdout
)

# Clear existing handlers on the root logger
for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

_log = get_logger("Caldanai")

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
                await Command.execute(tokens, state)
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
        cmd = await asyncio.get_event_loop().run_in_executor(None, input)
        await state.put_command(cmd)


async def main():
    setup_logging(_log)
    state = BotState()
    bot_task = asyncio.create_task(start_bot(state))
    cmd_task = asyncio.create_task(cmd_loop(state))
    input_task = asyncio.create_task(input_loop(state))

    await asyncio.gather(bot_task, cmd_task, input_task)

    _log.handlers.clear()
    _log.info("Closing DB connection.")
    DB.close_db_connection()


if __name__ == "__main__":
    asyncio.run(main())
