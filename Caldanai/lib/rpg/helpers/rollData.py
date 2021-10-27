from typing import Tuple

from Caldanai.lib.rpg.helpers.dice import Dice


class RollData:
	"""
	Simple structure for packaging a die roll with skill bonus. NOT INTENDED FOR DIRECT USE!

	Please use AttackRoll or DamageRoll which inherit from this class.

	Attributes
	----------
	rolls : Tuple
		The natural rolls with no bonuses applied.
	skillBonus : int
		The bonus applied due to skill level.
	result : int
		The result of the roll + bonus.
	"""

	def __init__(self, dice: Dice, skill_bonus: int):
		self.rolls: Tuple[int] = dice.rolls
		self.sides = dice.sides
		self.skillBonus: int = skill_bonus
		self.result = dice.value + skill_bonus


class AttackRoll(RollData):
	"""
	Simple structure for packaging a d20 roll with a skill bonus.

	Attributes
	----------
	isCritical : bool
		Whether or not the roll is a critical hit (natural 20).
	isFumble : bool
		Whether or not the roll is a fumble (natural 1).
	"""

	def __init__(self, skill_bonus: int):
		super().__init__(Dice(1, 20), skill_bonus)
		self.isCritical = self.rolls[0] == 20
		self.isFumble = self.rolls[0] == 1

	def __str__(self):
		return f"{' + '.join(str(r) for r in self.rolls)}" \
			f"{' + ' + str(self.skillBonus) if self.skillBonus > 0 and not self.isFumble else ''}"


class DamageRoll(RollData):
	"""
	Simple structure for packaging an NdN roll with a skill bonus and a weapon bonus.
	"""

	def __init__(self, dice: Dice, skill_bonus: int, weapon_bonus: int):
		super().__init__(dice, skill_bonus)
		self.weaponBonus = weapon_bonus
		self.result += weapon_bonus

	def __str__(self):
		msg = f"{'(' if len(self.rolls) > 1 or self.skillBonus or self.weaponBonus else ''}"\
			f"{' + '.join(str(r) for r in self.rolls)}"
		show_result = False
		if self.skillBonus != 0:
			msg += f" {'+' if self.skillBonus > 0 else '-'} {self.skillBonus}"
			show_result = True
		if self.weaponBonus != 0:
			msg += f" {'+' if self.weaponBonus > 0 else '-'} {self.weaponBonus}"
			show_result = True
		msg += f"{')' if len(self.rolls) > 1 or self.skillBonus or self.weaponBonus else ''}"
		if show_result:
			msg += f" = {self.result}"

		return msg


class CombinedRoll:
	"""
	A structure that packages together an AttackRoll and DamageRoll against monster data, providing easy access to
	interdependent data such as critical damage, fumbled damage.

	Attributes
	----------
	attack : AttackRoll
		Attack roll data
	damage : DamageRoll
		Damage roll data
	isMiss : bool
		True if the attack fumbles or misses.
	isCritical : bool
		True if the attack roll is a natural 20.
	isFumble : bool
		True if the attack roll is a natural 1.
	result : int
		The total of the damage accounting for miss/fumble, or critical hit multipliers.
	"""

	def __init__(
			self,
			attack: AttackRoll,
			damage: DamageRoll,
			dodge: int = 0,
			is_miss: bool = False
	):
		self.attack = attack
		self.damage = damage
		self.isMiss = not attack.isCritical and (is_miss or attack.isFumble or attack.result < dodge)
		self.isCritical = attack.isCritical
		self.isFumble = attack.isFumble
		self.result = damage.result * (0 if self.isMiss else 2 if self.attack.isCritical else 1)

	def get_hit_string(self):
		return f"{'FUMBLE' if self.isFumble else 'MISS' if self.isMiss else 'CRITICAL' if self.isCritical else 'HIT'}"
