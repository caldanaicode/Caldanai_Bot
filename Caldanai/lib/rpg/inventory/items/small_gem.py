from bson import ObjectId

from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ItemPlugin(Item):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, count: int = 1):
		super().__init__(
			iid=iid,
			name="small gem",
			desc="Sadly, the jewelry market has collapsed due to the frequency of dragon kills.",
			unit_weight=0.1,
			unit_value=10,
			image="small_gem128.png",
			rarity=rarity,
			article='a',
			plural='small gems',
			stackable=True,
			count=count,
			plugin='small_gem'
		)
