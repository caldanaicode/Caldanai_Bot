from abc import ABC
from typing import Dict

from Caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels


class BodyPart(ABC):
    def __init__(self, name: str, health_max: int, is_critical: bool = False, traits: Dict[DamageTypes, float] = None):
        self.name = name
        self.health_max = health_max
        self.health = health_max
        self.is_critical = is_critical
        self.traits = traits

    def get_injury_level(self):
        health_percent = self.health / self.health_max
        if 0.60 <= health_percent < 1.0:
            return InjuryLevels.MINOR

        if 0.30 <= health_percent < 0.60:
            return InjuryLevels.MODERATE

        if 0 < health_percent < 0.30:
            return InjuryLevels.SEVERE

        if health_percent <= 0:
            return InjuryLevels.USELESS

        return InjuryLevels.NONE

    def get_injury_string(self):
        level = self.get_injury_level()
        if level == InjuryLevels.MINOR:
            return f"{self.name} seems lightly battered."

        if level == InjuryLevels.MODERATE:
            return f"{self.name} shows signs of moderate damage."

        if level == InjuryLevels.SEVERE:
            return f"{self.name} appears severely wounded."

        if level == InjuryLevels.USELESS:
            return f"{self.name} looks to be utterly useless."

        return f"{self.name} is completely unscathed."

    def apply_damage(self, amount: int, dmg_type: DamageTypes):
        multiplier = 1
        if dmg_type and dmg_type in self.traits.keys():
            multiplier = self.traits[dmg_type]

        self.health = max(amount * multiplier, 0)
