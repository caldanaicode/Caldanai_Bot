from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import Qualities
from Caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, count: int = 1):
        super().__init__(
            iid=iid,
            name="small gem",
            desc="Sadly, the jewelry market has collapsed due to the frequency of dragon kills.",
            unit_weight=0.1,
            unit_value=10,
            image="small_gem128.png",
            quality=quality,
            plural="small gems",
            count=count,
        )
