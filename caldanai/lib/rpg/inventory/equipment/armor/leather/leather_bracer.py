from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="leather bracer",
            desc=(
                "A rigid leather cuff laced over the forearm. "
                "Shaped to a single arm — the matching pair takes a second."
            ),
            unit_weight=0.4,
            unit_value=4,
            image=None,
            quality=quality,
            slots=EquipmentSlots.FOREARMS,
            bonuses={"defense": 1},
        )
