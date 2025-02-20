from typing import List

from Caldanai.consolecommands import CommandPlugin
from Caldanai.lib.bot.BotState import BotState
from Caldanai.Logger import stdout


class LoadCommand(CommandPlugin):
    """
    Loads (or reloads) plugins in the environment without forcing a restart.

    Usage:
        `load commands` - Refreshes the console command plugins from the directory.
    """

    COMMAND = "load"
    ALIASES = []

    @staticmethod
    def reload_commands():
        stdout(f"Reloading console commands")
        return CommandPlugin.load_commands()

    @staticmethod
    async def execute(args: List[str], state: BotState):
        subcommands = {"commands": LoadCommand.reload_commands}
        if args and (subcmd := subcommands.get(args.pop(0).lower())):
            subcmd()
        else:
            stdout("No such subcommand or subcommand not provided")
