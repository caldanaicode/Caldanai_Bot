from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="sledgehammer",
            desc="This weapon wants to be yours, but may or may not have initials P.G.",
            unit_weight=10.5,
            unit_value=8,
            image="sledge128.png",
            quality=quality,
            slots=EquipmentSlots.TWO_HANDED,
            atk="2d8",
            atk_msg="bashes",
            bonus=bonus,
            dmg_type=DamageTypes.BLUDGEONING,
        )
