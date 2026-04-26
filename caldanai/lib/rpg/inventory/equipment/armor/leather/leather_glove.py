from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="leather glove",
            desc=(
                "Suppled hide stitched into a working glove. "
                "Grips a hilt without slipping."
            ),
            unit_weight=0.2,
            unit_value=3,
            image=None,
            quality=quality,
            slots=EquipmentSlots.GLOVES,
            bonuses={"defense": 1},
        )
