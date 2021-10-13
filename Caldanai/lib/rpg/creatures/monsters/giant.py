from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="giant",
			atk="2d10",
			defense="2d8",
			dodge="1d4",
			health="5d10"
		)

		self.image = None
		self.arrival = Parser.parse(choice([
			"The ground trembles slightly as a giant trudges in."
		]))

		self.flavor = Parser.parse(choice([
			"This giant would blend in nicely with the surrounding rocks, if it would stop moving."
		]))

		self.escape = Parser.parse(choice([
			"The giant looks around the area with a wary eye, then lopes off to destinations unknown."
		]))

		self.death = Parser.parse(choice([
			"The giant wobbles unsteadily for a moment, then crashes backward into the earth sending out a small tremor."
		]))

		self.loot: Dict[str, float] = {
			"rock": 0.7,
			"sledgehammer": 0.2,
			"spear": 0.2
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		# TODO: Add damage to the hugger
		responses = [
			"$n approaches the giant for a $c. The giant flicks $n away with a rumbling chuckle."
		]
		return Parser.parse(choice(responses), name, invocation)
