from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.parser import Parser


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
		self.arrival = Parser.parse(choice([
			"A masked bandit {stealthily|clumsily|quickly|slowly} {walks|saunters|sashays|sneaks} out of the {"
			"bushes|rocks|distance|shadows}."
		]))

		self.flavor = Parser.parse(choice([
			"Your money or your life.",
			"This is a stick up.",
			"You'll never take me alive."
		]))

		self.escape = Parser.parse(choice([
			"The bandit runs off, taking whatever she can grab.",
			"Other horizons call the bandit away."
		]))

		self.death = Parser.parse(choice([
			"The bandit dies, and shall no longer steal from the rich and give to the poor.",
			"The bandit coughs blood before collapsing to the ground.",
			'"In another life, you could have been me," the bandit gasps with her dying breath.'
		]))

		self.loot: Dict[str, float] = {
			"shortsword": 0.2,
			"bandana": 0.2,
			"bow": 0.15,
			"cheese sandwich": 0.2,
			"wallet": 0.25
		}

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		# TODO: Perhaps attack the hugger in some way, or steal from them
		responses = [
			"The bandit breaks down crying at the first affection she has ever known.",
			"The bandit graciously accepts $n's $c while reaching toward their wallet.",
			"The bandit sneers at $n's attempt to $c it."
		]
		return Parser.parse(choice(responses), name, invocation)
