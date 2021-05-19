from typing import Union

from .item import Item
from .weapon import Weapon
from ....Logger import stdout
from ....db.db import MongoDB
from bson.objectid import ObjectId
from math import fsum


class Inventory:
	def __init__(self, contents: list = ()):
		self.__contents = {}
		self.operations = []
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
		"""Add an item to the inventory and the database."""

		if item.id:
			MongoDB["items"].update_one(
				{'_id': item.id},
				{'$set': item.to_dict()}
			)

		else:
			item.id = MongoDB["items"].insert_one(item.to_dict()).inserted_id

		self.__contents[str(item.id)] = item

	# Remove an item from the inventory if it exists.
	def remove(self, item: Union[Item, Weapon]) -> None:
		"""Remove an item from the inventory and database."""

		del self.__contents[str(item.id)]
		MongoDB["items"].delete_one({'_id': item.id})
		del item

	# Returns the current inventory weight
	def get_weight(self) -> float:
		"""Gets the total weight of the inventory."""

		return fsum([i.weight for i in self.__contents.values()])

	# Returns an index and item from the inventory.
	def enumeration(self) -> enumerate:
		"""Returns an index, item enumeration for the inventory."""

		return enumerate(self.__contents.values())

	# Returns an item based on index, rather than key.
	def get_by_index(self, index: int) -> Union[Item, Weapon]:
		"""Returns an item by index, rather than by key."""

		for i, item in enumerate(self.__contents.values()):
			if i == index:
				return item

	# Returns all inventory items as a tuple.
	def all(self) -> tuple:
		"""Returns a tuple containing all inventory items."""

		return tuple(self.__contents.values())

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
				stdout(f"Failed to load item {item['_id']}")
			else:
				loaded.append(i)
		return cls(loaded)
