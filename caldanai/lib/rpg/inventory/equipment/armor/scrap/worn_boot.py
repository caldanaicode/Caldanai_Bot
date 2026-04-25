from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="worn boot",
            desc=(
                "Cobbled leather, a sole more memory than substance. "
                "Whoever wore it last walked a long way."
            ),
            unit_weight=0.5,
            unit_value=2,
            image=None,
            quality=quality,
            slots=EquipmentSlots.FEET,
            bonuses={"defense": 1},
        )
