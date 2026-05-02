from typing import Tuple
from bson import ObjectId

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.usables.consumables import Consumable


class ConsumablePlugin(Consumable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, uses_max: int = 5, uses_left: int = 5):
        super().__init__(
            iid=iid,
            name="cheese sandwich",
            desc="It would be best to eat or sell this before it goes bad.",
            unit_weight=0.4,
            unit_value=1,
            image="cheese_sammich128.png",
            quality=quality,
            uses_max=uses_max,
            uses_left=uses_left,
        )

    def use(self, user: Creature) -> Tuple[str, bool]:
        msg, keep = super().use(user)

        msg += (
            f"{'The ' if not isinstance(user, Player) else ''}@2 takes a bite of "
            f"@2a @1.{'' if keep else ' That was the last of it!'}"
        )

        d4 = Dice.d4()
        msg += f"\n@2sc @2v(replenishes|replenish) {d4.value} health!"
        user.apply_damage(-d4.value)

        if isinstance(user, Player):
            user.update_roll_count(d4.sides, d4.value)

        return parse(msg, self, user), keep
