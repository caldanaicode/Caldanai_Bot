from random import random, choice
from typing import Union, Optional, Dict

from discord import Embed, File

from Caldanai.db.db import MongoDB
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.inventory.item import Item
from Caldanai.lib.rpg.inventory.weapon import Weapon


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
			health: Optional[Union[str, int]],
			gender: Optional[str] = None,
			pronouns: Optional[str] = None
	):
		"""
		Creates a new instance of a creature object.

		:param name: The creature's name or noun. Defaults to ''.
		:param atk: The creature's attack strength as an ndn string. Defaults to '1d4'.
		:param defense: The creature's defense strength as an integer or ndn string. Defaults to 1.
		:param dodge: The creature's dodge ability as an integer or ndn string. Defaults to 1.
		:param health: The creature's max health as an integer or ndn string. Defaults to 1.
		:param gender: The creature's gender as a string. Will randomly choose between 'male' and 'female' for NPCs	if not provided. For players, the gender can be defined by the player.
		:param pronouns: The creature's pronouns as a comma-separated string in the format of 'subject, object,	possessive'. For example, a female's pronouns will default to 'she, her, hers' if no pronouns are provided.
		"""
		self.name = name or ''
		self.attack = atk or '1d4'
		self.defense = Dice.quick_roll(defense) if isinstance(defense, str) else defense if defense else 1
		self.dodge = Dice.quick_roll(dodge) if isinstance(dodge, str) else dodge if dodge else 1
		self.health_max = Dice.quick_roll(health) if isinstance(health, str) else health if health else 1
		self.health = self.health_max
		self.flavor = ''
		self.image = None
		self.clarks = 0
		self.loot: Dict[str, float] = {}
		self.gender: Optional[str] = gender or choice(['male', 'female'])
		self.is_dirty: bool = False
		if pronouns:
			s = pronouns.split(',')
			self.pronouns: Dict[str, str] = {
				'subject': s[0].strip(),
				'object': s[1].strip(),
				'possessive': s[2].strip()
			}
		else:
			self.pronouns: Dict[str, str] = {
				'subject': 'he' if self.gender == 'male' else 'she' if self.gender == 'female' else 'it',
				'object': 'him' if self.gender == 'male' else 'her' if self.gender == 'female' else 'it',
				'possessive': 'his' if self.gender == 'male' else 'her' if self.gender == 'female' else 'its'
			}

	def get_embed(self) -> tuple:
		"""
		Generates a discord embed and image file for displaying information about this creature.

		:return: A tuple containing (Embed, File) for the creature's details
		"""

		embed = Embed(
			title=f'{self.name.title()}',
			description=self.flavor,
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
		for item, frequency in self.loot.items():
			if random() <= frequency:
				i = MongoDB.templates_items.find_one({'name': item})
				if i is not None:
					i['templateId'] = i['_id']
					del i['_id']
					if i['itemType'] == 'Item':
						items.append(Item.from_dict(i))
					elif i['itemType'] == 'Weapon':
						items.append(Weapon.from_dict(i))
		return items

	def on_hugged(self, actor: "Creature", invocation: str) -> str:
		"""
		Gets a creature's reaction to being hugged.

		:param actor: The Creature object initiating the hug.
		:param invocation: The calling command, such as 'hug', 'cuddle', or 'snuggle'.
		:return: A string representing the creature's reaction.
		"""
		if self.is_dead():
			return f"{self.name.capitalize()}'s corpse rolls lifelessly in {actor.name}'s arms."
		return f"The {self.name} glances at {actor.name} and sidesteps {actor.pronouns['possessive']} hug."

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
