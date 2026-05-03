from glob import glob
from os import path
from typing import Tuple, Dict, Optional, List, Union, Type

from caldanai.lib.rpg.inventory.item import Item
from caldanai.lib.rpg.inventory.equipment.armor import Armor
from caldanai.lib.rpg.inventory.stackables import Stackable
from caldanai.lib.rpg.inventory.usables import Usable
from caldanai.lib.rpg.inventory.usables.consumables import Consumable
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from caldanai.lib.rpg.helpers.enums import Qualities
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
        "weapons": Weapon,
    }

    ITEMS: Dict[str, Type[Union[Usable, Stackable, Weapon, Armor, Consumable]]] = {}

    @staticmethod
    def discover_items():
        """Scan ``caldanai/lib/rpg/inventory/`` for plugin files and
        register each one's stem in :attr:`ITEMS` against the
        appropriate base class.

        The category (armor / weapon / consumable / etc.) is read
        from whichever ancestor directory matches a known type in
        :attr:`ITEM_TYPES`, so set-organized subdirectories like
        ``armor/scrap/patchwork_bracer.py`` register as Armor the
        same way flat ``armor/cape.py`` does. Walk-up resolution
        means future per-set / per-tier subtrees nest freely
        without touching this method."""
        items = [
            filepath
            for filepath in glob("./caldanai/lib/rpg/inventory/*/**/*.py", recursive=True)
            if not filepath.endswith("__init__.py")
        ]

        for filepath in items:
            parts = filepath.split(path.sep)[1:]
            _name = parts[-1][:-3].lower()
            # Walk parent directories upward until we hit a recognized
            # type. For ``armor/scrap/patchwork_bracer.py`` the
            # immediate parent is ``scrap`` (unrecognized) and the
            # next is ``armor`` (recognized). For ``armor/cape.py``
            # the immediate parent is already ``armor``. Falls
            # through with no registration if no ancestor matches.
            _type = None
            for ancestor in reversed(parts[:-1]):
                if ancestor.lower() in Inventory.ITEM_TYPES.keys():
                    _type = ancestor.lower()
                    break

            if (
                _type is not None
                and _name not in Inventory.ITEMS.keys()
            ):
                Inventory.ITEMS[_name] = Inventory.ITEM_TYPES[_type]

    @staticmethod
    def load_item(name: Optional[str] = None, data: Optional[dict] = None):
        if name and not data:
            data = {"plugin": name}
        elif not name and data and "plugin" in data.keys():
            name = data["plugin"]

        if name:
            if name not in Inventory.ITEMS.keys():
                Inventory.discover_items()

            if name in Inventory.ITEMS.keys():
                item = Inventory.ITEMS[name].from_plugin(name, data or {})
                # Common attributes live here so subclass from_plugin
                # methods don't each need to thread them through.
                if item is not None and data and data.get("favorited"):
                    item.favorited = True
                return item

        return None

    def __init__(self, contents: list = ()):
        # Keyed by 1-based slot number. The slot is the user-visible
        # index in $inv output and the handle for $sell <n> /
        # $equip <n>. Slots are kept compact (1..N, no gaps) by
        # rekeying after every mutation; new items go to slot
        # ``len(self) + 1``. Insertion-ordered dict so iteration
        # order matches slot order.
        self.__items: Dict[int, Item] = {}
        for _item in contents:
            self.add(_item)

    def _rekey(self) -> None:
        """Compact ``__items`` to slots 1..N after a mutation that
        could leave gaps. Called from ``__delitem__`` / ``remove``.
        Insertion order is preserved, so the resulting slots match
        the prior iteration order minus the removed item."""
        self.__items = {
            new_key: item
            for new_key, item in enumerate(self.__items.values(), start=1)
        }

    def sort(self) -> int:
        """Re-slot every item by ``(plugin asc, quality desc)``.

        Same shape as :meth:`_rekey`, different ordering function:
        groups all instances of one plugin together, with the
        best-quality copy of each plugin landing at the lowest
        slot in its group. Quality sort uses the ``Qualities``
        ``multiplier`` value (range 0.75–2.0; masterwork high)
        which gives a clean numeric desc sort via negation.

        Items keep their identity — ``_id``, equipped placement
        (placement state lives on the ``Player.body`` tree, not
        on the slot), and ``favorited`` are properties of the
        ``Item`` instance. Loadouts reference items by ObjectId
        not slot, so saved loadouts are unaffected.

        Returns the count of items in the now-sorted inventory,
        for the cog command to surface back to the player.
        """
        items = sorted(
            self.__items.values(),
            key=lambda i: (i.plugin, -i.quality.value["multiplier"]),
        )
        self.__items = {
            new_key: item
            for new_key, item in enumerate(items, start=1)
        }
        return len(items)

    def __getitem__(self, _id: Union[str, ObjectId]) -> Optional[Item]:
        """
        Retrieves an item from the inventory by ID.

        :param _id: The ID of the item to retrieve.
        :return: The item associated with the given ID, or None if the key is not found.
        """
        if _id is None or (isinstance(_id, str) and len(_id) == 0):
            return None

        if isinstance(_id, str):
            return next((i for i in self.__items.values() if str(i.id) == _id), None)

        if isinstance(_id, ObjectId):
            return next((i for i in self.__items.values() if _id == i.id), None)

        return None

    def __delitem__(self, _id: Union[str, ObjectId]) -> None:
        """
        Removes an item from the inventory by ID. Rekeys the
        remaining items to keep slots compact at 1..N.

        :param _id: The ID of the item to remove.
        :return: None
        """

        if _id is None or (isinstance(_id, str) and len(_id) == 0):
            return None

        _item = self[_id]
        if _item:
            slot = next(
                (k for k, v in self.__items.items() if v is _item),
                None,
            )
            if slot is not None:
                del self.__items[slot]
                self._rekey()
            del _item

    def __len__(self) -> int:
        return len(self.__items)

    def __contains__(self, item: Item) -> bool:
        """Identity-based membership check. ``item in inventory``
        returns True iff the *exact same Item instance* is present
        — distinct from ``inventory[item.id] is not None`` which
        would falsely accept a sibling that shares an ObjectId
        through a doppy-clone harvest or any other dup-id path.
        2026-04-29 added so ``Player.take_item`` can verify
        possession without relying on id uniqueness."""
        return any(i is item for i in self.__items.values())

    def add(self, _item: Item) -> None:
        """
        Add an item to the inventory.

        :param _item: The item to add.
        """

        stacked = False
        if isinstance(_item, Stackable):
            stack = next(
                (
                    i for i in self.__items.values()
                    if isinstance(i, Stackable) and _item.can_stack(i)
                ),
                None,
            )
            if stack is not None:
                stack.stack(_item)
                stacked = True

        if not stacked:
            if _item.id is None:
                _item.id = ObjectId()
            # Slots are 1..N with no gaps thanks to ``_rekey`` on
            # remove, so the next free slot is always ``len + 1``.
            self.__items[len(self.__items) + 1] = _item

    def remove(self, _item: Item, count: int = 1) -> None:
        """
        Remove an item from the inventory.

        :param _item: The item to remove.
        :param count: The number to remove, if stackable and more than 1 exists.

        Identity-based slot lookup — ``del self[_item.id]`` would
        match the FIRST sibling sharing an ObjectId, removing the
        wrong instance when ids collide (e.g. doppy-clone harvest
        seeded the bag with a dup-id pair). 2026-04-29 fix.
        """

        if isinstance(_item, Stackable):
            _item.count -= max(count, 0)
            if _item.count > 0:
                return
        slot = next(
            (k for k, v in self.__items.items() if v is _item),
            None,
        )
        if slot is not None:
            del self.__items[slot]
            self._rekey()

    def get_weight(self) -> float:
        """Gets the total weight of the inventory."""
        return fsum([i.get_weight() for i in self.__items.values()])

    def _get_by_index(self, index: int) -> Optional[Item]:
        """Returns an item by 0-based position. Slots are 1..N
        internally, so position N maps to slot N+1."""
        if 0 <= index < len(self):
            return self.__items.get(index + 1)
        return None

    def _filter_by_name(self, f: str) -> Tuple[Item]:
        """Returns a tuple of Items whose name resolves against
        ``f`` via the shared fuzzy pass chain
        (exact → prefix → substring → edit-distance).

        Routes through :func:`fuzzy_match` with the same
        whitespace-token strategy used everywhere else, so item
        lookup gets the same prefix-wins / exact-wins invariant
        that body parts and monster names already enjoy: a literal
        ``wand`` exact-matches the inventory's ``wand`` and short-
        circuits past ``magic_wand`` substring noise. ``$equip wnd``
        catches the typo via edit-distance after the stricter
        passes return empty.

        ``.tightest`` picks the most-specific tier; the structured
        :class:`FuzzyResult` is available via :func:`fuzzy_match`
        directly for callers that want the autocomplete-style union
        view (none today, but the seam is here for it).
        """
        from caldanai.lib.rpg.helpers.fuzzy import fuzzy_match
        matches = fuzzy_match(
            f,
            list(self.__items.values()),
            keys=lambda i: [i.name] if i is not None else [],
            strategy="unordered",
            edit_distance=True,
        ).tightest
        return tuple(matches)

    def _filter_by_quality(self, f: str) -> Tuple[Item]:
        """Returns of tuple of Items with qualities matching the provided string."""
        results = tuple(filter(lambda i: f.lower() == i.quality.name.lower(), self.__items.values()))
        return results

    def filter(self, f: Union[str, int]) -> Tuple[Optional[Item]]:
        """
        Returns a tuple of Items where name or quality contain the provided string, or a tuple containing a single
        item if the item.n notation is used.
        """

        results: Tuple[Optional[Item]] = (None,)

        if not f or f == "_":
            results = self.all()

        elif isinstance(f, int) or f.isnumeric():
            index = int(f) - 1
            results = (self._get_by_index(index),)

        elif f.upper() in Qualities.__members__:
            results = (*[i for i in self._filter_by_quality(f)],)

        elif "." in f:
            parts = f.split(".")
            f, flag = parts[0], parts[1]
            tail = parts[2] if len(parts) > 2 else None

            if flag and flag.isnumeric():
                r = self._filter_by_name(f)
                index = int(flag) - 1
                if 0 <= index < len(r):
                    results = (r[index],)

            elif flag.upper() in Qualities.__members__:
                filtered = [i for i in self._filter_by_name(f) if i.quality == Qualities[flag.upper()]]
                if tail is not None and tail.isnumeric():
                    index = int(tail) - 1
                    if 0 <= index < len(filtered):
                        results = (filtered[index],)
                    else:
                        results = (None,)
                else:
                    results = (*filtered,)

        else:
            if f.upper() in Qualities.__members__:
                results = self._filter_by_quality(f)
            else:
                results = self._filter_by_name(f)

        if len(results) > 0:
            return results
        return (None,)

    def all(self) -> Tuple[Item]:
        """Returns a tuple containing all inventory items in slot
        order (1..N)."""

        return tuple(self.__items.values())

    def favorites(self) -> Tuple[Item]:
        """Returns the tuple of items flagged ``favorited``."""

        return tuple(i for i in self.__items.values() if i.favorited)

    def to_list(self) -> List[Dict]:
        """Returns a sorted and stacked list of items as data dictionaries."""

        tmp = sorted([i.to_dict() for i in self.__items.values()], key=lambda d: d["plugin"])
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
