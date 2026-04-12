from bson import ObjectId

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="torch",
            desc="This handy stick lets you feel less scared in the dark.",
            unit_weight=0.3,
            unit_value=1,
            image=None,
            quality=quality,
            slots=EquipmentSlots.EITHER_HELD,
            atk="1d6",
            atk_msg="flails",
            bonus=bonus,
            dmg_type=DamageTypes.BLUDGEONING | DamageTypes.FIRE | DamageTypes.COMBINED,
        )
