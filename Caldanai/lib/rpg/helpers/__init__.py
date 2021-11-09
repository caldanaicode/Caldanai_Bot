import importlib
from glob import glob
from os import path
from random import choice


def get_random_direction() -> str:
	return choice([
		"north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"
	])


def get_random_monster():
	monsters = [
		filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/rpg/creatures/monsters/*.py")
	]
	monsters.remove('__init__')
	monster = importlib.import_module(f'Caldanai.lib.rpg.creatures.monsters.{choice(monsters)}').Monster()
	return monster
