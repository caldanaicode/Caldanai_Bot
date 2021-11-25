from discord import Embed, File
from random import randint

from Caldanai.lib.rpg.inventory.rarity import Rarity
from Caldanai.lib.rpg.helpers.enums import Rarities
from bson.objectid import ObjectId


class Item:
	def __init__(
			self,
			iid: ObjectId = None,
			name: str = "",
			desc: str = "",
			unit_weight: float = 1.0,
			unit_value: int = 0,
			image: str = None,
			rarity: Rarity = None,
			article: str = None,
			plugin: str = None,
			item_type: str = "Item"
	):
		if rarity is None:
			self.rarity = Rarities.from_scale(randint(1, 100), 1, 100)
		else:
			self.rarity = rarity

		self.id = iid
		self.name = name
		self.article = article
		self.description = desc
		self.unit_weight = max(0.0, unit_weight)
		self.unit_value = round(max(0, unit_value) * self.rarity.multiplier)
		self.image = image
		self.plugin = plugin or name.replace(' ', '_').lower()
		self.item_type = item_type

	def get_weight(self) -> float:
		return self.unit_weight

	def get_value(self) -> int:
		return self.unit_value

	def get_article(self, next_word: str = None) -> str:
		exclusions = ('unique',)
		if next_word is not None \
				and next_word not in exclusions \
				and next_word[0] in 'aeiouh' \
				and self.article == 'a':
			return f'an {next_word}'
		return f'{self.article} {next_word}'

	def get_full_name(self) -> str:
		return f"{self.get_article(self.rarity.name)} {self.name}"

	def get_embed(self) -> (Embed, File):
		"""Returns a tuple containing an Embed and File object for this item."""

		embed = Embed(
			title=f"{self.get_full_name()}",
			description=self.description,
			color=self.rarity.color
		)

		file = None
		if self.image is not None:
			file = File(f"./site/static/images/{self.image}", filename=self.image)
			embed.set_thumbnail(url=f"attachment://{self.image}")

		fields = (
			("Rarity", self.rarity.name.title(), True),
			("Weight", self.get_weight(), True),
			("Value", self.get_value(), True)
		)

		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)
		return embed, file

	def to_dict(self) -> dict:
		"""Returns the database-friendly dictionary for this item."""

		d = {
			'_id': self.id,
			'rarity': self.rarity.name,
			'plugin': self.plugin,
			'item_type': self.item_type
		}

		if self.id is None:
			del d['_id']
		return d
