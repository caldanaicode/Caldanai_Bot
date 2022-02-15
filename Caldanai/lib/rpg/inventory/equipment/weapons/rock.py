from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="rock",
			desc="Simply a rock, that fits in your hand just right.",
			unit_weight=2,
			unit_value=0,
			image="grey-rock128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="rock",
			atk="1d6",
			atk_msg="bashes",
			bonus=bonus,
			dmg_type=DamageTypes.BLUDGEONING
		)
