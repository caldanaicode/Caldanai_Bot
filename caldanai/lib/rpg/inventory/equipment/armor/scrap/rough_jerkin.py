from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="rough jerkin",
            desc=(
                "A sleeveless body-cloth of rough weave, fastened "
                "with mismatched buttons. Stained at the seams."
            ),
            unit_weight=0.7,
            unit_value=3,
            image=None,
            quality=quality,
            slots=EquipmentSlots.TORSO,
            bonuses={"defense": 1},
        )
