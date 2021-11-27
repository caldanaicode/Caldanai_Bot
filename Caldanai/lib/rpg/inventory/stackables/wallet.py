from bson import ObjectId

from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.rarity import Rarity


class StackablePlugin(Stackable):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, count: int = 1):
		super().__init__(
			iid=iid,
			name="wallet",
			desc="A small pouch for holding things. Stolen from a hugger by a mugger.",
			unit_weight=0.2,
			unit_value=8,
			image="wallet128.png",
			rarity=rarity,
			article='a',
			plural='wallets',
			count=count
		)
