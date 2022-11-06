from random import choice
from typing import Union, Optional, Dict, Tuple

from discord import Embed, File

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures.body_part import BodyPart
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import Pronouns, DamageTypes
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll, CombinedRoll


class Creature:
	"""
	An instance of a creature object.
	"""

	def __init__(
			self,
			name: Optional[str],
			atk: Optional[str],
			defense: Optional[Union[str, int]],
			dodge: Optional[Union[str, int]],
			health_max: Optional[Union[str, int]],
			health: Optional[int] = None,
			gender: Optional[str] = None,
			pronouns: Optional[str] = None,
			traits: Optional[Dict[DamageTypes, float]] = ()
	):
		"""
		Creates a new instance of a creature object.

		:param name: The creature's name or noun. Defaults to ''.
		:param atk: The creature's attack strength as an ndn string. Defaults to '1d4'.
		:param defense: The creature's defense strength as an integer or ndn string. Defaults to 1.
		:param dodge: The creature's dodge ability as an integer or ndn string. Defaults to 1.
		:param health_max: The creature's max health as an integer or ndn string. Defaults to 1.
		:param health: The creature's current health as an integer. Defaults to health_max.
		:param gender: The creature's gender as a string. Will randomly choose between 'male' and 'female' for NPCs	if
			not provided. For players, the gender can be defined by the player.
		:param pronouns: The creature's pronouns as a comma-separated string in the format of 'subject, object,
			possessive'. For example, a female's pronouns will default to 'she, her, hers' if no pronouns are provided.
		:param traits: Damage types and effectiveness against this creature.
		"""

		self.name = name or ''
		self.attack = atk or '1d4'
		self.defense = Dice.quick_roll(defense) if isinstance(defense, str) else defense if defense else 1
		self.dodge = Dice.quick_roll(dodge) if isinstance(dodge, str) else dodge if dodge else 1
		self.health_max = Dice.quick_roll(health_max) if isinstance(health_max,	str) else health_max if health_max else 1
		self.health = health if health is not None else self.health_max
		self.flavor = ''
		self.image = None
		self.clarks = 0
		self.gender: Optional[str] = gender or choice(['male', 'female'])
		self.is_dirty: bool = False
		self.pronouns: Dict[Pronouns, str] = {}
		self.traits: Dict[DamageTypes, float] = traits or {}

		if pronouns:
			s = pronouns.split(',')
			self.pronouns: Dict[Pronouns, str] = {
				Pronouns.SUBJECTIVE: s[0].strip(),
				Pronouns.OBJECTIVE: s[1].strip(),
				Pronouns.POSSESSIVE: s[2].strip(),
				Pronouns.ADJECTIVE: s[3].strip(),
				Pronouns.REFLEXIVE: s[1].strip() + 'self'
			}
		else:
			self.update_pronouns()

		# if stats:
		# 	for name, value in stats.items():
		# 		n = name.upper()
		# 		if n in Stats.__members__.keys():
		# 			if Stats[n] == Stats.ATTACK:
		# 				self.stats[Stats.ATTACK] = value or Stats.ATTACK['default']
		# 			else:
		# 				self.stats[Stats[n]] = value if isinstance(value, int) else Dice.quick_roll(value)
		# 				if Stats[n]['min']:
		# 					self.stats[Stats[n]] = max(self.stats[Stats[n]], Stats[n]['min'])
		#
		# for stat in Stats:
		# 	if stat not in self.stats.keys():
		#
		# 		self.stats[stat] = 1

	def get_trait_multiplier(self, dmg_type: DamageTypes) -> float:
		if not dmg_type:
			return 1.0

		if dmg_type in self.traits:
			return self.traits[dmg_type]

		highest = 0.0
		for trait in self.traits:
			if trait & DamageTypes.COMBINED:
				if not dmg_type & DamageTypes.COMBINED:
					continue
				if dmg_type & trait == trait:
					highest = max(self.traits[trait], highest)

			elif dmg_type & trait:
				highest = max(self.traits[trait], highest)

		return highest

	def apply_damage(self, amount: int) -> None:
		"""
		Applies damage (or healing if amount is negative) to the creature's health.

		:param amount: Integer representing the amount by which to adjust health.
		:return: None
		"""

		self.health -= amount
		self.health = max(0, self.health)
		self.health = min(self.health, self.get_health_max())

	def do_attack(
			self,
			target: "Creature",
			dmg_type: DamageTypes = None
	) -> Tuple[str, int]:
		"""
		Calculates an attack against the given creature, without modifying any attributes.

		Returns a tuple containing the attack message and the total damage done.
		"""
		attack = AttackRoll(skill_bonus=0)
		damage = DamageRoll(Dice.from_ndn(self.attack), 0, 0)
		msg, dmg = target.on_attacked(self, attack, damage, dmg_type)
		return msg, dmg

	def get_embed(self) -> tuple:
		"""
		Generates a discord embed and image file for displaying information about this creature.

		:return: A tuple containing (Embed, File) for the creature's details
		"""

		embed = Embed(
			title=f'{self.name.title()}',
			description=parse(self.flavor, self),
			color=0xffcc00
		)
		file = None
		if self.image is not None:
			file = File(f"./site/static/images/{self.image}", filename=self.image)
			embed.set_thumbnail(url=f"attachment://{self.image}")

		fields = [
			("Attack", self.attack, True),
			("Defense", self.defense, True),
			("Dodge", self.dodge, True),
			("Health", f"{self.health} / {self.health_max}", True)
		]

		for f, v, i in fields:
			if isinstance(v, int):
				v = f"{v:,}"
			embed.add_field(name=f, value=v, inline=i)
		return embed, file

	def get_defense(self) -> int:
		return self.defense

	def get_dodge(self) -> int:
		return self.dodge

	def get_health_max(self) -> int:
		return self.health_max

	def get_health_scale(self) -> float:
		return self.health / self.get_health_max()

	def give_clarks(self, amount: int) -> bool:
		"""
		Gives (or removes, if negative amount is passed) clarks to the creature.

		:param amount: The amount to adjust clarks by.
		:return: True if the exchange succeeded, otherwise False.
		"""
		if self.clarks + amount > 0:
			self.clarks += amount
			self.is_dirty = True
			return True
		return False

	# Returns a boolean indicating whether the creature's health is depleted.
	def is_dead(self) -> bool:
		"""
		Returns a boolean indicating whether the creature's health is depleted.

		:return: True if health <= 0, otherwise False.
		"""
		return self.health <= 0

	def on_attacked(
			self,
			actor: "Creature",
			atk_roll: AttackRoll,
			dmg_roll: DamageRoll,
			dmg_type: DamageTypes = None
	) -> Tuple[str, int]:
		"""
		Gets a creature's reaction to being attacked.

		:param actor: The creature performing the attack.
		:param atk_roll: The actor's attack roll.
		:param dmg_roll: The actor's damage roll.
		:param dmg_type: The incoming damage type.
		:return: A tuple containing a string representing this creature's reaction, and the total damage done.
		"""
		defense = self.get_defense()
		dodge = self.get_dodge()
		combined = CombinedRoll(atk_roll, dmg_roll, dodge)
		multiplier = self.get_trait_multiplier(dmg_type)
		sub_dmg = int(multiplier * combined.result)
		t_dmg = 0 if combined.isMiss else max(1, sub_dmg - defense)

		msg = f"**{actor.name.capitalize()} attacks {self.name}:**```diff\nAttack vs Dodge ({dodge}): " \
			f"\n{'-' if combined.isMiss else '+'}    {combined.attack} ({combined.get_hit_string()})"

		if not combined.isMiss:
			msg += f"\n\n{str(dmg_type).title() + ' ' if dmg_type else ''}Damage:\n{'-' if combined.isMiss else '+'}" \
				f"    {combined.damage}{' * 0' if combined.isMiss else ' * 2' if combined.isCritical else ''}" \
				f"{' * ' + str(multiplier) if multiplier != 1 else ''} = {sub_dmg}"

			msg += f"\n\nTotal ({sub_dmg}) vs Defense ({defense}) = {t_dmg}"

		msg += "```\n"
		return msg, t_dmg

	def on_hugged(self, actor: "Creature", invocation: str) -> str:
		"""
		Gets a creature's reaction to being hugged.

		:param actor: The Creature object initiating the hug.
		:param invocation: The calling command, such as 'hug', 'cuddle', or 'snuggle'.
		:return: A string representing the creature's reaction.
		"""
		if self.is_dead():
			return parse("@1c's corpse rolls lifelessly in @2's arms.", self, actor)
		return parse("The @1 glances at @2 and sidesteps @2a hug.", self, actor)

	def update_pronouns(self):
		"""Auto-updates the creature's pronouns, if the gender matches a preset."""
		if self.gender.lower() == 'male':
			self.pronouns[Pronouns.SUBJECTIVE] = 'he'
			self.pronouns[Pronouns.OBJECTIVE] = 'him'
			self.pronouns[Pronouns.POSSESSIVE] = 'his'
			self.pronouns[Pronouns.ADJECTIVE] = 'his'
			self.pronouns[Pronouns.REFLEXIVE] = 'himself'

		elif self.gender.lower() == 'female':
			self.pronouns[Pronouns.SUBJECTIVE] = 'she'
			self.pronouns[Pronouns.OBJECTIVE] = 'her'
			self.pronouns[Pronouns.POSSESSIVE] = 'hers'
			self.pronouns[Pronouns.ADJECTIVE] = 'her'
			self.pronouns[Pronouns.REFLEXIVE] = 'herself'

		elif self.gender.lower() == 'non-binary':
			self.pronouns[Pronouns.SUBJECTIVE] = 'they'
			self.pronouns[Pronouns.OBJECTIVE] = 'them'
			self.pronouns[Pronouns.POSSESSIVE] = 'theirs'
			self.pronouns[Pronouns.ADJECTIVE] = 'their'
			self.pronouns[Pronouns.REFLEXIVE] = 'themself'
