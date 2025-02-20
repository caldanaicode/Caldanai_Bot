from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None):
        super().__init__(
            iid=iid,
            name="cape",
            desc="This cape is short, yet stylish. Wearing this may impart minor delusions of grandeur.",
            unit_weight=1.0,
            unit_value=1,
            image=None,
            quality=quality,
            slots=EquipmentSlots.CAPE,
            bonuses={
                "dodge": 1,
            },
        )
