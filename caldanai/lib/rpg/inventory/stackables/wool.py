from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, count: int = 1):
        super().__init__(
            iid=iid,
            name="wool",
            desc="A fluffy ball of wool, plucked from the corpse of a sheep by some evil adventurer.",
            unit_weight=0.01,
            unit_value=1,
            image=None,
            quality=quality,
            article="some",
            plural="tufts of wool",
            count=count,
        )
