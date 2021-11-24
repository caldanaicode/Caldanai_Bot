from typing import Dict, List

from random import choice

from Caldanai.lib.rpg import get_random_direction
from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions


class MonsterPlugin(Monster):
	def __init__(self):
		super().__init__(
			name="toad",
			atk="1d8",
			defense="1d4",
			dodge="2d8",
			health_max="2d8"
		)

		self.time_partition = TimePartitions.CREPUSCULAR | TimePartitions.NOCTURNAL
		self.image = None
		self.aggression = AggressionLevels.VENGEFUL
		self.arrival = f"A giant @1 {choice('hops|leaps|bounds'.split('|'))} in from the {get_random_direction()}, " \
			f"with a hungry gaze."
		self.flavor = "This @1 is abnormally large, its diet primarily consisting of cute, small animals."
		self.escape = "The @1 barks out a loud croaking noise before leaping off into the distance."
		self.death = f"The @1 struggles to leap away, but the effort is futile, as @1s collapses onto @1a belly."

		self.loot: List[Dict] = [
			{"plugin": "toad_slime", "item_type": "Item", "frequency": 0.9},
			{"plugin": "mushroom_hat", "item_type": "Armor", "frequency": 0.3}
		]

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
