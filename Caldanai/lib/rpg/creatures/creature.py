from random import random
from typing import Union, Optional, Dict

from discord import Embed, File

from Caldanai.db.db import MongoDB
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.inventory.item import Item
from Caldanai.lib.rpg.inventory.weapon import Weapon


class Creature:
	def __init__(
			self,
			name: Optional[str],
			atk: Optional[str],
			defense: Optional[Union[str, int]],
			dodge: Optional[Union[str, int]],
			health: Optional[Union[str, int]]
	):
		self.name = name or ''
		self.attack = atk or '1d4'
		self.defense = Dice.quick_roll(defense) if isinstance(defense, str) else defense if defense else 1
		self.dodge = Dice.quick_roll(dodge) if isinstance(dodge, str) else dodge if dodge else 1
		self.health = Dice.quick_roll(health) if isinstance(health, str) else health if health else 1
		self.flavor = ''
		self.image = None
		self.loot: Dict[str, float] = {}

	# Returns an embed populated with the creature's details.
	def get_embed(self) -> tuple:
		"""Returns a tuple containing (Embed, File) for the creature's details"""

		embed = Embed(
			title=self.name.title(),
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
			("Health", self.health, True)
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

	# Reacts to hugs.
	def on_hugged(self, name: str, invocation: str) -> str:
		return f"The {self.name} ignores the hug."
