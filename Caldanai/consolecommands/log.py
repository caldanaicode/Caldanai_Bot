from typing import List
import os

from Caldanai.consolecommands import CommandPlugin
from Caldanai.lib.bot.BotState import BotState
from Caldanai.Logger import get_logger, set_app_log_level, stdout

_log = get_logger(__name__)


class LogCommand(CommandPlugin):
    """
    Test or configure logging levels.

    Send a log test: log <level> <msg>
        e.g. - `log info This is only a test`

    Check the current log level:
        e.g. - `log level`

    Set the logging level: log level <level>
        e.g. - `log level debug`
    """

    COMMAND = "log"
    ALIASES = []

    VALID_LEVELS = {"critical", "fatal", "error", "warn", "warning", "info", "debug"}

    @classmethod
    def level(cls, args: List[str] = []):
        if not args:
            stdout(f"Current log level is {os.getenv('LOG_LEVEL', 'INFO')}")
        elif (level := args.pop(0).lower()) in cls.VALID_LEVELS:
            os.environ["LOG_LEVEL"] = level.upper()
            set_app_log_level(os.getenv("LOG_LEVEL"))
            stdout(f"Logging level set to {os.getenv('LOG_LEVEL')}")

    @classmethod
    def log(cls, level: str, args: List[str]):
        _log.debug(f"Called {__name__}.log({level}, {args})")
        msg = " ".join(args)
        if method := getattr(_log, level, None):
            method(msg)
        else:
            stdout(f"Unrecognized log level '{level}'. Valid values: {LogCommand.VALID_LEVELS}")

    @staticmethod
    async def execute(args: List[str], state: BotState):
        _log.debug("Executing the Log command")
        subcommands = {"level": LogCommand.level, **{level: LogCommand.log for level in LogCommand.VALID_LEVELS}}

        if args and (subcommand := args.pop(0).lower()) in subcommands:
            if subcommand in LogCommand.VALID_LEVELS:
                subcommands[subcommand](subcommand, args)
            else:
                subcommands[subcommand](args)
        _log.debug("Log command completed")
