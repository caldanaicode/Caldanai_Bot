import asyncio
from typing import Any, List

from Caldanai.consolecommands import CommandPlugin
from Caldanai.Dispatcher import Dispatcher
from Caldanai.lib.bot.BotState import BotState
from Caldanai.Logger import get_logger


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

    @staticmethod
    async def execute(args: List[Any], state: BotState):
        msg = "Shutting down"
        if args:
            msg += f" with message: {' '.join(args)}"
        bot = await state.get_bot()
        if bot:
            _log.info(msg)
            for game in bot.games.values():
                Dispatcher.add(game.channel, msg)
            Dispatcher.flush = True
            while not Dispatcher.queue.empty():
                await asyncio.sleep(1)
            _log.info("Dispatcher is flushed. Completing shutdown.")

            state.set_shutdown()
