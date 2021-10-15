import random
from typing import Dict

from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


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
		self.arrival = "The ground trembles slightly as a giant trudges in."
		self.flavor = f"This giant would blend in nicely with the surrounding rocks, if {self.pronouns['subject']} " \
					  f"would stop moving."
		self.escape = "The giant looks around the area with a wary eye, then lopes off to destinations unknown."
		self.death = "The giant wobbles unsteadily for a moment, then crashes backward into the earth sending out a " \
					 "small tremor."

		self.loot: Dict[str, float] = {
			"rock": 0.7,
			"sledgehammer": 0.2,
			"spear": 0.2
		}

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		dmg = Dice.quick_roll("1d4")
		attempt = Dice.quick_roll("1d20")
		msg = f"{actor.name} approaches the giant for a {invocation}. The giant flicks {actor.pronouns['object']} " \
			  f"away with a rumbling chuckle."
		if attempt >= actor.dodge:
			msg += f" {actor.name} takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
			actor.apply_damage(dmg)
		else:
			msg += f" {actor.name} tumbles deftly to avoid taking damage!"
		return msg
