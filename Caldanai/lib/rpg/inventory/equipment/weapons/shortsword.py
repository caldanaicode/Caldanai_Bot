from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="shortsword",
			desc="The most basic weapon for novice adventurers.",
			unit_weight=5,
			unit_value=8,
			image="shortsword128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="shortsword",
			atk="1d8",
			atk_msg="swings",
			bonus=bonus,
			dmg_type=DamageTypes.SLASHING
		)
