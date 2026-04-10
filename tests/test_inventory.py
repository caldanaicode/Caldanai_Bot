"""Tests for Caldanai.lib.rpg.inventory.Inventory class."""

from unittest.mock import patch, MagicMock

import pytest
from bson.objectid import ObjectId

from Caldanai.lib.rpg.helpers.enums import Qualities
from Caldanai.lib.rpg.inventory import Inventory
from Caldanai.lib.rpg.inventory.item import Item
from Caldanai.lib.rpg.inventory.stackables import Stackable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_item(name="sword", weight=2.0, quality=Qualities.ORDINARY, iid=None):
    """Create a simple Item with a known quality so multiplier is predictable."""
    return Item(
        iid=iid or ObjectId(),
        name=name,
        unit_weight=weight,
        quality=quality,
        plugin="test_plugin",
    )


def _make_stackable(name="arrow", weight=0.1, quality=Qualities.ORDINARY, count=1, iid=None, plugin="arrow"):
    return Stackable(
        iid=iid or ObjectId(),
        name=name,
        plural=f"{name}s",
        unit_weight=weight,
        quality=quality,
        count=count,
        plugin=plugin,
    )


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_single_item(self):
        inv = Inventory()
        item = _make_item()
        inv.add(item)
        assert len(inv) == 1
        assert inv.all()[0] is item

    def test_add_assigns_id_when_none(self):
        inv = Inventory()
        item = _make_item()
        item.id = None
        inv.add(item)
        assert item.id is not None
        assert isinstance(item.id, ObjectId)

    def test_add_stackable_stacks_matching(self):
        inv = Inventory()
        s1 = _make_stackable(count=3)
        s2 = _make_stackable(count=5)
        inv.add(s1)
        inv.add(s2)
        # They should stack into one entry
        assert len(inv) == 1
        assert s1.count == 8

    def test_add_stackable_different_plugin_does_not_stack(self):
        inv = Inventory()
        s1 = _make_stackable(plugin="arrow")
        s2 = _make_stackable(plugin="bolt")
        inv.add(s1)
        inv.add(s2)
        assert len(inv) == 2

    def test_add_stackable_different_quality_does_not_stack(self):
        inv = Inventory()
        s1 = _make_stackable(quality=Qualities.ORDINARY)
        s2 = _make_stackable(quality=Qualities.FINE)
        inv.add(s1)
        inv.add(s2)
        assert len(inv) == 2


# ---------------------------------------------------------------------------
# remove()
# ---------------------------------------------------------------------------

class TestRemove:
    def test_remove_non_stackable_deletes_item(self):
        inv = Inventory()
        item = _make_item()
        inv.add(item)
        inv.remove(item)
        assert len(inv) == 0

    def test_remove_stackable_decrements_count(self):
        inv = Inventory()
        s = _make_stackable(count=5)
        inv.add(s)
        inv.remove(s, count=2)
        assert len(inv) == 1
        assert s.count == 3

    def test_remove_stackable_to_zero_removes_entry(self):
        inv = Inventory()
        s = _make_stackable(count=3)
        inv.add(s)
        inv.remove(s, count=3)
        assert len(inv) == 0

    def test_remove_stackable_below_zero_removes_entry(self):
        inv = Inventory()
        s = _make_stackable(count=2)
        inv.add(s)
        inv.remove(s, count=10)
        assert len(inv) == 0


# ---------------------------------------------------------------------------
# filter()
# ---------------------------------------------------------------------------

class TestFilter:
    def test_filter_by_name(self):
        inv = Inventory()
        inv.add(_make_item(name="iron sword"))
        inv.add(_make_item(name="iron shield"))
        inv.add(_make_item(name="gold ring"))
        results = inv.filter("iron")
        assert len(results) == 2

    def test_filter_by_numeric_index(self):
        inv = Inventory()
        a = _make_item(name="alpha")
        b = _make_item(name="bravo")
        inv.add(a)
        inv.add(b)
        results = inv.filter("1")
        assert results == (a,)

    def test_filter_underscore_returns_all(self):
        inv = Inventory()
        inv.add(_make_item(name="a"))
        inv.add(_make_item(name="b"))
        results = inv.filter("_")
        assert len(results) == 2

    def test_filter_empty_string_returns_all(self):
        inv = Inventory()
        inv.add(_make_item(name="x"))
        results = inv.filter("")
        assert len(results) == 1

    def test_filter_by_quality(self):
        inv = Inventory()
        inv.add(_make_item(name="a", quality=Qualities.FINE))
        inv.add(_make_item(name="b", quality=Qualities.JUNK))
        results = inv.filter("FINE")
        assert len(results) == 1

    def test_filter_dot_notation_numeric(self):
        inv = Inventory()
        inv.add(_make_item(name="iron sword"))
        inv.add(_make_item(name="iron dagger"))
        results = inv.filter("iron.1")
        assert len(results) == 1

    def test_filter_no_match_returns_none_tuple(self):
        inv = Inventory()
        inv.add(_make_item(name="sword"))
        results = inv.filter("nonexistent")
        assert results == (None,) or (len(results) == 0)


# ---------------------------------------------------------------------------
# __getitem__
# ---------------------------------------------------------------------------

class TestGetItem:
    def test_getitem_by_string_id(self):
        inv = Inventory()
        oid = ObjectId()
        item = _make_item(iid=oid)
        inv.add(item)
        assert inv[str(oid)] is item

    def test_getitem_by_objectid(self):
        inv = Inventory()
        oid = ObjectId()
        item = _make_item(iid=oid)
        inv.add(item)
        assert inv[oid] is item

    def test_getitem_missing_returns_none(self):
        inv = Inventory()
        inv.add(_make_item())
        assert inv[ObjectId()] is None

    def test_getitem_none_returns_none(self):
        inv = Inventory()
        assert inv[None] is None

    def test_getitem_empty_string_returns_none(self):
        inv = Inventory()
        assert inv[""] is None


# ---------------------------------------------------------------------------
# to_list / from_list round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_list_returns_sorted_dicts(self):
        inv = Inventory()
        i1 = _make_item(name="beta")
        i1.plugin = "beta"
        i2 = _make_item(name="alpha")
        i2.plugin = "alpha"
        inv.add(i1)
        inv.add(i2)
        result = inv.to_list()
        assert result[0]["plugin"] == "alpha"
        assert result[1]["plugin"] == "beta"

    @patch("Caldanai.lib.rpg.inventory.Inventory.load_item")
    def test_from_list_round_trip(self, mock_load):
        """from_list calls load_item for each dict; verify items end up in inventory."""
        item_a = _make_item(name="alpha")
        item_b = _make_item(name="bravo")
        mock_load.side_effect = [item_a, item_b]

        data = [{"plugin": "alpha", "quality": "ORDINARY"}, {"plugin": "bravo", "quality": "ORDINARY"}]
        inv = Inventory.from_list(data)
        assert len(inv) == 2
        assert mock_load.call_count == 2


# ---------------------------------------------------------------------------
# Weight calculation
# ---------------------------------------------------------------------------

class TestWeight:
    def test_total_weight_single(self):
        inv = Inventory()
        inv.add(_make_item(weight=3.5))
        assert inv.get_weight() == pytest.approx(3.5)

    def test_total_weight_multiple(self):
        inv = Inventory()
        inv.add(_make_item(weight=1.0))
        inv.add(_make_item(weight=2.5))
        assert inv.get_weight() == pytest.approx(3.5)

    def test_total_weight_with_stackable(self):
        inv = Inventory()
        inv.add(_make_stackable(weight=0.5, count=10))
        assert inv.get_weight() == pytest.approx(5.0)

    def test_empty_inventory_weight(self):
        inv = Inventory()
        assert inv.get_weight() == 0.0


# ---------------------------------------------------------------------------
# all()
# ---------------------------------------------------------------------------

class TestAll:
    def test_all_returns_tuple(self):
        inv = Inventory()
        inv.add(_make_item())
        result = inv.all()
        assert isinstance(result, tuple)

    def test_all_contains_added_items(self):
        inv = Inventory()
        a = _make_item(name="a")
        b = _make_item(name="b")
        inv.add(a)
        inv.add(b)
        items = inv.all()
        assert a in items
        assert b in items
        assert len(items) == 2

    def test_all_empty(self):
        inv = Inventory()
        assert inv.all() == ()
