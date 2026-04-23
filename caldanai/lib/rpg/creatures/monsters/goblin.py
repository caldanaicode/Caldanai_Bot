from random import choice
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes, Size
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.helpers.dice import Dice


class Goblin(MonsterPlugin):
    BODY_TREE = humanoid_tree()

    def __init__(self):
        super().__init__(
            name="goblin",
            atk="1d8",
            defense="1d10",
            dodge="1d10",
            health_max="3d10"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.SURVIVE
        self.arrival = choice(
            [
                f"With a spluttering snarl, @1i {choice('bursts|pads|runs'.split('|'))} into the area.",
                "A screeching laugh shatters the serenity that once lingered here, as @1i finds @1a way hither.",
            ]
        )

        self.flavor = choice(["This @1 is so ugly @1s is almost cute.", "A green and gray blob of stupidity."])

        self.escape = f"@1dc snorts, a vacant eye roaming the surroundings before @1s trudges off."
        self.death = (
            f"@1dc's eyes bulge as if @1s only now realized @1s was outmatched, and @1s flops onto the "
            f"ground unceremoniously."
        )

        self.traits[DamageTypes.BLUDGEONING] = 1.50
        self.traits[DamageTypes.PIERCING | DamageTypes.SLASHING] = 0.75
        self.traits[DamageTypes.MAGICAL] = 0.5

        self.loot["stick"] = 0.5
        self.loot["rock"] = 0.5
        self.loot["torch"] = 0.3
        self.loot["spear"] = 0.1

        self.size = Size.SMALL
        self._scale_part_hp()

    # Reacts to hugs.
    def on_hugged(self, actor: Creature, invocation: str) -> str:
        msg = f"@1dc hoots at @2 and backs away, flailing erratically."
        attempt = Dice.quick_roll("1d20")
        if attempt >= actor.get_dodge():
            dmg = Dice.quick_roll("1d4")
            msg += f" @2 is caught off-guard and takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
            m = actor.apply_damage(dmg)
            msg += f"\n{m}" if m else ""
        else:
            msg += "\n@2 narrowly avoids @1d's thrashing!"

        return msg
