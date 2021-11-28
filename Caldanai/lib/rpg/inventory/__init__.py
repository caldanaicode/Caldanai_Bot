from glob import glob
from os import path
from typing import Tuple, Dict, Optional, List, Union, Type

from Caldanai.lib.rpg.inventory.item import Item
from Caldanai.lib.rpg.inventory.equipment.armor import Armor
from Caldanai.lib.rpg.inventory.rarity import Rarities
from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.usables import Usable
from Caldanai.lib.rpg.inventory.usables.consumables import Consumable
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from bson.objectid import ObjectId
from math import fsum


class Inventory:
	ITEM_TYPES: Dict[str, Type[Union[Usable, Stackable, Weapon, Armor, Consumable]]] = {
		"armor": Armor,
		"consumable": Consumable,
		"consumables": Consumable,
		"stackable": Stackable,
		"stackables": Stackable,
		"usable": Usable,
		"usables": Usable,
		"weapon": Weapon,
		"weapons": Weapon
	}

	ITEMS: Dict[str, Type[Union[Usable, Stackable, Weapon, Armor, Consumable]]] = {}

	@staticmethod
	def discover_items():
		items = [
			filepath
			for filepath in glob("./Caldanai/lib/rpg/inventory/*/**/*.py", recursive=True)
			if not filepath.endswith("__init__.py")
		]

		for filepath in items:
			parts = filepath.split(path.sep)[1:]
			_name = parts[-1][:-3].lower()
			_type = parts[-2].lower()

			if _name not in Inventory.ITEMS.keys() and _type in Inventory.ITEM_TYPES.keys():
				Inventory.ITEMS[_name] = Inventory.ITEM_TYPES[_type]

	@staticmethod
	def load_item(name: Optional[str] = None, data: Optional[dict] = None):
		if not name and data and 'plugin' in data.keys():
			name = data['plugin']

		if name:
			if name not in Inventory.ITEMS.keys():
				Inventory.discover_items()

			if name in Inventory.ITEMS.keys():
				return Inventory.ITEMS[name].from_plugin(name, data or {})

		return None

	def __init__(self, contents: list = ()):
		self.__items: List[Item] = []
		for _item in contents:
			self.add(_item)

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

		_item = self[_id]
		if _item:
			self.__items.remove(_item)
			del _item

	def __len__(self) -> int:
		return len(self.__items)

	def add(self, _item: Item) -> None:
		"""
		Add an item to the inventory.

		:param _item: The item to add.
		"""

		stacked = False
		if isinstance(_item, Stackable):
			stack = next((i for i in self.__items if isinstance(i, Stackable) and _item.can_stack(i)), None)
			if stack is not None:
				stack.stack(_item)
				stacked = True

		if not stacked:
			if _item.id is None:
				_item.id = ObjectId()
			self.__items.append(_item)

	def remove(self, _item: Item, count: int = 1) -> None:
		"""
		Remove an item from the inventory.

		:param _item: The item to remove.
		:param count: The number to remove, if stackable and more than 1 exists.
		"""

		if isinstance(_item, Stackable):
			_item.count -= max(count, 0)
			if _item.count <= 0:
				del self[_item.id]
		else:
			del self[_item.id]

	def get_weight(self) -> float:
		"""Gets the total weight of the inventory."""
		return fsum([i.get_weight() for i in self.__items])

	def _get_by_index(self, index: int) -> Optional[Item]:
		"""Returns an item by index, rather than by key."""
		if 0 <= index < len(self):
			return self.__items[index]
		return None

	def _filter_by_name(self, f: str) -> Tuple[Item]:
		"""Returns a tuple of Items with names containing the provided string."""
		results = tuple(filter(lambda i: f.lower() in i.name, self.__items))
		return results

	def _filter_by_rarity(self, f: str) -> Tuple[Item]:
		"""Returns of tuple of Items with rarities matching the provided string."""
		results = tuple(filter(lambda i: f.lower() == i.rarity.name.lower(), self.__items))
		return results

	def filter(self, f: Union[str, int]) -> Tuple[Optional[Item]]:
		"""
		Returns a tuple of Items where name or rarity contain the provided string, or a tuple containing a single
		item if the item.n notation is used.
		"""

		results: Tuple[Optional[Item]] = None,

		if not f or f == '_':
			results = self.all()

		elif isinstance(f, int) or f.isnumeric():
			index = int(f) - 1
			results = self._get_by_index(index),

		elif _rarity := Rarities.from_name(f):
			results = *[i for i in self._filter_by_rarity(f)],

		elif '.' in f:
			f, flag, *_ = f.split('.')

			if flag and flag.isnumeric():
				r = self._filter_by_name(f)
				index = int(flag) - 1
				if 0 <= index < len(r):
					results = r[index],

			elif _rarity := Rarities.from_name(flag):
				results = *[i for i in self._filter_by_name(f) if i.rarity == _rarity],

		else:
			results = *tuple(set(self._filter_by_name(f)) | set(self._filter_by_rarity(f))),

		if len(results) > 0:
			return results
		return None,

	def all(self) -> Tuple[Item]:
		"""Returns a tuple containing all inventory items."""

		return tuple(self.__items)

	def to_list(self) -> List[Dict]:
		"""Returns a sorted and stacked list of items as data dictionaries."""

		tmp = sorted([i.to_dict() for i in self.__items], key=lambda d: d['plugin'])
		return tmp

	@classmethod
	def from_list(cls, data: List[Dict]):
		"""Creates an inventory from a list of data dictionaries."""

		items: List[Item] = []
		for d in data:
			_item = Inventory.load_item(data=d)
			if _item is not None:
				items.append(_item)

		return cls(items)


if not Inventory.ITEMS:
	Inventory.discover_items()
