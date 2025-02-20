from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.armor import Armor


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
            bonuses={"dodge": 2, "defense": -2},
        )
