import importlib
from glob import glob
from os import path
from random import choice
from typing import Optional, Union, List, Dict

from Caldanai.lib.rpg import Creature, GameClock
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, TimesOfDay


class Monster(Creature):
	def __init__(
			self,
			name: Optional[str],
			atk: Optional[str],
			defense: Optional[Union[str, int]],
			dodge: Optional[Union[str, int]],
			health_max: Optional[Union[str, int]],
			health: Optional[int] = None,
			gender: Optional[str] = None,
			pronouns: Optional[str] = None
	):
		super().__init__(name, atk, defense, dodge, health_max, health, gender, pronouns)

		self.aggression = AggressionLevels.PASSIVE
		self.time_partition = TimePartitions.CATHEMERAL
		self.dies_from_time = False
		self.time_death = ""
		self.flees_from_time = False
		self.time_flee = ""
		self.arrival = ""
		self.flavor = ""
		self.escape = ""
		self.death = ""
		self.loot: List[Dict] = []

	@staticmethod
	def get_random_monster(clock: GameClock) -> 'Monster':
		monsters = [
			filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/rpg/creatures/monsters/*.py")
		]
		monsters.remove('__init__')
		time = TimesOfDay[clock.get_time_of_day().upper()].value

		while (
		monster := importlib.import_module(f'Caldanai.lib.rpg.creatures.monsters.{choice(monsters)}').MonsterPlugin()) \
				and not bool(time & monster.time_partition):
			continue

		return monster

