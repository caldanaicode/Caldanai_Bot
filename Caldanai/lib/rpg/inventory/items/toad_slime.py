from bson import ObjectId

from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ItemPlugin(Item):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, count: int = 1):
		super().__init__(
			iid=iid,
			name="toad slime",
			desc="Useful either as an alchemy component or a practical joke.",
			unit_weight=0.5,
			unit_value=2,
			image="green_splat128.png",
			rarity=rarity,
			article="some",
			plural="globs of toad slime",
			stackable=True,
			count=count,
			plugin='toad_slime'
		)
