from typing import Union

from discord import Embed, File
from random import randint
from .rarity import Rarity, Rarities
from ....Logger import stdout
from ....db.db import MongoDB
from bson.objectid import ObjectId


class Item:
	def __init__(
			self,
			iid: ObjectId = None,
			tid: ObjectId = None,
			pid: ObjectId = None,
			name: str = "",
			desc: str = "",
			weight: float = 1.0,
			value: int = 0,
			image: str = None,
			rarity: Rarity = None,
			article: str = None
	):
		if rarity is None:
			self.rarity = Rarities.getRarityFromScale(randint(1, 100), 1, 100)
		else:
			self.rarity = rarity

		self.id = iid
		self.templateId = tid
		self.playerId = pid
		self.name = name
		self.article = article
		self.description = desc
		self.weight = max(0.0, weight)
		self.value = round(max(0, value) * self.rarity.multiplier)
		self.image = image
		self.itemType = 'Item'

	def __eq__(self, o):
		return isinstance(o, Item) and self.id == o.id

	def get_embed(self) -> (Embed, File):
		"""Returns a tuple containing an Embed and File object for this item."""

		embed = Embed(
			title=f"{'' if self.article is None else self.article + ' '}{self.name}",
			description=self.description,
			color=self.rarity.color
		)
		file = None
		if self.image is not None:
			file = File(f"./site/static/images/{self.image}", filename=self.image)
			embed.set_thumbnail(url=f"attachment://{self.image}")

		fields = (
			("Rarity", self.rarity.name.title(), True),
			("Weight", self.weight, True),
			("Value", self.value, True)
		)
		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)
		return embed, file

	def to_dict(self) -> dict:
		"""Returns the database-friendly dictionary for this item."""

		d = {
			'_id': self.id,
			'playerId': self.playerId,
			'templateId': self.templateId,
			'rarity': self.rarity.to_dict(),
		}
		if self.id is None:
			del d['_id']
		return d

	# Creates a new item from a dictionary
	@classmethod
	def from_dict(cls, d: dict):
		"""Creates a new item from a dictionary."""

		if d is None:
			return None

		return cls(
			iid=d['_id'] if '_id' in d.keys() else None,
			tid=d['templateId'] if 'templateId' in d.keys() else None,
			pid=d['playerId'] if 'playerId' in d.keys() else None,
			name=d['name'] if 'name' in d.keys() else None,
			desc=d['description'] if 'description' in d.keys() else None,
			weight=float(d['weight']) if 'weight' in d.keys() else 1.0,
			value=int(d['value']) if 'value' in d.keys() else 0,
			image=d['image'] if 'image' in d.keys() else None,
			rarity=Rarity.load(d['rarity']) if 'rarity' in d.keys() else None,
			article=d['article'] if 'article' in d.keys() else None
		)

	@classmethod
	def load(cls, item) -> Union['Item', None]:
		"""Loads an item from the database"""

		if isinstance(item, ObjectId):
			item = MongoDB.items.find_one({'_id': item})

		if item is None:
			return None

		template = MongoDB.templates_items.find_one({'_id': item['templateId']})
		if template is None:
			stdout(f"Error loading template ID: {item['templateId']}")
			return None

		return cls(
			iid=item['_id'],
			tid=template['_id'],
			pid=item['playerId'],
			name=template['name'],
			desc=template['description'],
			weight=float(template['weight']),
			value=int(template['value']),
			image=template['image'],
			rarity=Rarity.load(item['rarity']),
			article=template['article']
		)
