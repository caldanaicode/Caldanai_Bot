from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="spear",
            desc="Stick them with the pointy end!",
            unit_weight=3.5,
            unit_value=15,
            image="spear128.png",
            quality=quality,
            slots=EquipmentSlots.TWO_HANDED,
            atk="2d10",
            atk_msg="thrusts",
            bonus=bonus,
            dmg_type=DamageTypes.PIERCING,
        )
