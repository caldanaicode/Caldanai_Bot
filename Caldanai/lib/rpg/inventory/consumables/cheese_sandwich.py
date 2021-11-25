from bson import ObjectId

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.inventory.consumables import Consumable
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ConsumablePlugin(Consumable):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None, uses_max: int = 5, uses_left: int = 5):
		super().__init__(
			iid=iid,
			name="cheese sandwich",
			desc="It would be best to eat or sell this before it goes bad.",
			unit_weight=0.4,
			unit_value=1,
			image="cheese_sammich128.png",
			rarity=rarity,
			article="a",
			uses_max=uses_max,
			uses_left=uses_left,
			plugin='cheese_sandwich'
		)

	def use(self, user: Creature) -> (str, bool):
		msg, keep = super().use(user)

		msg += f"{'The ' if not isinstance(user, Player) else ''}@2 takes a bite of " \
			   f"@2a @1.{'' if keep else ' That was the last of it!'}"

		d4 = Dice.d4()
		msg += f"\n@2sc replenishes {d4.value} health!"
		user.apply_damage(-d4.value)

		if isinstance(user, Player):
			user.update_roll_count(d4.sides, d4.value)

		return parse(msg, self, user), keep
