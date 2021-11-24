from random import choice

from Caldanai.lib.rpg import get_random_direction
from Caldanai.lib.rpg.creatures.monsters import Monster
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature


class MonsterPlugin(Monster):
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
		self.aggression = AggressionLevels.VENGEFUL
		self.arrival = "A genetically improbable creature " \
			f"{choice('lurches|trudges|charges|walks|wanders'.split('|'))} " \
			f"in from the {get_random_direction()}."

		self.flavor = choice([
			"Legally distinct from any similarly-named creatures.",
			"Hoo.  Hoo.  A frickin' @1, that's who.",
			"Trust me, you don't want to know."
		])

		self.escape = "The @1, silent as a jackhammer, slips away."
		self.death = choice([
			"The @1 gives a final howl of pain and terror before crumpling to the ground.",
			"After a last-ditch effort to escape your fury, the @1 collapses into lifelessness.",
			"The abomination of nature will no more threaten your sense of reason."
		])

	# Reacts to hugs.
	def on_hugged(self, actor: Creature, invocation: str) -> str:
		return choice([
			"Are you really sure you want to do that, @2?",
			f"The @1 looks at @2 suspiciously before accepting the {invocation}.",
			f"{invocation.capitalize()}s do not work on @1, @2."
		])

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""
