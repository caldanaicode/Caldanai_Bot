from typing import Union

from discord import Embed, File
from ..dice import quick_roll
from .item import Item
from .rarity import Rarity
from ....db.db import MongoDB
from bson.objectid import ObjectId


class Weapon(Item):
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
			atk: str = "1d4",
			twohands: bool = False,
			atkmsg: str = None,
			bonus: int = None,
			article: str = None
	):
		super().__init__(iid, tid, pid, name, desc, weight, value, image, rarity, article)
		self.attack = atk.lower()
		self.isTwoHanded = twohands
		self.attackMessage = atkmsg
		self.itemType = 'Weapon'

		dice = int(self.attack.split('d')[0])
		self.bonus = bonus or (round(dice * self.rarity.multiplier) if self.rarity.name != 'junk' else 0)

	def get_attack_damage(self):
		return quick_roll(self.attack) + self.bonus

	def get_embed(self) -> tuple:
		embed = Embed(
			title=f"{'' if self.article is None else self.article + ' '}{self.name}",
			description=self.description, color=self.rarity.color
		)
		file = None
		if self.image is not None:
			file = File(f"./Caldanai/images/{self.image}", filename=self.image)
			embed.set_thumbnail(url=f"attachment://{self.image}")

		fields = (
			("Attack", f"{self.attack} +{self.bonus}", True),
			("Is Two-Handed", self.isTwoHanded, True),
			("Rarity", self.rarity.name.title(), True),
			("Weight", self.weight, True),
			("Value", self.value, True)
		)
		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)

		return embed, file

	def to_dict(self):
		d = super().to_dict()
		d['bonus'] = self.bonus

		return d

	@classmethod
	def from_dict(cls, d: dict):
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
			article=d['article'] if 'article' in d.keys() else None,
			atk=d['attack'] if 'attack' in d.keys() else None,
			twohands=d['isTwoHanded'] if 'isTwoHanded' in d.keys() else False,
			atkmsg=d['attackMessage'] if 'attackMessage' in d.keys() else None,
			bonus=d['bonus'] if 'bonus' in d.keys() else None
		)

	@classmethod
	def load(cls, item) -> Union['Weapon', None]:
		if isinstance(item, ObjectId):
			item = MongoDB.items.find_one({'_id': item})

		if item is None:
			return None

		template = MongoDB.templates_items.find_one({'_id': item['templateId']})
		if template is None:
			print(f"Error loading template ID: {item['templateId']}")
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
			article=template['article'],
			atk=template['attack'],
			twohands=template['isTwoHanded'],
			atkmsg=template['attackMessage'],
			bonus=item['bonus']
		)
