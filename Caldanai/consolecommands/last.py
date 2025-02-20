from typing import Any, List

from Caldanai.consolecommands import CommandPlugin
from Caldanai.lib.bot.BotState import BotState
from Caldanai.Logger import stdout


class LastCommand(CommandPlugin):
    """
    Retrieves the last command that trigger the bot's onCommand() function.

    Usage:
        `last`

    Example:
        `last`
    """

    COMMAND = "last"
    ALIASES = []

    @staticmethod
    async def execute(args: List[Any], state: BotState):
        bot = await state.get_bot()
        stdout(f"Last command: {bot.last_command}")
