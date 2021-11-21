from typing import Dict, List

from random import choice

from Caldanai.lib.rpg import get_random_direction
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.time import TimePartitions


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="sheep",
			atk="1d4",
			defense="1d6",
			dodge="1d6",
			health_max="2d4"
		)

		self.time_partition = TimePartitions.DIURNAL
		self.image = None
		self.aggression = "neutral"
		self.arrival = f"A fluffy mass of fur {choice('saunters|ambles|prances|skitters|tiptoes|wanders'.split('|'))} " \
					   f"in from the {get_random_direction()}."

		self.flavor = choice([
			"Just a cuddly sheep, searching the lonely fields for hugs.",
			"Ple-e-e-e-ease don't kill me-e-e-e-e.",
			f"A sleepy looking sheep, seeking naught but the warmth of {self.pronouns['possessive']} barn."
		])

		self.escape = f"The sheep {choice('slips|bounds|wanders'.split('|'))} away merrily, not a care in the world."
		self.death = choice([
			"The sheep gurgles out a final, sad, bleating cry, and goes still.",
			"Eyes rolling wildly in terror and pain, the sheep stumbles and falls to the ground motionless.",
			"A final wheezing breath escapes slowly, as the sheep collapses to the ground in a twitching heap."
		])

		self.loot: List[Dict] = [
			{"plugin": "stick", "item_type": "Weapon", "frequency": 0.5},
			{"plugin": "wool", "item_type": "Item", "frequency": 0.5},
			{"plugin": "leather", "item_type": "Item", "frequency": 0.25}
		]

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		return choice([
			f"The sheep glances at {actor.name}, but apparently decides to allow the {invocation}.",
			f"A soft bleat escapes the sheep as {actor.name} {invocation}s {self.pronouns['object']}.",
			f"The sheep wuffles happily and leans into {actor.name}'s {invocation}."
		])

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
