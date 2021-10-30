from bson import ObjectId

from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.inventory.consumables import Consumable
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ConsumablePlugin(Consumable):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, uses_max: int = 3, uses_left: int = 3):
		super().__init__(
			iid=iid,
			name="candy",
			desc="Cinnamon-flavored!",
			unit_weight=0.1,
			unit_value=1,
			image="candy128.png",
			rarity=rarity,
			article="some",
			uses_max=uses_max,
			uses_left=uses_left
		)

	def use(self, target: Creature) -> (str, bool):
		msg, keep = super().use(target)

		msg += f"{target.name if isinstance(target, Player) else 'The ' + target.name} tosses a few pieces of " \
			   f"{self.name} into {target.pronouns['possessive']} mouth.{'' if keep else ' That was the last of it!'}"

		return msg, keep
