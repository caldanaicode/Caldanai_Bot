from typing import Union

from .item import Item
from .weapon import Weapon
from ....db.db import MongoDB
from bson.objectid import ObjectId
from math import fsum


class Inventory:
	def __init__(self, contents: list = ()):
		self.__contents: dict = {}
		for item in contents:
			self.add(item)

	def __getitem__(self, key) -> Union[Item, Weapon, None]:
		if key is not None and key in self.__contents.keys():
			return self.__contents[key]
		return None

	def __len__(self) -> int:
		return len(self.__contents.keys())

	# Add an item to the inventory.
	def add(self, item: Union[Item, Weapon]) -> None:
		item.save()
		self.__contents[str(item.id)] = item

	# Remove an item from the inventory if it exists.
	def remove(self, item: Union[Item, Weapon]) -> None:
		del self.__contents[str(item.id)]
		MongoDB["items"].delete_one({'_id': item.id})

	# Returns the current inventory weight
	def get_weight(self) -> float:
		return fsum([i.weight for i in self.__contents.values()])

	# Returns an index and item from the inventory.
	def enumeration(self) -> enumerate:
		return enumerate(self.__contents.values())

	# Returns an item based on index, rather than key.
	def get_by_index(self, index: int) -> Union[Item, Weapon]:
		for i, item in enumerate(self.__contents.values()):
			if i == index:
				return item

	# Loads the inventory from a list of items
	@classmethod
	def load(cls, pid: ObjectId):
		loaded = []
		items = MongoDB.items.find({"playerId": pid})
		for item in items:
			t = MongoDB.templates_items.find_one({"_id": item['templateId']})
			i = None
			if t['itemType'] == 'Weapon':
				i = Weapon.load(item)
			elif t['itemType'] == 'Item':
				i = Item.load(item)
			if i is None:
				print(f"Failed to load item {item['_id']}")
			else:
				loaded.append(i)
		return cls(loaded)
