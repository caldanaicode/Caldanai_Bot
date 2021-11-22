from typing import Dict, List

from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


class MonsterPlugin(Monster):
	def __init__(self):
		super().__init__(
			name="giant",
			atk="2d10",
			defense="2d8",
			dodge="1d4",
			health_max="5d10"
		)

		self.time_partition = TimePartitions.DIURNAL
		self.image = None
		self.aggression = AggressionLevels.RAMPAGE
		self.arrival = "The ground trembles slightly as a giant trudges in."
		self.flavor = f"This giant would blend in nicely with the surrounding rocks, if {self.pronouns['subject']} " \
					  f"would stop moving."
		self.escape = "The giant looks around the area with a wary eye, then lopes off to destinations unknown."
		self.death = "The giant wobbles unsteadily for a moment, then crashes backward into the earth sending out a " \
					 "small tremor."

		self.loot: List[Dict] = [
			{"plugin": "rock", "item_type": "Weapon", "frequency": 0.7},
			{"plugin": "sledgehammer", "item_type": "Weapon", "frequency": 0.2},
			{"plugin": "spear", "item_type": "Weapon", "frequency": 0.2},
		]

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		dmg = Dice.quick_roll("1d4")
		attempt = Dice.quick_roll("1d20")
		msg = f"*{actor.name} approaches the giant for a {invocation}. The giant flicks {actor.pronouns['object']} " \
			  f"away with a rumbling chuckle.*"
		if attempt >= actor.dodge:
			msg += f" {actor.name} takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
			m = actor.apply_damage(dmg)
			msg += f"\n{m}" if len(m) > 0 else ""
		else:
			msg += f"\n*{actor.name} tumbles deftly to avoid taking damage!*"
		return msg

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
