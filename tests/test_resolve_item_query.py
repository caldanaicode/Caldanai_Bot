"""Tests for ``Player.resolve_item_query`` — the shared data
layer behind ``$equip`` / ``$stow`` / ``$item`` / ``$sell``'s
query handling.

Covers the four modes and their priority rules:

- ``"equip"`` — item-first; multi-match → ambiguity.
- ``"stow"`` — placement-first (via find_equipped_by_placement),
  then equipped-item-name fallback; inventory-only items don't
  come back (nothing to stow).
- ``"item"`` — item-first, with a placement fallback so
  ``$item head.helm`` shows the currently-worn helm.
- ``"sell"`` — item-first, excludes equipped; multi-match
  returns the full list (no ambiguity surfacing — the point
  of sell is to catch multiple matches).

The ``.best`` quality selector is honored in every mode
(picks the highest-quality variant of the matching base name).
"""

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import ItemResolution, Player
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _player() -> Player:
    return Player(uid=1, gid=2, cid=3)


def _give(player: Player, plugin_name: str):
    item = Inventory.load_item(name=plugin_name)
    assert item is not None, f"unknown plugin {plugin_name!r}"
    player.inventory.add(item)
    return item


def _give_and_equip(player: Player, plugin_name: str):
    item = _give(player, plugin_name)
    ok, _ = player.equip(item)
    assert ok
    return item


class TestEquipMode:
    def test_single_item_resolves_cleanly(self):
        p = _player()
        hat = _give(p, "mushroom_hat")
        res = p.resolve_item_query("mushroom", "equip")
        assert res.items == [hat]
        assert res.ambiguity_candidates == []

    def test_multiple_same_name_items_surface_ambiguity(self):
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        res = p.resolve_item_query("wand", "equip")
        assert res.items == []
        assert res.ambiguity_candidates  # some candidate hints

    def test_best_selector_picks_highest_quality(self):
        """``.best`` collapses multi-match ambiguity by picking the
        highest-quality variant — single-match return."""
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        res = p.resolve_item_query("wand.best", "equip")
        assert len(res.items) == 1

    def test_no_match_returns_empty(self):
        p = _player()
        _give(p, "mushroom_hat")
        res = p.resolve_item_query("cape", "equip")
        assert res.items == []
        assert res.ambiguity_candidates == []

    def test_index_selector_picks_specific(self):
        """``wand.1`` picks the first wand, single-match — shouldn't
        trigger ambiguity even when multiple wands exist."""
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        res = p.resolve_item_query("wand.1", "equip")
        assert len(res.items) == 1


class TestStowMode:
    def test_placement_key_finds_equipped(self):
        """Bare placement key (``helm``) resolves to the item at
        that placement."""
        p = _player()
        hat = _give_and_equip(p, "mushroom_hat")
        res = p.resolve_item_query("helm", "stow")
        assert res.items == [hat]

    def test_full_part_key_placement(self):
        p = _player()
        hat = _give_and_equip(p, "mushroom_hat")
        res = p.resolve_item_query("head.helm", "stow")
        assert res.items == [hat]

    def test_inventory_only_item_does_not_resolve(self):
        """Item in inventory but not equipped → stow has nothing
        to act on. Resolver must not fall back to an inventory
        match — that's a no-op for stow."""
        p = _player()
        _give(p, "mushroom_hat")
        res = p.resolve_item_query("mushroom", "stow")
        # Not equipped, inventory-name fallback filters to equipped-
        # only → empty items.
        assert res.items == []

    def test_equipped_item_name_fallback(self):
        """When a placement key doesn't match but an item-name
        filter hits an equipped item, return that item."""
        p = _player()
        hat = _give_and_equip(p, "mushroom_hat")
        # "mushroom_hat" is the plugin name; inventory.filter picks
        # it up by substring match on the item's ``name`` field
        # ("mushroom hat"). Since the hat IS equipped, stow-mode
        # returns it.
        res = p.resolve_item_query("mushroom", "stow")
        assert res.items == [hat]

    def test_empty_when_nothing_equipped_matches(self):
        p = _player()
        _give(p, "wand")  # unequipped
        res = p.resolve_item_query("held", "stow")
        assert res.items == []
        assert res.ambiguity_candidates == []


class TestItemMode:
    def test_inventory_item_wins(self):
        p = _player()
        cape = _give(p, "cape")
        res = p.resolve_item_query("cape", "item")
        assert res.items == [cape]

    def test_placement_fallback_when_no_inventory_match(self):
        """``$item head.helm`` (or ``$item helm``) when you have
        no helm in inventory should fall back to "what's equipped
        there" so the command is useful without an inventory
        match."""
        p = _player()
        hat = _give_and_equip(p, "mushroom_hat")
        # Remove from inventory too (weird edge — the equip flow
        # leaves it in inventory, so for realistic test we need to
        # confirm placement fallback triggers only when inventory
        # filter misses). Let's test the full placement form
        # specifically — inventory.filter("head.helm") won't match
        # any item name, so placement fallback kicks in.
        res = p.resolve_item_query("head.helm", "item")
        assert res.items == [hat]

    def test_ambiguous_inventory_surfaces_candidates(self):
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        res = p.resolve_item_query("wand", "item")
        assert res.items == []
        assert res.ambiguity_candidates


class TestSellMode:
    def test_returns_multiple_unequipped_matches(self):
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        res = p.resolve_item_query("wand", "sell")
        assert len(res.items) == 2
        # Sell never surfaces ambiguity — multi-match IS the point.
        assert res.ambiguity_candidates == []

    def test_excludes_equipped_items(self):
        """Equipped items are NOT sellable — resolver filters them
        out of the result so the caller doesn't have to."""
        p = _player()
        _give_and_equip(p, "wand")  # equipped
        _give(p, "wand")              # free
        res = p.resolve_item_query("wand", "sell")
        assert len(res.items) == 1

    def test_all_equipped_returns_empty(self):
        p = _player()
        _give_and_equip(p, "mushroom_hat")
        res = p.resolve_item_query("mushroom", "sell")
        assert res.items == []

    def test_best_picks_one_unequipped(self):
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        res = p.resolve_item_query("wand.best", "sell")
        assert len(res.items) == 1


class TestStowBareKeyBroadening:
    """Bare placement keys in stow mode broaden to every occupied
    placement with that key. ``$stow held`` clears both hands;
    ``$stow ring`` clears both rings. Full ``part.key`` form stays
    specific."""

    def test_held_clears_both_hands_when_dual_wielding(self):
        p = _player()
        left = Inventory.load_item(name="shortsword")
        right = Inventory.load_item(name="mace")
        p.inventory.add(left)
        p.inventory.add(right)
        p.part_equipment["arm.left"]["held"] = left
        p.part_equipment["arm.right"]["held"] = right

        res = p.resolve_item_query("held", "stow")
        assert len(res.items) == 2
        assert left in res.items
        assert right in res.items

    def test_held_returns_one_item_when_two_handed(self):
        """Two-handed weapons share their Item ref across both
        arms — the broadening dedupes by identity so callers don't
        call ``remove()`` twice on the same weapon."""
        p = _player()
        spear = _give_and_equip(p, "spear")
        res = p.resolve_item_query("held", "stow")
        assert len(res.items) == 1
        assert res.items[0] is spear

    def test_full_part_key_stays_specific(self):
        """``arm.left.held`` must NOT broaden to both arms — the
        explicit form is the escape hatch when the player wants
        exactly one side."""
        p = _player()
        left = Inventory.load_item(name="shortsword")
        right = Inventory.load_item(name="mace")
        p.inventory.add(left)
        p.inventory.add(right)
        p.part_equipment["arm.left"]["held"] = left
        p.part_equipment["arm.right"]["held"] = right

        res = p.resolve_item_query("arm.left.held", "stow")
        assert res.items == [left]


class TestItemBareKeyAmbiguates:
    """Bare placement keys in item mode ambiguate when they match
    multiple occupied placements — ``$item held`` can't pick a
    side. Specific ``part.key`` or item-name queries resolve
    cleanly."""

    def test_held_ambiguates_when_dual_wielding(self):
        p = _player()
        left = Inventory.load_item(name="shortsword")
        right = Inventory.load_item(name="mace")
        p.inventory.add(left)
        p.inventory.add(right)
        p.part_equipment["arm.left"]["held"] = left
        p.part_equipment["arm.right"]["held"] = right

        res = p.resolve_item_query("held", "item")
        assert res.items == []
        # Candidate labels are the specific placement strings so
        # the user can retype e.g. ``arm.left.held`` unambiguously.
        assert "arm.left.held" in res.ambiguity_candidates
        assert "arm.right.held" in res.ambiguity_candidates

    def test_held_resolves_cleanly_when_single_hand(self):
        """Only one hand occupied → no ambiguity, return that item."""
        p = _player()
        sword = _give_and_equip(p, "shortsword")
        res = p.resolve_item_query("held", "item")
        assert res.items == [sword]

    def test_full_part_key_resolves_cleanly(self):
        p = _player()
        left = Inventory.load_item(name="shortsword")
        right = Inventory.load_item(name="mace")
        p.inventory.add(left)
        p.inventory.add(right)
        p.part_equipment["arm.left"]["held"] = left
        p.part_equipment["arm.right"]["held"] = right

        res = p.resolve_item_query("arm.right.held", "item")
        assert res.items == [right]


class TestBestSelectorInSellMode:
    """``.best`` should pick the best from the CANDIDATE POOL for
    the mode — in sell mode, that's unequipped items only. Pre-fix
    the filter ran globally and then sell subtracted equipped,
    which made ``$sell wand.best`` return nothing when the best
    wand was equipped (the common case after ``$equip wand.best``)."""

    def _three_quality_wands(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p = _player()
        items = []
        for q in (Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR):
            w = Inventory.load_item(name="wand")
            w.quality = q
            p.inventory.add(w)
            items.append(w)
        return p, items

    def test_sell_best_with_nothing_equipped_picks_superior(self):
        p, (junk, fine, superior) = self._three_quality_wands()
        res = p.resolve_item_query("wand.best", "sell")
        assert res.items == [superior]

    def test_sell_best_falls_back_to_next_best_when_best_equipped(self):
        p, (junk, fine, superior) = self._three_quality_wands()
        p.part_equipment["arm.left"]["held"] = superior
        res = p.resolve_item_query("wand.best", "sell")
        assert res.items == [fine]

    def test_sell_best_empty_when_all_equipped(self):
        p, (junk, fine, superior) = self._three_quality_wands()
        p.part_equipment["arm.left"]["held"] = superior
        p.part_equipment["arm.right"]["held"] = fine
        # junk stays unequipped — best of unequipped is junk.
        res = p.resolve_item_query("wand.best", "sell")
        assert res.items == [junk]


class TestBestSelectorInEquipMode:
    """Same fix as sell mode: ``$equip wand.best`` with the
    globally-best wand already equipped picks the next-best
    unequipped rather than bouncing off "Item already equipped."
    Lets a player fill their second hand with the second-best
    wand in a single command. Full quality form (``wand.superior``)
    or index form (``wand.1``) is the escape hatch when the
    player really wants to re-equip the worn item."""

    def _three_quality_wands(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p = _player()
        items = []
        for q in (Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR):
            w = Inventory.load_item(name="wand")
            w.quality = q
            p.inventory.add(w)
            items.append(w)
        return p, items

    def test_equip_best_picks_superior_when_none_equipped(self):
        p, (_, _, superior) = self._three_quality_wands()
        res = p.resolve_item_query("wand.best", "equip")
        assert res.items == [superior]

    def test_equip_best_picks_next_best_when_superior_worn(self):
        p, (_, fine, superior) = self._three_quality_wands()
        p.part_equipment["arm.left"]["held"] = superior
        res = p.resolve_item_query("wand.best", "equip")
        assert res.items == [fine]

    def test_equip_best_falls_to_junk_when_two_worn(self):
        p, (junk, fine, superior) = self._three_quality_wands()
        p.part_equipment["arm.left"]["held"] = superior
        p.part_equipment["arm.right"]["held"] = fine
        res = p.resolve_item_query("wand.best", "equip")
        assert res.items == [junk]


class TestQualityPrefixExpansion:
    """Single (or multi) character prefixes of quality suffixes
    expand to the full form. Each quality starts with a unique
    letter today (``.b``=best, ``.j``=junk, ``.o``=ordinary,
    ``.f``=fine, ``.q``=quality, ``.s``=superior, ``.m``=masterwork)
    so one-char prefixes are unambiguous."""

    def _make_with_qualities(self, *qualities):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p = _player()
        items = []
        for q in qualities:
            w = Inventory.load_item(name="wand")
            w.quality = q
            p.inventory.add(w)
            items.append(w)
        return p, items

    def test_dot_b_expands_to_best(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p, (_, fine, superior) = self._make_with_qualities(
            Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR,
        )
        res = p.resolve_item_query("wand.b", "equip")
        assert res.items == [superior]

    def test_dot_s_expands_to_superior(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p, (_, _, superior) = self._make_with_qualities(
            Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR,
        )
        res = p.resolve_item_query("wand.s", "equip")
        assert res.items == [superior]

    def test_dot_j_expands_to_junk(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p, (junk, _, _) = self._make_with_qualities(
            Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR,
        )
        res = p.resolve_item_query("wand.j", "equip")
        assert res.items == [junk]

    def test_multi_char_prefix_narrows(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p, (_, _, _, masterwork) = self._make_with_qualities(
            Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR, Qualities.MASTERWORK,
        )
        res = p.resolve_item_query("wand.mas", "equip")
        assert res.items == [masterwork]

    def test_full_name_still_works(self):
        from caldanai.lib.rpg.helpers.enums import Qualities
        p, (_, fine, _) = self._make_with_qualities(
            Qualities.JUNK, Qualities.FINE, Qualities.SUPERIOR,
        )
        res = p.resolve_item_query("wand.fine", "equip")
        assert res.items == [fine]

    def test_unknown_prefix_falls_through(self):
        """A prefix that doesn't uniquely match any quality
        should NOT be expanded — leave as-is and let normal
        handling fail naturally. ``wand.xyz`` has no match."""
        p, _ = self._make_with_qualities()
        res = p.resolve_item_query("wand.xyz", "equip")
        # Empty result — not a crash, just no match.
        assert res.items == []


class TestUnknownMode:
    def test_unknown_mode_raises(self):
        p = _player()
        with pytest.raises(ValueError):
            p.resolve_item_query("whatever", "nope")


class TestEdgeCases:
    def test_empty_query_returns_empty(self):
        p = _player()
        res = p.resolve_item_query("", "equip")
        assert res.items == []
        assert res.ambiguity_candidates == []

    def test_whitespace_query_returns_empty(self):
        p = _player()
        res = p.resolve_item_query("   ", "equip")
        assert res.items == []
