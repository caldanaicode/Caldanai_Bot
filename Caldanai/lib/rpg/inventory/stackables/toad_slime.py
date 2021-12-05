from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import Qualities
from Caldanai.lib.rpg.inventory.stackables import Stackable


class StackablePlugin(Stackable):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, count: int = 1):
		super().__init__(
			iid=iid,
			name="toad slime",
			desc="Useful either as an alchemy component or a practical joke.",
			unit_weight=0.5,
			unit_value=2,
			image="green_splat128.png",
			quality=quality,
			article="some",
			plural="globs of toad slime",
			count=count,
			plugin='toad_slime'
		)
