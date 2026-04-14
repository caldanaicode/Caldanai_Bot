from random import choice

from caldanai.lib.rpg import get_random_direction
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Size)


class Toad(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="toad",
            atk="1d8",
            defense="1d4",
            dodge="2d8",
            health_max="4d8"
        )

        if choice([1, 2]) == 2:
            self.size = Size.SMALL
            self.arrival = "An odd humanoid mushroom waddles into the area muttering something about castles and princesses."
            self.flavor = "It remains unclear whether this _toadstool_ is just a remnant of a bad trip."
            self.escape = "The funny little toadstool zips around in a rapid circle before jumping down a large green pipe -- wait, where did that come from?"
            self.death = "The mushroom waves @1a arms frantically, shrieking in terror. Then, @1s suddenly stops and falls backwards, rocking slightly before going still."
        else:
            self.size = Size.MEDIUM
            size = self.size.name.lower()
            self.arrival = (
                f"A {size} @1 {choice('hops|leaps|bounds'.split('|'))} in from the {get_random_direction()}, "
                f"with a hungry gaze."
            )
            self.flavor = "This @1 is abnormally large, its diet primarily consisting of cute, small animals."
            self.escape = "@1dc barks out a loud croaking noise before leaping off into the distance."
            self.death = "@1dc struggles to leap away, but the effort is futile, as @1s collapses onto @1a belly."

        self.time_partition = TimePartitions.CREPUSCULAR | TimePartitions.NOCTURNAL
        self.image = None
        self.aggression = AggressionLevels.VENGEFUL

        self.traits[DamageTypes.RANGED | DamageTypes.PIERCING | DamageTypes.COMBINED] = 1.50
        self.traits[DamageTypes.FIRE] = 2.00
        self.traits[DamageTypes.BLUDGEONING] = 0.75
        self.traits[DamageTypes.PIERCING] = 1.00
        self.traits[
            DamageTypes.ANY - (DamageTypes.RANGED | DamageTypes.PIERCING | DamageTypes.FIRE | DamageTypes.BLUDGEONING)
        ] = 0.5

        self.loot["toad_slime"] = 0.9
        self.loot["mushroom_hat"] = 0.3

        self.body_parts = [p for p in BodyPart.quadruped() if p.name != "tail"]

        self._scale_part_hp()
