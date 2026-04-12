from typing import Set
from caldanai import PluginManager

from caldanai.console_commands import CommandPlugin
from caldanai.logger import stdout


class HelpCommand(CommandPlugin):
    """
    Shows the docstrings for a command or alias, if provided. Otherwise, shows this docstring :)

    Usage:
        `help [command|alias]`

    Examples:
        `help` - Shows this message

        `help load` - Shows the docstring for the load command
    """

    COMMAND = "help"
    ALIASES = []

    @classmethod
    def get_loaded_plugins(cls) -> Set[CommandPlugin]:
        return {*PluginManager.LOADED_PLUGINS.get(CommandPlugin, {})}

    @classmethod
    def append_commands(cls) -> str:
        commands = ", ".join([c.COMMAND for c in cls.get_loaded_plugins()])
        return f'{cls.__doc__}\n	Available Commands:\n		{commands}'

    @classmethod
    async def execute(cls, *args, **kwargs):
        if args and (tokens := args[0]):
            cmd = tokens[0].lower()
            found = False
            for command in cls.get_loaded_plugins():
                if command.has_alias(cmd):
                    found = True
                    if command.__doc__:
                        stdout(command.__doc__, False)
                    else:
                        stdout(f"No help available for `{command.COMMAND} ({cmd})`, yet 😞  ")
                    break

            if not found:
                stdout(f"There is no command or alias for `{cmd}` 🤨  ")
        else:
            stdout(HelpCommand.append_commands(HelpCommand.__doc__), False)
