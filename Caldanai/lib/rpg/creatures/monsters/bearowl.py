from random import choice

from Caldanai.lib.rpg import get_random_direction
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.time import TimePartitions


class Monster(Creature):
	def __init__(self):
		super().__init__(
			name="bearowl",
			atk="2d7",
			defense="3d8",
			dodge="1d10",
			health_max="10d4"
		)

		self.time_partition = TimePartitions.NOCTURNAL | TimePartitions.CREPUSCULAR
		self.image = "owl128.png"
		self.aggression = "vengeful"
		self.arrival = f"A genetically improbable creature " \
					   f"{choice('lurches|trudges|charges|walks|wanders'.split('|'))} " \
					   f"in from the {get_random_direction()}."

		self.flavor = choice([
			"Legally distinct from any similarly-named creatures.",
			"Hoo.  Hoo.  A frickin' bearowl, that's who.",
			"Trust me, you don't want to know."
		])

		self.escape = "The bearowl, silent as a jackhammer, slips away."
		self.death = choice([
			"The bearowl gives a final howl of pain and terror before crumpling to the ground.",
			"After a last-ditch effort to escape your fury, the bearowl collapses into lifelessness.",
			"The abomination of nature will no more threaten your sense of reason."
		])

	# Reacts to hugs.
	def on_hugged(self, actor: Creature, invocation: str) -> str:
		responses = [
			f"Are you really sure you want to do that, {actor.name}?",
			f"The bearowl looks at {actor.name} suspiciously before accepting the {invocation}.",
			f"{invocation.capitalize()}s do not work on bearowls, {actor.name}."
		]
		return choice(responses)

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
