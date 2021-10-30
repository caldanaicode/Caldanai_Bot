from bson import ObjectId

from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="warhammer",
			desc="An old favorite of many.",
			unit_weight=2,
			unit_value=5,
			image="warhammer128.png",
			rarity=rarity,
			atk="1d10",
			is_2handed=False,
			is_magic=False,
			is_ranged=False,
			atk_msg="bonks",
			bonus=bonus,
			article="a",
			dmg_type="bludgeoning"
		)
