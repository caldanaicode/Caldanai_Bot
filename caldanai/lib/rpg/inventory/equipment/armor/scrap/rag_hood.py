from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="rag hood",
            desc=(
                "A hood pieced together from cloaked rags. Hides "
                "the face when pulled forward."
            ),
            unit_weight=0.3,
            unit_value=2,
            image=None,
            quality=quality,
            slots=EquipmentSlots.FACE,
            bonuses={"defense": 1},
        )
