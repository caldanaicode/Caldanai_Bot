from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    LOW_QUALITY_DODGE_PENALTY = 1

    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="leather jerkin",
            desc=(
                "Sleeveless body-armor of supple hide, double-stitched "
                "down the seams. Heavy enough to turn a knife, light "
                "enough to wear all day."
            ),
            unit_weight=1.2,
            unit_value=8,
            image=None,
            quality=quality,
            slots=EquipmentSlots.TORSO,
            bonuses={"defense": 2},
        )
