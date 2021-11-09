from bson import ObjectId

from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ItemPlugin(Item):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, count: int = 1):
		super().__init__(
			iid=iid,
			name="wool",
			desc="A fluffy ball of wool, plucked from the corpse of a sheep by some evil adventurer.",
			unit_weight=0.01,
			unit_value=1,
			image=None,
			rarity=rarity,
			article='some',
			plural='tufts of wool',
			stackable=True,
			count=count
		)
