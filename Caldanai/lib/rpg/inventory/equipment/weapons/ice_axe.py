from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="ice axe",
            desc="An axe with a frosty edge that chills its victims.",
            unit_weight=4.0,
            unit_value=120,
            image="iceaxe128.png",
            quality=quality,
            slots=EquipmentSlots.EITHER_HELD,
            atk="2d6",
            atk_msg="cleaves",
            bonus=bonus,
            dmg_type=DamageTypes.SLASHING | DamageTypes.WATER | DamageTypes.DARK,
        )
