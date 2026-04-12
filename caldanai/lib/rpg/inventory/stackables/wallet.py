from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, count: int = 1):
        super().__init__(
            iid=iid,
            name="wallet",
            desc="A small pouch for holding things. Stolen from a hugger by a mugger.",
            unit_weight=0.2,
            unit_value=8,
            image="wallet128.png",
            quality=quality,
            plural="wallets",
            count=count,
        )
