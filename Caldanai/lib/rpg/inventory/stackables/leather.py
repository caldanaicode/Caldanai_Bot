from bson import ObjectId

from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.rarity import Rarity


class StackablePlugin(Stackable):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, count: int = 1):
		super().__init__(
			iid=iid,
			name="leather",
			desc="The hide of some beast that seems to have magically stretched and tanned itself.",
			unit_weight=1.0,
			unit_value=5,
			image=None,
			rarity=rarity,
			article="some",
			plural="leathers",
			count=count
		)
