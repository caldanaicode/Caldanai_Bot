from random import choice

from Caldanai.lib.rpg import get_random_direction, Player
from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature


class Doppelganger(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="???",
            atk="2d10",
            defense="6d4",
            dodge="6d4",
            health_max="40d4"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.aggression = AggressionLevels.RAMPAGE
        self.image = None
        self.arrival = choice(
            [
                "A pale creature with dimly-glowing putrid-yellow eyes lopes into the area.",
                "A lumpy, misshapen humanoid slinks into view.",
            ]
        )

        self.flavor = choice(
            [
                "This creature seems to defy definition as it is quite difficult to tell what, exactly, one is looking at.",
                "The flesh of this creature seems to shift both size and shape, disturbingly devoid of description.",
            ]
        )

        self.escape = choice(
            [
                '"Oh yes, I think I\'ll keep this one for a while," the creature exclaims with a creepy squeal of '
                "delight, loping swiftly out of view!",
                f'"You\'ll never catch this one, you meddling kids," the creature shrieks as it escapes to the '
                f"{get_random_direction()}!",
            ]
        )

        self.death = choice(
            [
                "The creature let's out a final cough before dissolving into shapeless ooze.",
                "The @1 coughs blood before collapsing to the ground.",
                '"In another life, you could have been me," the @1 gasps with @1a dying breath.',
            ]
        )

        self.loot["shortsword"] = 0.2
        self.loot["bandanna"] = 0.2
        self.loot["bow"] = 0.15
        self.loot["cheese_sandwich"] = 0.2
        self.loot["wallet"] = 0.25

    def imitate(self, target: Creature) -> str:
        """
        Assumes a creature's form and stats.

        :param target: The creature being targeted.
        :return: A string indicating the results of the imitation.
        """

        if player := isinstance(target, Player) and target:
            # Establish loot possibilities
            for item in player.inventory.all():
                self.loot[item.name] = (self.loot[item.name] if item.name in self.loot else 0) + 0.1

            # Establish stats
            defense = player.get_defense()
            dodge = player.get_dodge()
            health = player.get_health_max()
            self.defense = defense if defense > self.defense else self.defense
            self.dodge = dodge if dodge > self.dodge else self.dodge
            self.health_max = health if health > self.health_max else self.health_max

            return (
                "\nThe amorphous creature's body begins to shift, stretch, and squash. The form's movements are "
                "both disturbing and fascinating, as it molds itself slowly into the likeness of @2."
            )

        return ""

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        responses = [
            f"The @1 breaks down crying at the first affection @1s has ever known, as @2 {invocation}s @1o.",
            f"The @1 graciously accepts @2's {invocation} while reaching toward @2a wallet...",
            f"The @1 sneers at @2's attempt to {invocation} @1o.",
        ]

        response = choice(responses)
        if response == responses[1]:
            response += f"\n{self.steal(actor)}"

        return response

    def apply_damage(self, amount: int) -> str:
        was_alive = self.health > 0
        super().apply_damage(amount)
        if was_alive and self.is_dead():
            return self.death

        return ""
