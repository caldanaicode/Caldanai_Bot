from typing import List
from caldanai import PluginManager

from os import sep


class CommandPlugin:
    """
    The base class for all console command plugins. This class should not be
    used directly, and is meant only to provide a contract, and some basic
    functionality shared by all console commands.
    """
    COMMAND: str = None
    ALIASES: List[str] = []
    BASEPATH: str = f'caldanai{sep}console_commands'

    @classmethod
    async def execute(cls, *args, **kwargs):
        raise NotImplementedError

    @classmethod
    def has_alias(cls, cmd: str):
        return cmd.lower() in (cls.COMMAND, *cls.ALIASES)

    @staticmethod
    def load_plugins():
        PluginManager.load(CommandPlugin, CommandPlugin.BASEPATH)
