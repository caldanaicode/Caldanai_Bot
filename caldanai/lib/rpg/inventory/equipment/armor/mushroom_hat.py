from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="mushroom hat",
            desc="Wait, it was that kind of Toad?",
            unit_weight=1.2,
            unit_value=5,
            image="mushroom_red.png",
            quality=quality,
            slots=EquipmentSlots.HEAD,
            bonuses={"dodge": 1, "defense": -1},
        )
