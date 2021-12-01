from random import randint
from typing import Tuple

from random import choice

from Caldanai.lib.rpg import Monster, parse
from Caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.dice import Dice


class MonsterPlugin(Monster):
	def __init__(self):
		super().__init__(
			name="vampire",
			atk="4d4",
			defense="1d4",
			dodge="1d10",
			health_max="50d4"
		)

		self.time_partition = TimePartitions.NOCTURNAL
		self.dies_from_time = True
		self.time_death = "The @1 cries out in unimaginable pain as the light of day rolls over @1a body. Just as " \
			"the sound becomes unbearable, @1s suddenly goes still, and @1a form explodes into a shower of miniature " \
			"meteorites sailing in all directions."
		self.flees_from_time = True
		self.time_flee = "As the light of dawn approaches, the @1 hisses with frustration, clearly unsatisfied " \
			"with the night's hunt. With a final glare, @1s fades into a ball of shadow and zips away."
		self.image = None
		self.aggression = AggressionLevels.RAMPAGE
		self.arrival = "Shadows coalesce into a humanoid shape as a @1 materializes. @1ac hungry gaze sweeps the area."

		self.flavor = choice([
			"The @1 radiates malevolent hunger.",
			"@1ac gaze is as sharp as @1a teeth.",
			"The shadows shifting about this @1 produce an aura of cold dread, as if defying the very existence of life."
		])

		self.escape = choice([
			"With nary a sound, the @1 slips back into the darkness.",
			"The @1 melts into a pool of shadows, vanishing into the night.",
			"The @1 explodes into a cloud of bats, scattering in all directions."
		])

		self.death = choice([
			"The @1 screeches horribly as @1s bursts into flame. Soon, naught remains but ash.",
			"With a final gasp of disbelief, the @1 slows to a halt as dark tendrils spread outward from @1a chest. "
			"After a moment, the husk crumbles and drifts away.",
		])

		self.loot['cape'] = 0.2
		self.loot['high-collared_cape'] = 0.1

	def feed(self, target: Creature) -> str:
		"""
		Attempts to feed from a target, regenerating its own health.

		:param target: The creature being targeted.
		:return: A string indicating the results of the feeding
		"""

		amount = randint(1, target.health)
		attempt = Dice.quick_roll("1d20") + 4
		msg = "The @1's eyes darken as @1a gaze settles upon @2. With a burst of unbelievable speed, " \
			"the @1's form blurs as @1s rushes headlong at @1a victim."
		
		if attempt >= target.get_dodge():
			msg += "\n\n@2 stands paralyzed before the @1, and cries out as fangs plunge into " \
				"@2a throat."

			if m := target.apply_damage(amount):
				msg += f"\n\n{m}"
			else:
				msg += f"\n\n**@2 is drained of {amount} health!**"

			msg += "\n\nThe @1 licks the blood from @1a lips, and a wicked smile carves a path across @1a face as " \
				"wounds begin to mend."
			self.apply_damage(amount * -2)

		else:
			msg += "\n\nAmazingly, @2's quick reflexes see @2o safely out of harm's way!"

		return parse(msg, self, target)

	def on_hugged(self, actor: Creature, invocation: str) -> str:
		responses = [
			"An overwhelming sense of foreboding roots @2 in place.",
			"The hungry, piercing gaze of the @1 paralyzes @2.",
			f"The @1 smiles seductively at @2, encouraging the {invocation}..."
		]

		response = choice(responses)
		if response == responses[2]:
			response += f"\n{self.feed(actor)}"

		return response

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		if was_alive and self.is_dead():
			return self.death

		return ""

	def do_attack(self, creature: "Creature") -> Tuple[str, int]:
		if self.health / self.health_max <= 0.5:
			return self.feed(creature), 0
		return super().do_attack(creature)
