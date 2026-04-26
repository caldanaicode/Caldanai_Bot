"""Recipe scroll stackable behavior + end-to-end crafting flow.

Exercises the actual code paths in
``caldanai.lib.cogs.rpg_crafting_commands`` (the helper functions
that drive ``$craft`` and ``$learn``) against real Player +
Inventory + recipe instances. The Discord cog wrappers are thin
async dispatch — these tests bypass them and call the underlying
helpers directly so they don't need a bot fixture.
"""
from random import seed

import pytest
from bson import ObjectId

from caldanai.lib.cogs.rpg_crafting_commands import (
    _consume_materials,
    _find_materials,
    _normalize,
)
from caldanai.lib.rpg.crafting import (
    discover_recipes,
    get_recipe,
    list_recipes,
)
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory import Inventory


@pytest.fixture(autouse=True)
def bootstrap():
    """Body parts + items + recipes need to be discovered for these
    integration tests."""
    BodyPartPlugin.load_plugins()
    Inventory.discover_items()
    discover_recipes()


def _player_with_leather(count=10, quality=Qualities.ORDINARY) -> Player:
    p = Player(uid=1, gid=2, cid=3)
    leather = Inventory.load_item(
        name="leather",
        data={"quality": quality.name, "count": count},
    )
    assert leather is not None
    p.inventory.add(leather)
    return p


# ---------------------------------------------------------------------------
# Recipe scroll
# ---------------------------------------------------------------------------

class TestRecipeScroll:
    def test_loads_with_recipe_name(self):
        scroll = Inventory.load_item(
            name="recipe_scroll",
            data={"recipe_name": "leather_jerkin"},
        )
        assert scroll is not None
        assert scroll.recipe_name == "leather_jerkin"
        assert scroll.unit_weight == 0.0

    def test_round_trip_recipe_name(self):
        original = Inventory.load_item(
            name="recipe_scroll",
            data={"recipe_name": "leather_boot"},
        )
        d = original.to_dict()
        assert d["recipe_name"] == "leather_boot"

        restored = Inventory.load_item(
            name="recipe_scroll",
            data=d,
        )
        assert restored.recipe_name == "leather_boot"

    def test_different_recipe_names_dont_stack(self):
        a = Inventory.load_item(
            name="recipe_scroll",
            data={"recipe_name": "leather_jerkin", "quality": "ORDINARY"},
        )
        b = Inventory.load_item(
            name="recipe_scroll",
            data={"recipe_name": "leather_boot", "quality": "ORDINARY"},
        )
        assert a.can_stack(b) is False

    def test_same_recipe_name_stacks(self):
        # ``can_stack`` requires distinct IDs (so identity stomp
        # is rejected). In real flow ``Inventory.add`` assigns one
        # if the item arrives idless — mirror that here.
        a = Inventory.load_item(
            name="recipe_scroll",
            data={"recipe_name": "leather_jerkin", "quality": "ORDINARY"},
        )
        a.id = ObjectId()
        b = Inventory.load_item(
            name="recipe_scroll",
            data={"recipe_name": "leather_jerkin", "quality": "ORDINARY"},
        )
        b.id = ObjectId()
        assert a.can_stack(b) is True


# ---------------------------------------------------------------------------
# Material lookup + consumption
# ---------------------------------------------------------------------------

class TestFindMaterials:
    def test_finds_enough(self):
        p = _player_with_leather(count=10)
        ok, found, missing = _find_materials(p, {"leather": 5})
        assert ok is True
        assert missing == []
        assert sum(s.count for s in found["leather"]) == 10

    def test_reports_missing(self):
        p = _player_with_leather(count=2)
        ok, _, missing = _find_materials(p, {"leather": 5})
        assert ok is False
        assert any("leather" in m for m in missing)

    def test_lowest_quality_listed_first(self):
        p = Player(uid=1, gid=2, cid=3)
        fine = Inventory.load_item(
            name="leather",
            data={"quality": "FINE", "count": 3},
        )
        ordinary = Inventory.load_item(
            name="leather",
            data={"quality": "ORDINARY", "count": 3},
        )
        # Add fine first to ensure sort kicks in regardless of order.
        p.inventory.add(fine)
        p.inventory.add(ordinary)

        _, found, _ = _find_materials(p, {"leather": 1})
        # ORDINARY (rank 1) should sort before FINE (rank 2).
        assert found["leather"][0].quality is Qualities.ORDINARY


class TestConsumeMaterials:
    def test_consumes_full_count_on_success(self):
        p = _player_with_leather(count=5)
        _, found, _ = _find_materials(p, {"leather": 5})
        consumed = _consume_materials(p, {"leather": 5}, found, fraction=1.0)

        assert len(consumed) == 5
        # Inventory drained.
        leftover = [it for it in p.inventory.all() if it.plugin == "leather"]
        assert sum(s.count for s in leftover) == 0

    def test_consumes_half_on_failure(self):
        p = _player_with_leather(count=5)
        _, found, _ = _find_materials(p, {"leather": 4})
        _consume_materials(p, {"leather": 4}, found, fraction=0.5)

        leftover = [it for it in p.inventory.all() if it.plugin == "leather"]
        # Half of 4 = 2 consumed; 3 remain.
        assert sum(s.count for s in leftover) == 3


# ---------------------------------------------------------------------------
# End-to-end success / failure (deterministic via seeded RNG)
# ---------------------------------------------------------------------------

class TestCraftFlow:
    def test_successful_craft_produces_armor(self):
        """High skill XP → near-100% success. Verify the output
        item lands in inventory and materials were consumed."""
        from caldanai.lib.cogs.rpg_crafting_commands import (
            RpgCraftingCommands,
        )
        import asyncio

        seed(0)
        p = _player_with_leather(count=10)
        p.skills["leatherworking"] = 500  # well above min, near-max success

        # Stub channel — capture Dispatcher.add calls.
        sent = []
        from caldanai.dispatcher import Dispatcher

        original_add = Dispatcher.add
        Dispatcher.add = lambda channel, content=None, file=None: sent.append(content)
        try:
            cog = RpgCraftingCommands(bot=None)
            asyncio.run(cog._do_craft("ch", p, "leather_cap"))
        finally:
            Dispatcher.add = original_add

        # Expect crafted item in inventory.
        caps = [it for it in p.inventory.all() if it.plugin == "leather_cap"]
        assert len(caps) == 1
        # And leather count dropped by 2 (recipe cost).
        leather_left = sum(
            s.count for s in p.inventory.all() if s.plugin == "leather"
        )
        assert leather_left == 8
        # And XP was granted.
        assert p.skills["leatherworking"] >= 505

    def test_unknown_recipe_refuses(self):
        from caldanai.lib.cogs.rpg_crafting_commands import (
            RpgCraftingCommands,
        )
        import asyncio
        from caldanai.dispatcher import Dispatcher

        p = _player_with_leather()
        sent = []
        original_add = Dispatcher.add
        Dispatcher.add = lambda channel, content=None, file=None: sent.append(content)
        try:
            cog = RpgCraftingCommands(bot=None)
            asyncio.run(cog._do_craft("ch", p, "fictional_doodad"))
        finally:
            Dispatcher.add = original_add

        assert any("No recipe matches" in (s or "") for s in sent)

    def test_insufficient_materials_refuses(self):
        from caldanai.lib.cogs.rpg_crafting_commands import (
            RpgCraftingCommands,
        )
        import asyncio
        from caldanai.dispatcher import Dispatcher

        p = _player_with_leather(count=1)  # need 5 for jerkin, only have 1
        sent = []
        original_add = Dispatcher.add
        Dispatcher.add = lambda channel, content=None, file=None: sent.append(content)
        try:
            cog = RpgCraftingCommands(bot=None)
            asyncio.run(cog._do_craft("ch", p, "leather_jerkin"))
        finally:
            Dispatcher.add = original_add

        assert any("Not enough materials" in (s or "") for s in sent)
        # No item produced.
        assert not any(
            it.plugin == "leather_jerkin" for it in p.inventory.all()
        )


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase_and_underscore(self):
        assert _normalize("Leather Jerkin") == "leather_jerkin"

    def test_dash_to_underscore(self):
        assert _normalize("leather-cap") == "leather_cap"

    def test_strip_whitespace(self):
        assert _normalize("  leather boot  ") == "leather_boot"
