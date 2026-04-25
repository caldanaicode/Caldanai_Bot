from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="ratty glove",
            desc=(
                "Mismatched leather, fingertips out, the palm worn "
                "shiny by years of grip."
            ),
            unit_weight=0.2,
            unit_value=1,
            image=None,
            quality=quality,
            slots=EquipmentSlots.GLOVES,
            bonuses={"defense": 1},
        )
