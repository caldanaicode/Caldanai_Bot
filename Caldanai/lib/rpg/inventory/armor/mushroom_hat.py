from bson import ObjectId

from Caldanai.lib.rpg.inventory.armor import Armor
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ArmorPlugin(Armor):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None):
		super().__init__(
			iid=iid,
			name="mushroom hat",
			desc="Wait, it was that kind of Toad?",
			unit_weight=1.2,
			unit_value=5,
			image="mushroom_red.png",
			rarity=rarity,
			article="a",
			slot="head",
			bonuses={
				"dodge": 2,
				"defense": -2
			},
			plugin='mushroom_hat'
		)
