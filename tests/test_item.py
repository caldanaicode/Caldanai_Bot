"""Tests for Caldanai.lib.rpg.inventory.item.Item class."""

import pytest
from bson.objectid import ObjectId

from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory.item import Item


# ---------------------------------------------------------------------------
# Construction and properties
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_basic_construction(self):
        oid = ObjectId()
        item = Item(
            iid=oid,
            name="dagger",
            desc="A small blade",
            unit_weight=1.5,
            unit_value=10,
            quality=Qualities.ORDINARY,
            plugin="dagger",
        )
        assert item.id == oid
        assert item.name == "dagger"
        assert item.description == "A small blade"
        assert item.unit_weight == 1.5
        assert item.quality == Qualities.ORDINARY
        assert item.plugin == "dagger"

    def test_value_multiplied_by_quality(self):
        item = Item(unit_value=100, quality=Qualities.MASTERWORK, plugin="x")
        assert item.unit_value == round(100 * Qualities.MASTERWORK.value["multiplier"])

    def test_default_quality_assigned_when_none(self):
        item = Item(plugin="x")
        assert item.quality is not None
        assert isinstance(item.quality, Qualities)

    def test_negative_weight_clamped_to_zero(self):
        item = Item(unit_weight=-5.0, quality=Qualities.ORDINARY, plugin="x")
        assert item.unit_weight == 0.0

    def test_negative_value_clamped_to_zero(self):
        item = Item(unit_value=-10, quality=Qualities.ORDINARY, plugin="x")
        assert item.unit_value == 0

    def test_default_article_is_a(self):
        item = Item(quality=Qualities.ORDINARY, plugin="x")
        assert item.article == "a"

    def test_custom_article(self):
        item = Item(article="some", quality=Qualities.ORDINARY, plugin="x")
        assert item.article == "some"

    def test_item_type_default(self):
        item = Item(quality=Qualities.ORDINARY, plugin="x")
        assert item.item_type == "Item"


# ---------------------------------------------------------------------------
# get_full_name
# ---------------------------------------------------------------------------

class TestGetFullName:
    def test_full_name_with_ordinary_quality(self):
        item = Item(name="sword", quality=Qualities.ORDINARY, plugin="x")
        name = item.get_full_name()
        # "ordinary" starts with 'o', so article becomes "an"
        assert name == "an ordinary sword"

    def test_full_name_with_junk_quality(self):
        item = Item(name="rock", quality=Qualities.JUNK, plugin="x")
        name = item.get_full_name()
        # "junk" starts with 'j', not a vowel, so article stays "a"
        assert name == "a junk rock"

    def test_full_name_with_custom_article_some(self):
        item = Item(name="dust", article="some", quality=Qualities.FINE, plugin="x")
        name = item.get_full_name()
        # article "some" bypasses vowel logic
        assert name == "some fine dust"


# ---------------------------------------------------------------------------
# get_weight
# ---------------------------------------------------------------------------

class TestGetWeight:
    def test_get_weight_returns_unit_weight(self):
        item = Item(unit_weight=3.7, quality=Qualities.ORDINARY, plugin="x")
        assert item.get_weight() == 3.7

    def test_get_weight_zero(self):
        item = Item(unit_weight=0.0, quality=Qualities.ORDINARY, plugin="x")
        assert item.get_weight() == 0.0


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------

class TestToDict:
    def test_to_dict_includes_required_keys(self):
        oid = ObjectId()
        item = Item(iid=oid, quality=Qualities.FINE, plugin="sword")
        d = item.to_dict()
        assert d["_id"] == oid
        assert d["quality"] == "FINE"
        assert d["plugin"] == "sword"
        assert d["item_type"] == "Item"

    def test_to_dict_without_id_omits_id_key(self):
        item = Item(quality=Qualities.ORDINARY, plugin="x")
        d = item.to_dict()
        assert "_id" not in d
