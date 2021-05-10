from typing import Optional

from Caldanai.lib.rpg.creatures.monster import Monster


class RollData:
	"""
	Simple structure for packaging a die roll with skill bonus. NOT INTENDED FOR DIRECT USE!

	Please use AttackRoll or DamageRoll which inherit from this class.

	Attributes
	----------
	roll : int
		The natural roll with no bonuses applied.
	skillBonus : int
		The bonus applied due to skill level.
	result : int
		The result of the roll + bonus.
	"""

	def __init__(self, roll: int, skill_bonus: int):
		self.roll: int = roll
		self.skillBonus: int = skill_bonus
		self.result = roll + skill_bonus

	def to_dict(self) -> dict:
		return {
			"roll": self.roll,
			"skillBonus": self.skillBonus
		}

	@classmethod
	def load(cls, d: dict) -> Optional["RollData"]:
		if "roll" not in d.keys() or "skillBonus" not in d.keys():
			return None
		return cls(
			roll=d['roll'],
			skill_bonus=d['skillBonus']
		)


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

	def __init__(self, roll: int, skill_bonus: int):
		super().__init__(roll, skill_bonus)
		self.isCritical = roll == 20
		self.isFumble = roll == 1

	def __str__(self):
		return f"{self.roll}{' + ' + str(self.skillBonus) if self.skillBonus > 0 and not self.isFumble else ''}"

	def to_dict(self) -> dict:
		return super().to_dict()

	@classmethod
	def load(cls, d: dict) -> Optional["AttackRoll"]:
		if "roll" not in d.keys() or "skillBonus" not in d.keys():
			return None
		return cls(
			roll=d['roll'],
			skill_bonus=d['skillBonus']
		)


class DamageRoll(RollData):
	"""
	Simple structure for packaging an NdN roll with a skill bonus and a weapon bonus.
	"""

	def __init__(self, roll: int, skill_bonus: int, weapon_bonus: int):
		super().__init__(roll, skill_bonus)
		self.weaponBonus = weapon_bonus
		self.result += weapon_bonus

	def __str__(self):
		msg = f"{self.roll}"
		show_result = False
		if self.skillBonus != 0:
			msg += f" {'+' if self.skillBonus > 0 else '-'} {self.skillBonus}"
			show_result = True
		if self.weaponBonus != 0:
			msg += f" {'+' if self.weaponBonus > 0 else '-'} {self.weaponBonus}"
			show_result = True
		if show_result:
			msg += f" = {self.result}"

		return msg

	def to_dict(self) -> dict:
		d = super().to_dict()
		d['weaponBonus'] = self.weaponBonus
		return d

	@classmethod
	def load(cls, d: dict) -> Optional["DamageRoll"]:
		if "roll" not in d.keys() or "skillBonus" not in d.keys() or "weaponBonus" not in d.keys():
			return None
		return cls(
			roll=d['roll'],
			skill_bonus=d['skillBonus'],
			weapon_bonus=d['weaponBonus']
		)


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
			monster: Optional[Monster] = None,
			is_miss: bool = False
	):
		self.attack = attack
		self.damage = damage
		self.isMiss = is_miss or attack.isFumble or (monster is not None and attack.result < monster.dodge)
		self.isCritical = attack.isCritical
		self.isFumble = attack.isFumble
		self.result = damage.result * (0 if self.isMiss else 2 if self.attack.isCritical else 1)

	def get_hit_string(self):
		return f"{'FUMBLE' if self.isFumble else 'MISS' if self.isMiss else 'CRITICAL' if self.isCritical else 'HIT'}"

	def to_dict(self) -> dict:
		return {
			"attack": self.attack.to_dict(),
			"damage": self.damage.to_dict(),
			"isMiss": self.isMiss
		}

	@classmethod
	def load(cls, d: dict) -> Optional["CombinedRoll"]:
		if "attack" not in d.keys() or "damage" not in d.keys() or "isMiss" not in d.keys():
			return None

		return cls(
			attack=AttackRoll.load(d["attack"]),
			damage=DamageRoll.load(d["damage"]),
			is_miss=d["isMiss"]
		)
