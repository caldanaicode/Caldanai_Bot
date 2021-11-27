from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="mace",
			desc="Stick it with the pointy en.... never mind.",
			unit_weight=5,
			unit_value=9,
			image="mace128.png",
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="mace",
			atk="2d6",
			is_magic=False,
			is_ranged=False,
			atk_msg="crushes",
			bonus=bonus,
			dmg_type="bludgeoning"
		)
