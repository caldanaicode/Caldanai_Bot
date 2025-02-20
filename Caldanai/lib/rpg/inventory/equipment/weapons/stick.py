from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
    def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
        super().__init__(
            iid=iid,
            name="stick",
            desc="It's brown. It's sticky. It's a simple stick, probably from some nearby tree. It's only slightly "
            "better than being bare-handed.",
            unit_weight=0.3,
            unit_value=0,
            image="stick128.png",
            quality=quality,
            slots=EquipmentSlots.EITHER_HELD,
            atk="1d4",
            atk_msg="pokes",
            bonus=bonus,
            dmg_type=DamageTypes.PIERCING,
        )

        self.attacks = {
            # Command: DamageType, Damage Roll, Strike Verb, Frequency
            "swing": (DamageTypes.BLUDGEONING, "1d4", "smacks", 0.5),
            "thrust": (DamageTypes.PIERCING, "1d4", "pokes", 0.5),
        }
