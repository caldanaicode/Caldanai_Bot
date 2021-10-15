from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="toad",
			atk="1d8",
			defense="1d4",
			dodge="2d8",
			health="2d8"
		)

		self.image = None
		self.arrival = choice([
			f"A giant toad {choice('hops|leaps|bounds'.split('|'))} in from the "
			f"{choice('north|south|east|west|northeast|northwest|southeast|southwest'.split('|'))}, with a hungry gaze."
		])

		self.flavor = "This toad is abnormally large, its diet primarily consisting of cute, small animals."
		self.escape = "The toad barks out a loud croaking noise before leaping off into the distance."
		self.death = f"The toad struggles to leap away, but the effort is futile, as {self.pronouns['subject']} " \
					 f"collapses onto {self.pronouns['possessive']} belly."

		self.loot: Dict[str, float] = {
			"toad slime": 0.9,
			"mushroom hat": 0.3
		}
