from discord import Embed, File
from random import choice, random
from .creature import Creature
from ..parser import Parser
from ..inventory.item import Item
from ..inventory.weapon import Weapon
from ....db.db import MongoDB


class Monster(Creature):
	def __init__(self, mDict: dict):
		name = mDict['name']
		attack = mDict['attack']
		defense = mDict['defense']
		dodge = mDict['dodge']
		health = mDict['health']

		super().__init__(name=name, atk=attack, defense=defense, dodge=dodge, health=health)
		self.image = mDict['image']
		self.arrival = Parser.parse(choice(mDict['arrivals']))
		self.flavor = Parser.parse(choice(mDict['flavors']))
		self.escape = Parser.parse(choice(mDict['escapes']))
		self.death = Parser.parse(choice(mDict['deaths']))
		self.hugs = mDict['hugs']
		self.loot = mDict['loot']
	
	# Returns an embed populated with the monster's details.
	def get_embed(self) -> tuple:
		"""Returns a tuple containing (Embed, File) for the monster's details"""
		embed = Embed(
			title=self.name.title(),
			description=self.flavor,
			color=0xffcc00
		)
		file = None
		if self.image is not None:
			file = File(f"./Caldanai/images/{self.image}", filename=self.image)
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
		return (embed, file)
	
	# Reacts to hugs.
	def receiveHug(self, name: str, invocation: str) -> str:
		return Parser.parse(choice(self.hugs), name, invocation)
	
	# Returns a list of loot items
	def getLoot(self) -> list:
		items = []
		for item, frequency in self.loot.items():
			if random() <= frequency:
				i = MongoDB.templates_items.find_one({ 'name': item })
				if i is not None:
					i['templateId'] = i['_id']
					del i['_id']
					if i['itemType'] == 'Item':
						items.append(Item.from_dict(i))
					elif i['itemType'] == 'Weapon':
						items.append(Weapon.from_dict(i))
		return items