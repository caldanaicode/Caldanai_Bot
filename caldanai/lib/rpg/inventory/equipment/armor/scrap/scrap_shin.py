from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="scrap shin",
            desc=(
                "Strips of leather and bark wrapped tight around "
                "the shin. Ugly and effective."
            ),
            unit_weight=0.4,
            unit_value=2,
            image=None,
            quality=quality,
            slots=EquipmentSlots.SHINS,
            bonuses={"defense": 1},
        )
