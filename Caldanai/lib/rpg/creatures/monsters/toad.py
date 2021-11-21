from typing import Dict, List

from random import choice

from Caldanai.lib.rpg import get_random_direction
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.time import TimePartitions


class Monster(Creature):
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
		self.aggression = "vengeful"
		self.arrival = choice([
			f"A giant toad {choice('hops|leaps|bounds'.split('|'))} in from the "
			f"{get_random_direction()}, with a hungry gaze."
		])

		self.flavor = "This toad is abnormally large, its diet primarily consisting of cute, small animals."
		self.escape = "The toad barks out a loud croaking noise before leaping off into the distance."
		self.death = f"The toad struggles to leap away, but the effort is futile, as {self.pronouns['subject']} " \
					 f"collapses onto {self.pronouns['possessive']} belly."

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
