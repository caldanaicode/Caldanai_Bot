from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="bearowl",
			atk="2d7",
			defense="3d8",
			dodge="1d10",
			health="10d4"
		)

		self.image = "owl128.png"
		self.arrival = Parser.parse(choice([
			"A genetically improbable creature {lurches|trudges|charges|walks|wanders} in from the {"
			"north|south|east|west}."
		]))

		self.flavor = Parser.parse(choice([
			"Legally distinct from any similarly-named creatures.",
			"Hoo.  Hoo.  A frickin' bearowl, that's who.",
			"Trust me, you don't want to know."
		]))

		self.escape = Parser.parse(choice([
			"The bearowl, silent as a jackhammer, slips away."
		]))

		self.death = Parser.parse(choice([
			"The bearowl gives a final howl of pain and terror before crumpling to the ground.",
			"After a last-ditch effort to escape your fury, the bearowl collapses into lifelessness.",
			"The abomination of nature will no more threaten your sense of reason."
		]))

		self.loot: Dict[str, float] = {
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		# TODO: Perhaps attack the hugger in some way.
		responses = [
			"Are you really sure you want to do that?",
			"The bearowl looks at $n suspiciously before accepting the $c.",
			"$cs do not work on bearowls, $n."
		]
		return Parser.parse(choice(responses), name, invocation)
