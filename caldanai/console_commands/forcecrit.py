"""Debug console command: force the next player attack roll to crit.

Monkey-patches AttackRoll so that the next time one is constructed, it
yields a natural 20 (and all its downstream crit effects). The patch
reverts itself after the forced roll is consumed.

Usage:
    forcecrit         — arm one crit for the next attack
    forcecrit on      — same as above
    forcecrit off     — disarm if currently armed
    forcecrit status  — show whether a forced crit is pending
"""

from typing import Any, List

from caldanai.console_commands import CommandPlugin
from caldanai.lib.bot.bot_state import BotState
from caldanai.lib.rpg.helpers import roll_data
from caldanai.logger import stdout


class ForceCritCommand(CommandPlugin):
    COMMAND = "forcecrit"
    ALIASES = ["crit"]

    _armed = False
    _original_init = None

    @classmethod
    def _arm(cls):
        if cls._armed:
            stdout("forcecrit: already armed.")
            return

        cls._original_init = roll_data.AttackRoll.__init__

        def patched_init(self, skill_bonus: int):
            # Call the real constructor first, then rewrite the roll
            cls._original_init(self, skill_bonus)
            self.rolls = (20,)
            self.result = 20 + skill_bonus
            self.isCritical = True
            self.isFumble = False
            # Self-disarm after one use
            roll_data.AttackRoll.__init__ = cls._original_init
            cls._armed = False
            cls._original_init = None
            stdout("forcecrit: consumed (next attack was crit).")

        roll_data.AttackRoll.__init__ = patched_init
        cls._armed = True
        stdout("forcecrit: armed. Next AttackRoll will be a natural 20.")

    @classmethod
    def _disarm(cls):
        if not cls._armed:
            stdout("forcecrit: not armed.")
            return
        roll_data.AttackRoll.__init__ = cls._original_init
        cls._original_init = None
        cls._armed = False
        stdout("forcecrit: disarmed.")

    @classmethod
    async def execute(cls, args: List[Any], state: BotState):
        sub = args[0].lower() if args else "on"
        if sub in ("on", "arm"):
            cls._arm()
        elif sub in ("off", "disarm"):
            cls._disarm()
        elif sub == "status":
            stdout(f"forcecrit: {'ARMED' if cls._armed else 'disarmed'}")
        else:
            stdout(f"forcecrit: unknown subcommand '{sub}'. Use on/off/status.")
