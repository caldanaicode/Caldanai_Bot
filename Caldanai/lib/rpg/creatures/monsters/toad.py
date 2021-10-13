from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


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
		self.arrival = Parser.parse(choice([
			"A giant toad {hops|leaps|bounds} in from the {"
			"north|south|east|west|northeast|northwest|southeast|southwest}, with a hungry gaze."
		]))

		self.flavor = Parser.parse(choice([
			"This toad is abnormally large, its diet primarily consisting of cute, small animals."
		]))

		self.escape = Parser.parse(choice([
			"The toad barks out a loud croaking noise before leaping off into the distance."
		]))

		self.death = Parser.parse(choice([
			"The toad struggles to leap away, but the effort is futile, as it collapses onto its belly."
		]))

		self.loot: Dict[str, float] = {
			"toad slime": 0.9,
			"mushroom hat": 0.3
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		responses = [
			"The toad seems to ignore $n's affections entirely."
		]
		return Parser.parse(choice(responses), name, invocation)
