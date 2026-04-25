from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="patchwork bracer",
            desc=(
                "Layered leather straps and mismatched buckles. "
                "Cut from whatever the previous owner had on."
            ),
            unit_weight=0.4,
            unit_value=2,
            image=None,
            quality=quality,
            slots=EquipmentSlots.FOREARMS,
            bonuses={"defense": 1},
        )
