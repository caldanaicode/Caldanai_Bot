from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="dragon",
			atk="3d10",
			defense="3d8",
			dodge="3d10",
			health="10d10"
		)

		self.image = None
		self.arrival = Parser.parse(choice([
			"A piercing roar rocks the heavens, as a dragon swoops down out of the clouds searching for prey."
		]))

		self.flavor = Parser.parse(choice([
			"A massive red dragon, smelling faintly of cinnamon and charcoal."
		]))

		self.escape = Parser.parse(choice([
			"The dragon circles the area lazily before taking to the clouds, disappearing from sight."
		]))

		self.death = Parser.parse(choice([
			"The dragon gives a final bellow of rage and disbelief as it falls to the ground. It's thrashing lasts "
			"but a moment, then all is still."
		]))

		self.loot: Dict[str, float] = {
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		# TODO: Perhaps attack the hugger in some way.
		responses = [
			"The dragon glowers hungrily at $n, and sends a wisp of flame in their direction."
		]
		return Parser.parse(choice(responses), name, invocation)
