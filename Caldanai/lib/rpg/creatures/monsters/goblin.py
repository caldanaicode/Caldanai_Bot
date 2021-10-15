from typing import Dict

from random import choice
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="goblin",
			atk="1d8",
			defense="1d10",
			dodge="1d10",
			health="1d20"
		)

		self.image = None
		self.arrival = choice([
			f"With a spluttering snarl, a goblin {choice('bursts|pads|runs'.split('|'))} into the area.",
			f"A screeching laugh shatters the serenity that once lingered here, as a goblin finds "
			f"{self.pronouns['possessive']} way hither."
		])

		self.flavor = choice([
			f"This goblin is so ugly {self.pronouns['subject']} is almost cute.",
			"A green and gray blob of stupidity."
		])

		self.escape = f"The goblin snorts, a vacant eye roaming the surroundings before {self.pronouns['subject']} " \
					  f"trudges off."
		self.death = f"The goblin's eyes bulge as if {self.pronouns['subject']} only now realized " \
					 f"{self.pronouns['subject']} was outmatched, and {self.pronouns['subject']} flops onto the " \
					 f"ground unceremoniously."

		self.loot: Dict[str, float] = {
			"stick": 0.5,
			"rock": 0.5,
			"spear": 0.1
		}

	# Reacts to hugs.
	def on_hugged(self, actor: Creature, invocation: str) -> str:
		msg = f"The goblin hoots at {actor.name} and backs away, flailing erratically."
		attempt = Dice.quick_roll('1d20')
		if attempt >= actor.dodge:
			dmg = Dice.quick_roll('1d4')
			msg += f" {actor.name} is caught off-guard and takes {dmg} point{'s' if dmg > 1 else ''} of damage!"
			actor.apply_damage(dmg)
		else:
			msg += f" {actor.name} narrowly avoids the goblin's thrashing!"

		return msg
