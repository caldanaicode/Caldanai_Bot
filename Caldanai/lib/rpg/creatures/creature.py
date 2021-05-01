from ..dice import quick_roll


class Creature:
	def __init__(self, name: str = None, atk: str = None, defense=None, dodge=None, health=None):
		self.name = name
		self.attack = atk
		self.defense = quick_roll(defense) if isinstance(defense, str) else defense if isinstance(defense, int) else 1
		self.dodge = quick_roll(dodge) if isinstance(dodge, str) else dodge if isinstance(dodge, int) else 1
		self.health = quick_roll(health) if isinstance(health, str) else health if isinstance(health, int) else 1
