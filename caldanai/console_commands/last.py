from typing import Any, List

from caldanai.console_commands import CommandPlugin
from caldanai.lib.bot.bot_state import BotState
from caldanai.logger import stdout


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
