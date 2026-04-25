from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="scrap collar",
            desc=(
                "A leather thong knotted around a small charm. "
                "Trinket more than armor — but the previous "
                "wearer didn't survive without it."
            ),
            unit_weight=0.1,
            unit_value=1,
            image=None,
            quality=quality,
            slots=EquipmentSlots.NECK,
            bonuses={"health_max": 1},
        )
