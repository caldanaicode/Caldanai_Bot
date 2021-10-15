import random
from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="bandit",
			atk="1d8",
			defense="1d12",
			dodge="1d12",
			health="1d12"
		)

		self.image = "bandit128.png"
		self.aggression = "vengeful"
		self.arrival = f"A masked bandit {choice('stealthily|clumsily|quickly|slowly'.split('|'))} " \
					   f"{choice('walks|saunters|sashays|sneaks'.split('|'))} out of the " \
					   f"{choice('bushes|rocks|distance|shadows'.split('|'))}."

		self.flavor = choice([
			"Your money or your life.",
			"This is a stick up.",
			"You'll never take me alive."
		])

		self.escape = choice([
			"The bandit runs off, taking whatever she can grab.",
			"Other horizons call the bandit away."
		])

		self.death = choice([
			"The bandit dies, and shall no longer steal from the rich and give to the poor.",
			"The bandit coughs blood before collapsing to the ground.",
			'"In another life, you could have been me," the bandit gasps with her dying breath.'
		])

		self.loot: Dict[str, float] = {
			"shortsword": 0.2,
			"bandana": 0.2,
			"bow": 0.15,
			"cheese sandwich": 0.2,
			"wallet": 0.25
		}

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
