from random import choice, sample
from typing import Tuple

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll


class MonsterPlugin(Monster):
	def __init__(self):
		super().__init__(
			name="flying math teacher",
			atk="3d14",
			defense="3d6",
			dodge="3d6",
			health_max="3d14"
		)

		self.time_partition = TimePartitions.CREPUSCULAR | TimePartitions.NOCTURNAL
		self.image = None
		self.aggression = AggressionLevels.SURVIVE
		self.arrival = choice([
			"The smell of whiteboard dust and stress wafts into the area.",
			"Wax wings make an odd sound as they pummel the air."
		])

		self.flavor = choice([
			"This @1 has an impressive array of tiny sand timers.",
			"A confounding quantity of board games surrounds this @1.",
			"The @1 eyes you mistrustfully, as if expecting to see a graphing calculator in your hand.",
			'"What do you get when you cross an elephant with a grape?"\n|| |elephant| ⨉ |grape| ⨉ sin(θ)||',
			'"What do you get when you cross an elephant with a mountain climber?"\n||You can\'t, because a mountain '
			'climber is a scaler.||'
		])

		self.escape = choice([
			"The @1 issues homework assignments before vanishing back into the 9th dimension.",
			"Exhausted from a long day of dealing with idiots, the @1 takes to the skies.",
			'The @1 boldly declares, "Time\'s up! Pencils down!" @1s then stuffs @1a papers and board games into a '
			'dimensional pocket and flutters away.'
		])
		self.death = choice([
			"The @1 haltingly begins listing off the digits of π to the 900th decimal, trailing off after only a few.",
			"The students have surpassed the teacher, who can finally rest in peace."
		])

		self.traits[DamageTypes.BLUDGEONING] = 1.25
		self.traits[DamageTypes.ALL ^ DamageTypes.BLUDGEONING] = 1

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		return choice([
			f"The @1 waves a dissuading finger in the face of @2.",
			f"The @1 arches a cynical eyebrow and sidesteps @2."
		])

	@staticmethod
	def is_prime(number: int) -> bool:
		if number > 1:
			for i in range(2, int(number / 2) + 1):
				if number % i == 0:
					return False

			return True

		else:
			return False

	def attack_random(self, combatants: list, count=1) -> str:
		if combatants and 0 < count <= len(combatants):
			victims = sample(combatants, count)
			m = None
			for victim in victims:
				m, d = self.do_attack(victim, DamageTypes.MAGICAL)
				if d > 0:
					m += parse(victim.apply_damage(d), victim)

			return m

		return None

	def do_attack(self,	target: Creature, dmg_type: DamageTypes = None) -> Tuple[str, int]:
		print('Called do_attack from math_teacher.py')
		attack = AttackRoll(skill_bonus=0)
		damage = DamageRoll(Dice.from_ndn(self.attack), 0, 0)
		msg, dmg = target.on_attacked(self, attack, damage, DamageTypes.MAGICAL)
		if self.is_prime(dmg):
			dmg *= 2
			msg = msg[:-4] + f" __LORD OF PRIMES!__ * 2 = {dmg}```\n"
		return msg, dmg

	def on_attacked(
			self,
			actor: Creature,
			atk_roll: AttackRoll,
			dmg_roll: DamageRoll,
			dmg_type: DamageTypes = None
	) -> Tuple[str, int]:
		print('Called on_attacked from math_teacher.py')
		msg, dmg = super().on_attacked(actor, atk_roll, dmg_roll, dmg_type)
		if self.is_prime(dmg):
			dmg /= 2
			msg = msg[:-4] + f" __LORD OF PRIMES!__ / 2 = {dmg}```\n"
		return msg, dmg
