from random import choice
from typing import Dict, List

from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature


class MonsterPlugin(Monster):
	def __init__(self):
		super().__init__(
			name="dragon",
			atk="3d10",
			defense="3d8",
			dodge="3d10",
			health_max="10d10"
		)

		self.time_partition = TimePartitions.CATHEMERAL
		self.image = None
		self.aggression = AggressionLevels.RAMPAGE
		self.arrival = "A piercing roar rocks the heavens, as a @1 swoops down out of the sky searching for prey."
		self.flavor = choice([
			"A massive red @1, smelling faintly of cinnamon and charcoal.",
			"Unconfirmed reports suggests that this @1 may, in fact, have 62 toes. However, no one can get close "
			"enough to actually count."
		])
		self.escape = "The @1 circles the area lazily before taking to the clouds, disappearing from sight."
		self.death = "The @1 gives a final bellow of rage and disbelief as @1s falls to the ground. @1pc thrashing " \
			"lasts but a moment, then all is still."

		self.loot: List[Dict] = [
			{"plugin": "small_gem", "item_type": "Item", "frequency": 0.7},
			{"plugin": "tee_shirt", "item_type": "Armor", "frequency": 0.2},
			{"plugin": "candy", "item_type": "Consumable", "frequency": 0.3},
			{"plugin": "heavy_stringed_instrument", "item_type": "Item", "frequency": 0.2},
			{"plugin": "mace", "item_type": "Weapon", "frequency": 0.3}
		]

	# Reacts to hugs.
	def on_hugged(self, actor: Creature, invocation: str) -> str:
		# TODO: Perhaps attack the hugger in some way.
		return "The @1 glowers hungrily at @2 and sends a wisp of flame in @2p direction."

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
