from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="leather cap",
            desc=(
                "Soft leather, hand-shaped to the skull. "
                "Quiet under a hood, warm in winter."
            ),
            unit_weight=0.3,
            unit_value=4,
            image=None,
            quality=quality,
            slots=EquipmentSlots.HEAD,
            bonuses={"defense": 1},
        )
