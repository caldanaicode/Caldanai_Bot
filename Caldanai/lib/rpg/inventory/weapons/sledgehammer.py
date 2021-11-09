from bson import ObjectId

from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.inventory.weapons import Weapon


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
			atk="2d8",
			is_2handed=True,
			is_magic=False,
			is_ranged=False,
			atk_msg="bashes",
			bonus=bonus,
			article="a",
			dmg_type="bludgeoning"
		)
