from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="rough greave",
            desc=(
                "Quilted thigh padding, cinched with leather laces. "
                "Smells faintly of sweat and an older fight."
            ),
            unit_weight=0.5,
            unit_value=2,
            image=None,
            quality=quality,
            slots=EquipmentSlots.LEGS,
            bonuses={"defense": 1},
        )
