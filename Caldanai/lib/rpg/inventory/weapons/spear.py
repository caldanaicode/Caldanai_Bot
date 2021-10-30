from bson import ObjectId

from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="spear",
			desc="Stick them with the pointy end!",
			unit_weight=3.5,
			unit_value=15,
			image="spear128.png",
			rarity=rarity,
			atk="2d10",
			is_2handed=True,
			is_magic=False,
			is_ranged=False,
			atk_msg="thrusts",
			bonus=bonus,
			article="a",
			dmg_type="piercing"
		)
