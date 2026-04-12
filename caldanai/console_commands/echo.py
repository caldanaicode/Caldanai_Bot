from typing import Any, List

from caldanai.console_commands import CommandPlugin
from caldanai.lib.bot.bot_state import BotState
from caldanai.logger import stdout


class EchoCommand(CommandPlugin):
    """
    Echoes the given message back to the console, without logging it. This can be useful for ensuring the bot is still responsive.

    Usage:
        `echo <message>`

    Example:
        `echo This is the song that nevers ends...`
    """

    COMMAND = "echo"
    ALIASES = []

    @staticmethod
    async def execute(args: List[Any], state: BotState):
        if args:
            msg = " ".join(args)
            stdout(f"Echoing: {msg}")
