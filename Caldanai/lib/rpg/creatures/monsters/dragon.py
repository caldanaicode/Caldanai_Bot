from typing import Dict, List

from Caldanai.lib.rpg.creatures.monsters import AggressionLevels
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.time import TimePartitions


class Monster(Creature):
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
		self.arrival = "A piercing roar rocks the heavens, as a dragon swoops down out of the clouds searching for prey."
		self.flavor = "A massive red dragon, smelling faintly of cinnamon and charcoal."
		self.escape = "The dragon circles the area lazily before taking to the clouds, disappearing from sight."
		self.death = f"The dragon gives a final bellow of rage and disbelief as {self.pronouns['subject']} falls to " \
					 f"the ground. {self.pronouns['possessive'].capitalize()} thrashing lasts but a moment, " \
					 f"then all is still."

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
		return f"The dragon glowers hungrily at {actor.name}, and sends a wisp of flame in " \
			   f"{actor.pronouns['possessive']} direction."

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
