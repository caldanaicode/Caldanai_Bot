from random import choice

from caldanai.lib.rpg import get_random_direction
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Size)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import quadruped_tree


class Sheep(MonsterPlugin):
    BODY_TREE = quadruped_tree()

    # Per-hit narration: thick wool cushions slashes; piercing
    # finds the soft body underneath without resistance.
    HIT_NARRATIONS = {
        DamageTypes.SLASHING:    "The blade catches in @1a thick wool, opening a shallow line through the layered fleece.",
        DamageTypes.PIERCING:    "The point parts @1a wool cleanly and sinks deep into the body beneath.",
        DamageTypes.BLUDGEONING: "The blow lands solid; even fleece can only soften so much.",
    }

    def __init__(self):
        super().__init__(
            name="sheep",
            atk="1d4",
            defense="1d6",
            dodge="1d6",
            health_max="3d6"
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

        self.escape = f"@1dc {choice('slips|bounds|wanders'.split('|'))} away merrily, not a care in the world."
        self.death = choice(
            [
                "@1dc gurgles out a final, sad, bleating cry, and goes still.",
                "Eyes rolling wildly in terror and pain, @1d stumbles and falls to the ground motionless.",
                "A final wheezing breath escapes slowly, as @1d collapses to the ground in a twitching heap.",
            ]
        )

        self.traits[DamageTypes.BLUDGEONING] = 1.25
        self.traits[DamageTypes.PIERCING] = 1.50
        self.traits[DamageTypes.SLASHING] = 0.75

        self.loot["stick"] = 0.5
        self.loot["wool"] = 0.5
        self.loot["leather"] = 0.25

        self.size = Size.SMALL
        self._scale_part_hp()

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                f"@1dc glances at @2, but apparently decides to allow the {invocation}.",
                f"A soft bleat escapes @1d as @2 {invocation}s @1o.",
                f"@1dc wuffles happily and leans into @2's {invocation}.",
            ]
        )
