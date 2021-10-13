from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="goblin",
			atk="1d8",
			defense="1d10",
			dodge="1d10",
			health="1d20"
		)

		self.image = None
		self.arrival = Parser.parse(choice([
			"With a spluttering snarl, a goblin {bursts|pads|runs} into the area.",
			"A screeching laugh shatters the serenity that once lingered here, as a goblin finds it way hither."
		]))

		self.flavor = Parser.parse(choice([
			"This goblin is so ugly it's almost cute.",
			"A green and gray blob of stupidity."
		]))

		self.escape = Parser.parse(choice([
			"The goblin snorts, a vacant eye roaming the surroundings before it trudges off."
		]))

		self.death = Parser.parse(choice([
			"The goblin's eyes bulge as if it only now realized it was outmatched, and it flops onto the ground unceremoniously."
		]))

		self.loot: Dict[str, float] = {
			"stick": 0.5,
			"rock": 0.5,
			"spear": 0.1
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		# TODO: Perhaps this goblin should attack in response? Or maybe the erratic flailing damages the hugger...
		responses = [
			"The goblin hoots at $n and backs away, flailing erratically."
		]
		return Parser.parse(choice(responses), name, invocation)
