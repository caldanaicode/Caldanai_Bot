from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="bandanna",
            desc="A multifunctional piece of patterned cloth.",
            unit_weight=0.2,
            unit_value=1,
            image="bandanna128.png",
            quality=quality,
            slots=EquipmentSlots.FACE,
            bonuses={"dodge": 2, "health_max": -1},
        )
