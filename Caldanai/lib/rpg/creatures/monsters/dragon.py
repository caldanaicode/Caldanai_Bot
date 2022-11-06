from random import choice, sample, random
from typing import List

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes
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
			"Unconfirmed reports suggest that this @1 may, in fact, have 62 toes. However, no one can get close "
			"enough to actually count."
		])
		self.escape = "The @1 circles the area lazily before taking to the clouds, disappearing from sight."
		self.death = "The @1 gives a final bellow of rage and disbelief as @1s falls to the ground. @1ac thrashing " \
			"lasts but a moment, then all is still."

		self.traits[DamageTypes.RANGED] = 1.00
		self.traits[DamageTypes.PIERCING] = 0.75
		self.traits[DamageTypes.PIERCING | DamageTypes.RANGED | DamageTypes.COMBINED] = 1.50
		self.traits[DamageTypes.ALL ^ (DamageTypes.RANGED | DamageTypes.PIERCING)] = 0.5

		self.loot["small_gem"] = 0.7
		self.loot["tee_shirt"] = 0.2
		self.loot["candy"] = 0.3
		self.loot["heavy_stringed_instrument"] = 0.2
		self.loot["mace"] = 0.3

	# Reacts to hugs.
	def on_hugged(self, actor: Creature, invocation: str) -> str:
		# TODO: Perhaps attack the hugger in some way.
		return "The @1 glowers hungrily at @2 and sends a wisp of flame in @2a direction."

	def breath_attack(self, combatants) -> str:
		msg = parse(
			"The base of @1's throat glows brightly, @1a head drawing back slightly as @1s breathes in deeply. With a "
			"deafening roar, @1s looses a mighty column of liquid flame, blanketing the entire area.\n```diff",	self
		)
		post = ""
		for victim in combatants:
			raw = Dice.quick_roll("6d6")
			df = victim.get_defense()
			dmg = raw - df
			msg += parse(f"\n- @1 takes [{raw} - {df}] = {dmg} fire damage!", victim)
			if p := victim.apply_damage(dmg):
				post += f"{p}\n"

		return f"{msg}```{post}"

	def attack_random(self, combatants: list, count=1) -> str:
		if combatants and 0 < count <= len(combatants):
			if random() < 0.2:
				return self.breath_attack(combatants)

			return super().attack_random(combatants, count)

		return None
