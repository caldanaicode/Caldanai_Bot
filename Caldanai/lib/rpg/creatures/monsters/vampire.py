import random
from typing import Dict, List, Tuple

from random import choice

from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="vampire",
			atk="4d4",
			defense="1d4",
			dodge="1d10",
			health_max="10d10"
		)

		self.time_partition = TimePartitions.NOCTURNAL
		self.dies_from_time = True
		self.time_death = f"The vampire cries out in unimaginable pain as the light of day rolls over " \
						  f"{self.pronouns['possessive']} body. Just as the sound becomes unbearable, " \
						  f"{self.pronouns['subject']} suddenly goes still, and {self.pronouns['possessive']} form " \
						  f"explodes into a shower of miniature meteorites sailing in all directions."
		self.flees_from_time = True
		self.time_flee = f"As the light of dawn approaches, the vampire hisses with frustration, clearly unsatisfied " \
						 f"with the night's hunt. With a final glare, {self.pronouns['subject']} fades into a ball of " \
						 f"shadow and zips away."
		self.image = None
		self.aggression = AggressionLevels.RAMPAGE
		self.arrival = f"Shadows coalesce into a humanoid shape as a vampire materializes. " \
					   f"{self.pronouns['possessive'].capitalize()} hungry gaze sweeps the area."

		self.flavor = choice([
			"The vampire radiates malevolent hunger.",
			f"{self.pronouns['possessive'].capitalize()} gaze is as sharp as {self.pronouns['possessive']} teeth.",
			"The shadows shifting about this vampire produce an aura of cold dread, as if defying the very existence "
			"of life."
		])

		self.escape = choice([
			"With nary a sound, the vampire slips back into the darkness.",
			"The vampire melts into a pool of shadows, vanishing into the night.",
			"The vampire explodes into a cloud of bats, scattering in all directions."
		])

		self.death = choice([
			f"The vampire screeches horribly as {self.pronouns['subject']} bursts into flame. Soon, naught remains "
			f"but ash.",
			f"With a final gasp of disbelief, the vampire slows to a halt as dark tendrils spread outward from "
			f"{self.pronouns['possessive']} chest. After a moment, the husk crumbles and drifts away.",
		])

		self.loot: List[Dict] = [
			# {"plugin": "shortsword", "item_type": "Weapon", "frequency": 0.2},
			# {"plugin": "bandanna", "item_type": "Armor", "frequency": 0.2},
			# {"plugin": "bow", "item_type": "Weapon", "frequency": 0.15},
			# {"plugin": "cheese_sandwich", "item_type": "Consumable", "frequency": 0.2},
			# {"plugin": "wallet", "item_type": "Item", "frequency": 0.25}
		]

	def feed(self, target: Creature) -> str:
		"""
		Attempts to feed from a target, regenerating its own health.

		:param target: The creature being targeted.
		:return: A string indicating the results of the feeding
		"""

		amount = random.randint(1, target.health)
		attempt = Dice.quick_roll("1d20") + 4
		msg = f"The vampire's eyes darken as {self.pronouns['possessive']} gaze settles upon {target.name}. With a " \
			  f"burst of unbelievable speed, the vampire's form blurs as it rushes headlong at " \
			  f"{self.pronouns['possessive']} victim."
		if attempt >= target.dodge:
			msg += f"\n{target.name} stands paralyzed before the vampire, and cries out as fangs plunge into " \
				   f"{target.pronouns['possessive']} throat."
			if m := target.apply_damage(amount):
				msg += f"\n{m}"
			msg += f"\nThe vampire licks the blood from {self.pronouns['possessive']} lips, and a wicked smile " \
				   f"carves a path across {self.pronouns['possessive']} face as wounds begin to mend."
			self.apply_damage(amount * -2)

		else:
			msg += f"\nAmazingly, {target.name}'s quick reflexes see {target.pronouns['subject']} safely out of " \
				   f"harm's way!"

		return msg

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		responses = [
			f"An overwhelming sense of foreboding roots {actor.name} in place.",
			f"The hungry, piercing gaze of the vampire paralyzes {actor.name}.",
			f"The vampire smiles seductively at {actor.name}, encouraging the {invocation}..."
		]

		response = choice(responses)
		if response == responses[2]:
			response += f"\n{self.feed(actor)}"

		return response

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""

	def do_attack(self, creature: "Creature") -> Tuple[str, int]:
		if self.health / self.health_max <= 0.5:
			return self.feed(creature), 0
		return super().do_attack(creature)
