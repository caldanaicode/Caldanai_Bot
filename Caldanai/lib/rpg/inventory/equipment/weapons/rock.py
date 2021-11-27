from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="rock",
			desc="Simply a rock, that fits in your hand just right.",
			unit_weight=2,
			unit_value=0,
			image="grey-rock128.png",
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="rock",
			atk="1d6",
			is_magic=False,
			is_ranged=False,
			atk_msg="bashes",
			bonus=bonus,
			dmg_type="bludgeoning"
		)
