from typing import Tuple, Dict, Optional, List, Union

from .armor import Armor
from .consumables import Consumable
from .items import Item
from .weapons import Weapon
from bson.objectid import ObjectId
from math import fsum


class Inventory:
	def __init__(self, contents: list = ()):
		self.__items: List[Item] = []
		for item in contents:
			self.add(item)

	def __getitem__(self, _id: Union[str, ObjectId]) -> Optional[Item]:
		"""
		Retrieves an item from the inventory by ID.

		:param _id: The ID of the item to retrieve.
		:return: The item associated with the given ID, or None if the key is not found.
		"""
		if _id is None or (isinstance(_id, str) and len(_id) == 0):
			return None

		if isinstance(_id, str):
			return next((i for i in self.__items if str(i.id) == _id), None)

		if isinstance(_id, ObjectId):
			return next((i for i in self.__items if _id == i.id), None)

		return None

	def __delitem__(self, _id: Union[str, ObjectId]) -> None:
		"""
		Removes an item from the inventory by ID.

		:param _id: The ID of the item to remove.
		:return: None
		"""

		if _id is None or (isinstance(_id, str) and len(_id) == 0):
			return None

		item = self[_id]
		if item:
			self.__items.remove(item)
			del item

	def __len__(self) -> int:
		return len(self.__items)

	def add(self, item: Item) -> None:
		"""
		Add an item to the inventory.

		:param item: The item to add.
		"""

		stacked = False
		if item.stackable:
			stack = next((i for i in self.__items if item.can_stack(i)), None)
			if stack is not None:
				stack.stack(item)
				stacked = True

		if not stacked:
			if item.id is None:
				item.id = ObjectId()
			self.__items.append(item)

	def remove(self, item: Item, count: int = 1) -> None:
		"""
		Remove an item from the inventory.

		:param item: The item to remove.
		:param count: The number to remove, if stackable and more than 1 exists.
		"""

		if not item.stackable or item.count <= 1:
			del self[item.id]
		else:
			self[item.id].count -= max(count, 0)
			if self[item.id].count <= 0:
				del self[item.id]

	def get_weight(self) -> float:
		"""Gets the total weight of the inventory."""
		return fsum([i.get_weight() for i in self.__items])

	def get_by_index(self, index: int) -> Item:
		"""Returns an item by index, rather than by key."""
		return self.__items[index]

	def filter_by_name(self, f: str) -> Tuple[Item]:
		"""Returns a tuple of Items with names containing the provided string."""
		results = tuple(filter(lambda i: f.lower() in i.name, self.__items))
		return results

	def filter_by_rarity(self, f: str) -> Tuple[Item]:
		"""Returns of tuple of Items with rarities matching the provided string."""
		results = tuple(filter(lambda i: f.lower() == i.rarity.name.lower(), self.__items))
		return results

	def filter(self, f: str) -> Tuple[Item]:
		"""
		Returns a tuple of Items where name or rarity contain the provided string, or a tuple containing a single
		item if the item.n notation is used.
		"""
		if not f:
			inv = self.all()
		else:
			if '.' in f:
				f, index, *_ = tuple(f.split('.'))
				index = int(index) - 1
				if 0 <= index < len(self):
					inv = (self.get_by_indexed_name(f, index),)
				else:
					inv = ()
			else:
				by_name = set(self.filter_by_name(f))
				by_rarity = set(self.filter_by_rarity(f))
				inv = tuple(by_name | by_rarity)

		return inv

	def get_by_indexed_name(self, name: str, index: int = 0) -> Optional[Item]:
		"""Returns an item by name and index of item in list of items with similar name."""
		results = self.filter_by_name(name)
		if 0 <= index < len(results):
			return results[index]
		return None

	def all(self) -> Tuple[Item]:
		"""Returns a tuple containing all inventory items."""

		return tuple(self.__items)

	def to_list(self) -> List[Dict]:
		"""Returns a sorted and stacked list of items as data dictionaries."""

		tmp = sorted([i.to_dict() for i in self.__items], key=lambda d: d['plugin'])
		return tmp

	@staticmethod
	def load_plugin(data: Dict) -> Item:
		item = None
		if 'plugin' in data.keys() and 'item_type' in data.keys():
			if data['item_type'] == 'Armor':
				item = Armor.from_plugin(data['plugin'], data)
			elif data['item_type'] == 'Consumable':
				item = Consumable.from_plugin(data['plugin'], data)
			elif data['item_type'] == 'Item':
				item = Item.from_plugin(data['plugin'], data)
			elif data['item_type'] == 'Weapon':
				item = Weapon.from_plugin(data['plugin'], data)
		return item

	@classmethod
	def from_list(cls, data: List[Dict]):
		"""Creates an inventory from a list of data dictionaries."""

		items: List[Item] = []
		for d in data:
			item = Inventory.load_plugin(d)
			if item is not None:
				items.append(item)

		return cls(items)
