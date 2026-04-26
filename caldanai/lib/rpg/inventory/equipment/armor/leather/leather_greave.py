from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="leather greave",
            desc=(
                "Layered hide thigh-pieces, laced from hip to knee. "
                "Took most of one beast's hindquarters to cut."
            ),
            unit_weight=0.7,
            unit_value=6,
            image=None,
            quality=quality,
            slots=EquipmentSlots.LEGS,
            bonuses={"defense": 1},
        )
