from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="bow",
			desc="For the socially-distanced adventurer.",
			unit_weight=5,
			unit_value=15,
			image="bow128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.TWO_HANDED,
			plugin="bow",
			atk="2d10",
			atk_msg="shoots",
			bonus=bonus,
			dmg_type=DamageTypes.PIERCING | DamageTypes.RANGED | DamageTypes.COMBINED
		)
