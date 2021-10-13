from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="sheep",
			atk="1d4",
			defense="1d6",
			dodge="1d6",
			health="2d4"
		)

		self.image = None
		self.arrival = Parser.parse(choice([
			"A fluffy mass of fur {saunters|ambles|prances|skitters|tiptoes|wanders} in from the {"
			"north|south|east|west|northeast|northwest|southeast|southwest}."
		]))

		self.flavor = Parser.parse(choice([
			"Just a cuddly sheep, searching the lonely fields for hugs.",
			"Ple-e-e-e-ease don't kill me-e-e-e-e.",
			"A sleepy looking sheep, seeking naught but the warmth of her barn."
		]))

		self.escape = Parser.parse(choice([
			"The sheep {slips|bounds|wanders} away merrily, not a care in the world."
		]))

		self.death = Parser.parse(choice([
			"The sheep gurgles out a final, sad, bleating cry, and goes still.",
			"Eyes rolling wildly in terror and pain, the sheep stumbles and falls to the ground motionless.",
			"A final wheezing breath escapes slowly, as the sheep collapses to the ground in a twitching heap."
		]))

		self.loot: Dict[str, float] = {
			"stick": 0.5,
			"wool": 0.5,
			"leather": 0.25
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		responses = [
			"The sheep glances at $n, but apparently decides to allow the $c.",
			"A soft bleat escapes the sheep as $n $cs it."
		]
		return Parser.parse(choice(responses), name, invocation)
