import importlib
from typing import Tuple

from discord import Embed, File
from random import randint

from Caldanai.Logger import stdout
from Caldanai.lib.rpg.inventory.rarity import Rarity, Rarities
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
			plural: str = None,
			stackable: bool = False,
			count: int = 1,
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
		self.plural = plural
		self.description = desc
		self.unit_weight = max(0.0, unit_weight)
		self.unit_value = round(max(0, unit_value) * self.rarity.multiplier)
		self.image = image
		self.stackable = stackable
		self.count = count
		self.plugin = plugin or name
		self.item_type = item_type

	def get_weight(self) -> float:
		if self.stackable:
			return self.unit_weight * self.count
		return self.unit_weight

	def get_value(self) -> int:
		if self.stackable:
			return self.unit_value * self.count
		return self.unit_value

	def can_stack(self, other: "Item"):
		return self.stackable \
				and self.id != other.id \
				and self.item_type == other.item_type \
				and self.rarity == other.rarity \
				and self.plugin == other.plugin

	def stack(self, other: "Item") -> bool:
		if not self.can_stack(other):
			return False

		self.count += other.count
		return True

	def get_article_or_count(self, next_word: str = None, count: int = None) -> str:
		exclusions = ['unique']
		if next_word is not None \
				and next_word not in exclusions \
				and next_word[0] in 'aeiouh' \
				and self.article == 'a'\
				and (count == 1 or self.count == 1):
			return f'an {next_word}'

		if count is not None and count != 1 or self.count != 1:
			return f'{count if count is not None else self.count} {next_word}'

		return f'{self.article} {next_word}'

	def get_full_name(self, count: int = None) -> str:
		return f"{self.get_article_or_count(self.rarity.name, count)} {self.name if self.count == 1 else self.plural}"

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

	def use(self, user) -> Tuple[str, bool]:
		return "There doesn't seem to be a way to do that.", True

	def to_dict(self) -> dict:
		"""Returns the database-friendly dictionary for this item."""

		d = {
			'_id': self.id,
			'rarity': self.rarity.name,
			'plugin': self.plugin,
			'item_type': self.item_type
		}

		if self.stackable:
			d['count'] = self.count

		if self.id is None:
			del d['_id']
		return d

	@classmethod
	def from_plugin(cls, plugin_name: str, data: dict):
		"""Creates a new item from a plugin with initial data."""

		try:
			item = importlib.import_module(f'Caldanai.lib.rpg.inventory.items.{plugin_name}').ItemPlugin(
				data['_id'] if '_id' in data.keys() else None,
				Rarities.from_name(data['rarity']) if 'rarity' in data.keys() else None,
				data['count'] if 'count' in data.keys() else 1
			)

			return item

		except:
			stdout(f"Unable to load ItemPlugin: {data}")
			return None
