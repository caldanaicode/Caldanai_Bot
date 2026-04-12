from random import choice


def get_random_direction() -> str:
    return choice(["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"])
