from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, count: int = 1):
        super().__init__(
            iid=iid,
            name="giant toe",
            desc="Severed from something enormous. The nail alone could shingle a roof.",
            unit_weight=2.5,
            unit_value=6,
            image=None,
            quality=quality,
            plural="giant toes",
            count=count,
        )
