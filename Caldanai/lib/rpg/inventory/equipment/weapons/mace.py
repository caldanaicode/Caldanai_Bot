from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="mace",
			desc="Stick it with the pointy en.... never mind.",
			unit_weight=5,
			unit_value=9,
			image="mace128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="mace",
			atk="2d6",
			atk_msg="crushes",
			bonus=bonus,
			dmg_type=DamageTypes.BLUDGEONING
		)
