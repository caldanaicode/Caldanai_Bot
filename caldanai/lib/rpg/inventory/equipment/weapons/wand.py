from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="wand",
            desc="Kinda like a stick, but more magical",
            unit_weight=0.3,
            unit_value=10,
            image="stick128.png",
            quality=quality,
            slots=EquipmentSlots.EITHER_HELD,
            atk="2d4",
            atk_msg="waves",
            bonus=bonus,
            dmg_type=DamageTypes.MAGICAL | DamageTypes.RANGED | DamageTypes.COMBINED,
        )
