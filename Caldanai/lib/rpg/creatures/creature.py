from typing import Union, Optional

from Caldanai.lib.rpg.helpers.dice import Dice


class Creature:
	def __init__(
			self,
			name: Optional[str],
			atk: Optional[str],
			defense: Optional[Union[str, int]],
			dodge: Optional[Union[str, int]],
			health: Optional[Union[str, int]]
	):
		self.name = name
		self.attack = atk
		self.defense = Dice.quick_roll(defense) if isinstance(defense, str) else defense if defense else 1
		self.dodge = Dice.quick_roll(dodge) if isinstance(dodge, str) else dodge if dodge else 1
		self.health = Dice.quick_roll(health) if isinstance(health, str) else health if health else 1
