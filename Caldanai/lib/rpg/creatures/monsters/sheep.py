from random import choice

from Caldanai.lib.rpg import get_random_direction
from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from Caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes)
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.bodypart import BodyPart


class Sheep(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="sheep",
            atk="1d4",
            defense="1d6",
            dodge="1d6",
            health_max="2d4"
        )

        self.time_partition = TimePartitions.DIURNAL
        self.image = None
        self.aggression = AggressionLevels.PASSIVE
        self.arrival = (
            f"A fluffy mass of fur {choice('saunters|ambles|prances|skitters|tiptoes|wanders'.split('|'))} "
            f"in from the {get_random_direction()}."
        )

        self.flavor = choice(
            [
                "Just a cuddly @1, searching the lonely fields for hugs.",
                '"Ple-e-e-e-ease don\'t kill me-e-e-e-e."',
                "A sleepy looking @1, seeking naught but the warmth of @1a barn.",
            ]
        )

        self.escape = f"The @1 {choice('slips|bounds|wanders'.split('|'))} away merrily, not a care in the world."
        self.death = choice(
            [
                "The @1 gurgles out a final, sad, bleating cry, and goes still.",
                "Eyes rolling wildly in terror and pain, the @1 stumbles and falls to the ground motionless.",
                "A final wheezing breath escapes slowly, as the @1 collapses to the ground in a twitching heap.",
            ]
        )

        self.traits[DamageTypes.BLUDGEONING] = 1.25
        self.traits[DamageTypes.PIERCING] = 1.50
        self.traits[DamageTypes.SLASHING] = 0.75

        self.loot["stick"] = 0.5
        self.loot["wool"] = 0.5
        self.loot["leather"] = 0.25

        self.body_parts = BodyPart.quadruped()

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                f"The @1 glances at @2, but apparently decides to allow the {invocation}.",
                f"A soft bleat escapes the @1 as @2 {invocation}s @1o.",
                f"The @1 wuffles happily and leans into @2's {invocation}.",
            ]
        )
