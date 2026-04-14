from random import choice, randint

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes, Size
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.dice import Dice


class Bandit(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="bandit",
            atk="1d8",
            defense="1d12",
            dodge="1d12",
            health_max="3d8"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = "bandit128.png"
        self.aggression = AggressionLevels.VENGEFUL
        self.arrival = (
            f"A masked @1 {choice('stealthily|clumsily|quickly|slowly'.split('|'))} "
            f"{choice('walks|saunters|sashays|sneaks'.split('|'))} out of the "
            f"{choice('bushes|rocks|distance|shadows'.split('|'))}."
        )

        self.flavor = choice(["Your money or your life.", "This is a stick up.", "You'll never take me alive."])

        self.escape = choice(["@1dc runs off, taking whatever @1s can grab.", "Other horizons call @1d away."])

        self.death = choice(
            [
                "@1dc dies, and shall no longer steal from the rich and give to the poor.",
                "@1dc coughs blood before collapsing to the ground.",
                '"In another life, you could have been me," @1d gasps with @1a dying breath.',
            ]
        )

        self.traits[DamageTypes.RANGED] = 1.00
        self.traits[DamageTypes.MAGICAL] = 1.50
        self.traits[DamageTypes.ANY - (DamageTypes.RANGED | DamageTypes.MAGICAL)] = 0.75

        self.loot["shortsword"] = 0.2
        self.loot["bandanna"] = 0.2
        self.loot["bow"] = 0.15
        self.loot["cheese_sandwich"] = 0.2
        self.loot["wallet"] = 0.25

        self.body_parts = BodyPart.humanoid()

        self.size = Size.MEDIUM
        self._scale_part_hp()

    def steal(self, target: Creature) -> str:
        """
        Attempts to steal a creature's wealth.

        Requires at least one working arm (to reach into the target's
        pockets) and at least one working leg (to close the distance).

        :param target: The creature being targeted.
        :return: A string indicating the results of the theft.
        """
        from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
        from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin

        working_arms = [p for p in self.body_parts if isinstance(p, ArmPlugin) and not p.is_destroyed()]
        if not working_arms:
            return "\n@1dc reaches for @2's coin purse, but @1a mangled arms fail to grasp anything."

        working_legs = [p for p in self.body_parts if isinstance(p, LegPlugin) and not p.is_destroyed()]
        if not working_legs:
            return "\n@1dc tries to approach @2's wallet, but can't close the distance on @1a ruined legs."

        if target.clarks > 0:
            amount = randint(1, max(1, int(target.clarks / 10)))
            attempt = Dice.quick_roll("1d20")
            if attempt >= target.get_dodge():
                target.give_clarks(-amount)
                return f"\n@2's wallet suddenly feels lighter... {amount} clarks were lost!"
            return "\n@2 easily avoids the bandit's groping fingers."
        else:
            return "\n@1dc sneers in disgust, realizing that @2 has no clarks to steal."

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        responses = [
            f"@1dc breaks down crying at the first affection @1s has ever known, as @2 {invocation}s @1o.",
            f"@1dc graciously accepts @2's {invocation} while reaching toward @2a wallet...",
            f"@1dc sneers at @2's attempt to {invocation} @1o.",
        ]

        response = choice(responses)
        if response == responses[1]:
            response += f"\n{self.steal(actor)}"

        return response
