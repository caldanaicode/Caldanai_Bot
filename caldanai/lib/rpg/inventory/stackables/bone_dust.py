from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, count: int = 1):
        super().__init__(
            iid=iid,
            name="bone dust",
            desc="Powdery, brittle remains. Useful for someone with a ritual in mind, presumably.",
            unit_weight=0.05,
            unit_value=2,
            image=None,
            quality=quality,
            article="some",  # uncountable mass noun
            plural="bone dust",  # uncountable noun — same singular and plural form
            count=count,
        )
