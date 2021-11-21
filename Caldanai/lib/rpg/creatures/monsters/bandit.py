import random
from typing import Dict, List

from random import choice

from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


class MonsterPlugin(Monster):
	def __init__(self):
		super().__init__(
			name="bandit",
			atk="1d8",
			defense="1d12",
			dodge="1d12",
			health_max="1d12"
		)

		self.time_partition = TimePartitions.CATHEMERAL
		self.image = "bandit128.png"
		self.aggression = AggressionLevels.VENGEFUL
		self.arrival = f"A masked bandit {choice('stealthily|clumsily|quickly|slowly'.split('|'))} " \
					   f"{choice('walks|saunters|sashays|sneaks'.split('|'))} out of the " \
					   f"{choice('bushes|rocks|distance|shadows'.split('|'))}."

		self.flavor = choice([
			"Your money or your life.",
			"This is a stick up.",
			"You'll never take me alive."
		])

		self.escape = choice([
			f"The bandit runs off, taking whatever {self.pronouns['subject']} can grab.",
			"Other horizons call the bandit away."
		])

		self.death = choice([
			"The bandit dies, and shall no longer steal from the rich and give to the poor.",
			"The bandit coughs blood before collapsing to the ground.",
			f'"In another life, you could have been me," the bandit gasps with {self.pronouns["possessive"]} dying '
			f'breath.'
		])

		self.loot: List[Dict] = [
			{"plugin": "shortsword", "item_type": "Weapon", "frequency": 0.2},
			{"plugin": "bandanna", "item_type": "Armor", "frequency": 0.2},
			{"plugin": "bow", "item_type": "Weapon", "frequency": 0.15},
			{"plugin": "cheese_sandwich", "item_type": "Consumable", "frequency": 0.2},
			{"plugin": "wallet", "item_type": "Item", "frequency": 0.25}
		]

	def steal(self, target: Creature) -> str:
		"""
		Attempts to steal a creature's wealth.

		:param target: The creature being targeted.
		:return: A string indicating the results of the theft.
		"""

		amount = random.randint(1, int(target.clarks / 10))
		attempt = Dice.quick_roll("1d20")
		if attempt >= target.dodge:
			target.give_clarks(-amount)
			return f"\n{target.name}'s wallet suddenly feels lighter... {amount} clarks were lost!"
		return f"\n{target.name} easily avoids the bandit's groping fingers."

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		responses = [
			f"The bandit breaks down crying at the first affection {self.pronouns['subject']} has ever known, "
			f"as {actor.name} {invocation}s {self.pronouns['object']}.",
			f"The bandit graciously accepts {actor.name}'s {invocation} while reaching toward {actor.pronouns['possessive']} wallet...",
			f"The bandit sneers at {actor.name}'s attempt to {invocation} {self.pronouns['object']}."
		]

		response = choice(responses)
		if response == responses[1]:
			response += f"\n{self.steal(actor)}"

		return response

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
