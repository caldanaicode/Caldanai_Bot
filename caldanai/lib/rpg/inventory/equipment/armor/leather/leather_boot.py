from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="leather boot",
            desc=(
                "Tall hide boot, sole stitched and waxed. "
                "The pair were made together — they keep walking together."
            ),
            unit_weight=0.5,
            unit_value=4,
            image=None,
            quality=quality,
            slots=EquipmentSlots.FEET,
            bonuses={"defense": 1},
        )
