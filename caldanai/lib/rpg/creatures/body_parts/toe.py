"""Toe body part plugin.

A small, low-HP extremity. Toes are natural melee targets on large
creatures (stomp a giant's toes!) but hard to hit at range. Generic
across all creatures — no creature-specific behavior.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class ToePlugin(BodyPartPlugin):
    name = "toe"
    health_max = 1
    is_critical = False
    exposure = {
        Reach.MELEE:  0.3,
        Reach.REACH:  0.2,
        Reach.THROWN: 0.1,
        Reach.RANGED: 0.1,
    }
    debuffs = {
        InjuryLevels.USELESS: {Stat.DODGE: -1},
    }
    # No get_stat_modifier override — uses the standard debuffs table.
