from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="sledgehammer",
			desc="This weapon wants to be yours, but may or may not have initials P.G.",
			unit_weight=10.5,
			unit_value=8,
			image="sledge128.png",
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.TWO_HANDED,
			plugin="sledgehammer",
			atk="2d8",
			is_magic=False,
			is_ranged=False,
			atk_msg="bashes",
			bonus=bonus,
			dmg_type="bludgeoning"
		)
