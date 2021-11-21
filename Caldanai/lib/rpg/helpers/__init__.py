import importlib
from glob import glob
from os import path
from random import choice

from Caldanai.lib.rpg.time import GameClock, TimesOfDay


def get_random_direction() -> str:
	return choice([
		"north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"
	])


def get_random_monster(clock: GameClock):
	monsters = [
		filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/rpg/creatures/monsters/*.py")
	]
	monsters.remove('__init__')
	time = TimesOfDay[clock.get_time_of_day().upper()].value
	while (monster := importlib.import_module(f'Caldanai.lib.rpg.creatures.monsters.{choice(monsters)}').Monster()) and\
					 not bool(time & monster.time_partition):
		continue

	return monster
