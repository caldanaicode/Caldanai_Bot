from typing import List

from bson import ObjectId

from Caldanai.lib.rpg.inventory.item import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity


class Consumable(Item):
	def __init__(
			self,
			iid: ObjectId = None,
			tid: ObjectId = None,
			pid: ObjectId = None,
			name: str = "",
			desc: str = "",
			weight: float = 1.0,
			value: int = 0,
			image: str = None,
			rarity: Rarity = None,
			article: str = None,
			uses: int = 1,
			use_msgs: List[str] = None
	):
		super().__init__(iid, tid, pid, name, desc, weight, value, image, rarity, article)
		self.uses: int = uses or 1
		self.useMessages = use_msgs or []
