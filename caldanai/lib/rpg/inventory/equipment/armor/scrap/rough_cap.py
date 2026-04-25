from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="rough cap",
            desc=(
                "Coarse cloth, hand-stitched, brim drooping. "
                "Better than nothing."
            ),
            unit_weight=0.3,
            unit_value=2,
            image=None,
            quality=quality,
            slots=EquipmentSlots.HEAD,
            bonuses={"defense": 1},
        )
