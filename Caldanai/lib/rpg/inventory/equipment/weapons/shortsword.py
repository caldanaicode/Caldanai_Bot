from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="shortsword",
			desc="The most basic weapon for novice adventurers.",
			unit_weight=5,
			unit_value=8,
			image="shortsword128.png",
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="shortsword",
			atk="1d8",
			is_magic=False,
			is_ranged=False,
			atk_msg="swings",
			bonus=bonus,
			dmg_type="slashing"
		)
