from random import random, choice
from typing import Union, Optional, Dict, Tuple, List

from discord import Embed, File

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import Pronouns
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll, CombinedRoll
from Caldanai.lib.rpg.inventory import Inventory


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
			pronouns: Optional[str] = None
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
		self.loot: List[Dict] = []
		self.gender: Optional[str] = gender or choice(['male', 'female'])
		self.is_dirty: bool = False

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
			self.pronouns: Dict[Pronouns, str] = {
				Pronouns.SUBJECTIVE: 'he' if self.gender == 'male' else 'she' if self.gender == 'female' else 'it',
				Pronouns.OBJECTIVE: 'him' if self.gender == 'male' else 'her' if self.gender == 'female' else 'it',
				Pronouns.POSSESSIVE: 'his' if self.gender == 'male' else 'hers' if self.gender == 'female' else 'its',
				Pronouns.ADJECTIVE: 'his' if self.gender == 'male' else 'her' if self.gender == 'female' else 'its',
				Pronouns.REFLEXIVE: 'himself' if self.gender == 'male' else 'herself' if self.gender == 'female' else 'itself'
			}

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

	# Returns a list of loot items
	def get_loot(self) -> list:
		items = []
		for data in self.loot:
			plugin = data['plugin'] if 'plugin' in data.keys() else None
			item_type = data['item_type'] if 'item_type' in data.keys() else None
			frequency = data['frequency'] if 'frequency' in data.keys() else -1.0
			if plugin and item_type and random() <= frequency:
				item = Inventory.load_plugin(data)
				if item:
					items.append(item)

		return items

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

	# Applies damage (or healing if amount is negative) to the creature's health.
	def apply_damage(self, amount: int) -> None:
		"""
		Applies damage (or healing if amount is negative) to the creature's health.

		:param amount: Integer representing the amount by which to adjust health.
		:return: None
		"""
		self.health -= amount
		self.health = max(0, self.health)
		self.health = min(self.health, self.health_max)

	# Returns a boolean indicating whether or not the creature's health is depleted.
	def is_dead(self) -> bool:
		"""
		Returns a boolean indicating whether or not the creature's health is depleted.

		:return: True if health <= 0, otherwise False.
		"""
		return self.health <= 0

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

	def do_attack(self, creature: "Creature") -> Tuple[str, int]:
		"""
		Performs an attack against the given creature, without modifying its attributes.

		Returns a tuple containing the attack message and the total damage done.
		"""

		attack = AttackRoll(skill_bonus=0)
		damage = DamageRoll(Dice.from_ndn(self.attack), 0, 0)
		defense = creature.get_defense() if creature.get_defense else creature.defense
		dodge = creature.get_dodge() if creature.get_dodge else creature.dodge
		combined = CombinedRoll(attack, damage, dodge)
		t_dmg = 0 if combined.isMiss else max(1, combined.result - defense)

		msg = f"**{self.name.capitalize()} attacks {creature.name}:**```diff\nAttack vs Dodge ({dodge}): " \
			f"\n{'-' if combined.isMiss else '+'}    {combined.attack} ({combined.get_hit_string()})"

		if not combined.isMiss:
			msg += f"\n\nDamage:\n{'-' if combined.isMiss else '+'}    {combined.damage} * " \
				   f"{'0' if combined.isMiss else '2' if combined.isCritical else '1'} = {combined.result}"

			msg += f"\n\nTotal ({combined.result}) vs Defense ({defense}) = {t_dmg}"

		msg += "```\n"
		return msg, t_dmg
