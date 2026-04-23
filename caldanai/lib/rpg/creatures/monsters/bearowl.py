from random import choice

from caldanai.lib.rpg import get_random_direction
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Size)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import quadruped_winged_tree


class Bearowl(MonsterPlugin):
    BODY_TREE = quadruped_winged_tree()

    # Apex-predator bias: ~40% of attacks go for the head (killing
    # bite). Otherwise falls back to exposure-weighted random — even
    # a predator misreads prey sometimes.
    TARGET_PREFERENCES = {"head": 0.4}

    def __init__(self):
        super().__init__(
            name="bearowl",
            atk="2d7",
            defense="3d8",
            dodge="1d10",
            health_max="22d10"
        )

        self.time_partition = TimePartitions.NOCTURNAL | TimePartitions.CREPUSCULAR
        self.image = "owl128.png"
        self.aggression = AggressionLevels.VENGEFUL
        self.arrival = (
            "A genetically improbable creature "
            f"{choice('lurches|trudges|charges|walks|wanders'.split('|'))} "
            f"in from the {get_random_direction()}."
        )

        self.flavor = choice(
            [
                "Legally distinct from any similarly-named creatures.",
                "Hoo. Hoo. A frickin' @1, that's who.",
                "Trust me, you don't want to know.",
            ]
        )

        self.escape = "@1dc, silent as a jackhammer, slips away."
        self.death = choice(
            [
                "@1dc gives a final howl of pain and terror before crumpling to the ground.",
                "After a last-ditch effort to escape your fury, @1d collapses into lifelessness.",
                "The abomination of nature will no more threaten your sense of reason.",
            ]
        )

        self.traits[DamageTypes.RANGED] = 1.50
        self.traits[DamageTypes.PIERCING | DamageTypes.SLASHING] = 1.25
        self.traits[DamageTypes.BLUDGEONING] = 0.5

        # Bearowls fly (owl half). The ``WingPlugin.on_injury_change``
        # hook from item 2.5 discards this flag when a wing is driven
        # to ``InjuryLevels.USELESS``, grounding the creature. This
        # pins the full wing -> grounded interaction on a real
        # creature, not just the hydra test fixture.
        self.flags = {"flying"}

        self.size = Size.LARGE
        self._scale_part_hp()
        # Thick pelt + layered muscle — torso-targeting absorbs a
        # flat +3 on top of base defense.
        for part in self.body_parts:
            if part.name == "torso":
                part.defense_bonus = 3

    # Reacts to hugs.
    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                "Are you really sure you want to do that, @2?",
                f"@1dc looks at @2 suspiciously before accepting the {invocation}.",
                f"{invocation.capitalize()}s do not work on @1, @2.",
            ]
        )
