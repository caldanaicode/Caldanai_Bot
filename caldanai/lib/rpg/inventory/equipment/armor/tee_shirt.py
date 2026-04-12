from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="tee-shirt",
            desc="I killed a dragon and all I got was this lousy shirt. (Lice not included.)",
            unit_weight=0.6,
            unit_value=4,
            image="tee-shirt128.png",
            quality=quality,
            slots=EquipmentSlots.TORSO,
            bonuses={"dodge": 1, "health_max": 1, "defense": 1},
        )
