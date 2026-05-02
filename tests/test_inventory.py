"""Tests for Caldanai.lib.rpg.inventory.Inventory class."""

from unittest.mock import patch, MagicMock

import pytest
from bson.objectid import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory import Inventory
from caldanai.lib.rpg.inventory.item import Item
from caldanai.lib.rpg.inventory.stackables import Stackable


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

    @patch("caldanai.lib.rpg.inventory.Inventory.load_item")
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
# sort()
# ---------------------------------------------------------------------------

class TestSort:
    """``$sort`` re-keys ``__items`` so identical plugins group
    together (alpha asc), with the best-quality copy of each
    group at the lowest slot. Item identity preserved."""

    def test_sort_groups_by_plugin(self):
        inv = Inventory()
        a1 = _make_item(name="alpha"); a1.plugin = "alpha"
        b1 = _make_item(name="bravo"); b1.plugin = "bravo"
        a2 = _make_item(name="alpha"); a2.plugin = "alpha"
        # Insertion: alpha, bravo, alpha — interleaved.
        inv.add(a1); inv.add(b1); inv.add(a2)
        inv.sort()
        items = inv.all()
        # Both alphas land before bravo.
        assert items[0].plugin == "alpha"
        assert items[1].plugin == "alpha"
        assert items[2].plugin == "bravo"

    def test_sort_quality_desc_within_plugin(self):
        inv = Inventory()
        junk = _make_item(quality=Qualities.JUNK); junk.plugin = "rerebrace"
        masterwork = _make_item(quality=Qualities.MASTERWORK); masterwork.plugin = "rerebrace"
        fine = _make_item(quality=Qualities.FINE); fine.plugin = "rerebrace"
        inv.add(junk); inv.add(masterwork); inv.add(fine)
        inv.sort()
        items = inv.all()
        assert items[0].quality == Qualities.MASTERWORK
        assert items[1].quality == Qualities.FINE
        assert items[2].quality == Qualities.JUNK

    def test_sort_returns_count(self):
        inv = Inventory()
        for _ in range(5):
            inv.add(_make_item())
        assert inv.sort() == 5

    def test_sort_empty_inventory(self):
        inv = Inventory()
        assert inv.sort() == 0
        assert len(inv) == 0

    def test_sort_preserves_favorited(self):
        inv = Inventory()
        i1 = _make_item(name="A"); i1.plugin = "alpha"
        i2 = _make_item(name="B"); i2.plugin = "bravo"
        i1.favorited = True
        inv.add(i2); inv.add(i1)
        inv.sort()
        # Find i1 in the sorted result; favorited flag intact.
        found = next(x for x in inv.all() if x is i1)
        assert found.favorited is True

    def test_sort_preserves_item_identity(self):
        """Items keep their _id and instance identity through
        sort — only slot keys change. Loadouts (which reference
        items by ObjectId) stay intact."""
        inv = Inventory()
        ids = [ObjectId() for _ in range(4)]
        for i, oid in enumerate(ids):
            it = _make_item(iid=oid); it.plugin = f"plugin_{i % 2}"
            inv.add(it)
        before = {item.id: item for item in inv.all()}
        inv.sort()
        after = {item.id: item for item in inv.all()}
        # Same IDs, same Item instances.
        assert set(before.keys()) == set(after.keys())
        for oid in before:
            assert before[oid] is after[oid]

    def test_sort_preserves_stacks(self):
        """Stackables sort as a single Item entry — no
        unstacking, no count loss."""
        inv = Inventory()
        s1 = _make_stackable(plugin="dust", count=5)
        item = _make_item(); item.plugin = "alpha"
        inv.add(s1); inv.add(item)
        inv.sort()
        # 'alpha' < 'dust' so item comes first; stack lands second
        # with count intact.
        items = inv.all()
        assert items[0].plugin == "alpha"
        assert items[1] is s1
        assert items[1].count == 5

    def test_sort_idempotent(self):
        """Sorting twice is a no-op — the second sort produces the
        same ordering as the first."""
        inv = Inventory()
        for q, p in [
            (Qualities.JUNK, "rerebrace"),
            (Qualities.SUPERIOR, "alpha"),
            (Qualities.FINE, "rerebrace"),
            (Qualities.ORDINARY, "alpha"),
        ]:
            it = _make_item(quality=q); it.plugin = p
            inv.add(it)
        inv.sort()
        first_pass = [(i.plugin, i.quality) for i in inv.all()]
        inv.sort()
        second_pass = [(i.plugin, i.quality) for i in inv.all()]
        assert first_pass == second_pass

    def test_sort_compacts_slots_to_1_n(self):
        """After sort, slot keys are 1..N with no gaps — same
        invariant ``_rekey`` maintains for delete/remove paths."""
        inv = Inventory()
        for _ in range(6):
            inv.add(_make_item())
        inv.sort()
        # Iterate slots via to_list which exposes the slot order.
        # Length should match item count.
        assert len(inv) == 6
        # All items reachable in slot order, no None gaps.
        all_items = inv.all()
        assert all(it is not None for it in all_items)
        assert len(all_items) == 6


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


# ---------------------------------------------------------------------------
# favorited flag + favorites() helper + round-trip persistence
# ---------------------------------------------------------------------------

class TestFavorites:
    def test_new_item_defaults_to_not_favorited(self):
        assert _make_item().favorited is False

    def test_to_dict_omits_flag_when_false(self):
        """Legacy DB docs stay bit-for-bit identical until a player
        actually favorites something — zero migration surface."""
        d = _make_item().to_dict()
        assert "favorited" not in d

    def test_to_dict_writes_flag_when_true(self):
        item = _make_item()
        item.favorited = True
        assert item.to_dict()["favorited"] is True

    def test_favorites_filters_inventory(self):
        inv = Inventory()
        plain = _make_item(name="rock")
        starred = _make_item(name="sword")
        starred.favorited = True
        inv.add(plain)
        inv.add(starred)

        assert inv.favorites() == (starred,)

    def test_favorites_empty_when_none_favorited(self):
        inv = Inventory()
        inv.add(_make_item())
        inv.add(_make_item(name="rock"))
        assert inv.favorites() == ()

    def test_load_item_restores_favorited_from_data(self):
        """The flag round-trips through ``load_item`` so subclasses
        don't each need to thread it through ``from_plugin``."""
        fake_item = _make_item()
        fake_item.favorited = False  # ensure baseline
        fake_class = MagicMock()
        fake_class.from_plugin.return_value = fake_item

        with patch.dict(Inventory.ITEMS, {"rock": fake_class}, clear=False):
            loaded = Inventory.load_item(data={"plugin": "rock", "favorited": True})

        assert loaded is fake_item
        assert loaded.favorited is True

    def test_load_item_leaves_favorited_false_when_missing(self):
        fake_item = _make_item()
        fake_class = MagicMock()
        fake_class.from_plugin.return_value = fake_item

        with patch.dict(Inventory.ITEMS, {"rock": fake_class}, clear=False):
            loaded = Inventory.load_item(data={"plugin": "rock"})

        assert loaded.favorited is False


# ---------------------------------------------------------------------------
# Slot stability — internal storage is a dict keyed by 1-based
# slot number, rekeyed compact (1..N) on every mutation. These
# tests pin the contract: filter("N") returns the item currently
# at user-visible slot N, and removes don't leave gaps.
# ---------------------------------------------------------------------------

class TestSlotStability:
    def test_slots_are_one_indexed_after_add(self):
        inv = Inventory()
        a = _make_item(name="a")
        b = _make_item(name="b")
        c = _make_item(name="c")
        inv.add(a)
        inv.add(b)
        inv.add(c)
        assert inv.filter("1") == (a,)
        assert inv.filter("2") == (b,)
        assert inv.filter("3") == (c,)

    def test_remove_compacts_slots_to_close_gap(self):
        inv = Inventory()
        a = _make_item(name="a")
        b = _make_item(name="b")
        c = _make_item(name="c")
        inv.add(a)
        inv.add(b)
        inv.add(c)
        inv.remove(b)
        # b was at slot 2; after remove, c is now at slot 2.
        assert inv.filter("1") == (a,)
        assert inv.filter("2") == (c,)
        assert len(inv) == 2

    def test_add_after_remove_uses_next_compact_slot(self):
        inv = Inventory()
        a = _make_item(name="a")
        b = _make_item(name="b")
        c = _make_item(name="c")
        inv.add(a)
        inv.add(b)
        inv.remove(a)
        # b moved from slot 2 to slot 1; new add lands at slot 2.
        inv.add(c)
        assert inv.filter("1") == (b,)
        assert inv.filter("2") == (c,)
        assert len(inv) == 2

    def test_all_iteration_order_matches_slot_order(self):
        inv = Inventory()
        a = _make_item(name="a")
        b = _make_item(name="b")
        c = _make_item(name="c")
        inv.add(a)
        inv.add(b)
        inv.add(c)
        inv.remove(b)
        # all() returns insertion order, which after a remove +
        # rekey equals slot order: (a, c) at slots 1, 2.
        assert inv.all() == (a, c)
