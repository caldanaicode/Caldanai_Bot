from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="warhammer",
            desc="An old favorite of many.",
            unit_weight=2,
            unit_value=5,
            image="warhammer128.png",
            quality=quality,
            slots=EquipmentSlots.EITHER_HELD,
            atk="1d10",
            atk_msg="bonks",
            bonus=bonus,
            dmg_type=DamageTypes.BLUDGEONING,
        )
