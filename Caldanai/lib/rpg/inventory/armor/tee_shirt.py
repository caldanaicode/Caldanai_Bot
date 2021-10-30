from bson import ObjectId

from Caldanai.lib.rpg.inventory.armor import Armor
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ArmorPlugin(Armor):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None):
		super().__init__(
			iid=iid,
			name="tee-shirt",
			desc="I killed a dragon and all I got was this lousy shirt. (Lice not included.)",
			unit_weight=0.6,
			unit_value=4,
			image="tee-shirt128.png",
			rarity=rarity,
			article="a",
			slot="torso",
			bonuses={
				"dodge": 1,
				"health_max": 1,
				"defense": 1
			}
		)
		self.plugin = 'tee_shirt'
