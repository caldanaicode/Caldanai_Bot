"""Tests for ``Player`` saved gear loadouts.

QoL feature landing on top of stage 2a (destroyed-part drops
gear). Players can snapshot their current ``part_equipment``
under a label and restore it later with a single command.

Contract pinned here:

- Save under a label, stored with original casing, looked up
  case-insensitively.
- Capacity capped at ``MAX_LOADOUTS``. Overwriting an existing
  (casefolded-equal) label is allowed; adding a NEW label when
  the player is at cap is rejected.
- Load stows current gear, then equips every saved item that's
  still in inventory and lands on a usable body part.
- Missing items (sold, traded, lost) are silently pruned from
  saved loadouts via the ``_purge_item_refs`` hook on
  ``take_item``.
- Persistence round-trips through ``to_dict`` / ``from_dict``.
"""

from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import MAX_LOADOUTS, Player
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _player_with(*plugin_names):
    p = Player(uid=1, gid=2, cid=3)
    items = []
    for name in plugin_names:
        item = Inventory.load_item(name=name)
        p.inventory.add(item)
        items.append(item)
    return p, items


class TestSaveLoadout:
    def test_save_empty_equipment_succeeds(self):
        """Saving with nothing equipped produces an empty payload
        — valid for snapshotting a "naked" state."""
        p, _ = _player_with()
        ok, label = p.save_loadout("naked")
        assert ok
        assert label == "naked"
        assert p.loadouts["naked"] == {}

    def test_save_captures_current_placements(self):
        p, (hat, wand) = _player_with("mushroom_hat", "wand")
        p.equip(hat)
        p.equip(wand)

        ok, _ = p.save_loadout("combat")
        assert ok
        payload = p.loadouts["combat"]
        assert payload["head"]["helm"] == str(hat.id)
        assert payload["arm.left"]["held"] == str(wand.id)

    def test_save_preserves_original_casing(self):
        p, _ = _player_with()
        p.save_loadout("Combat")
        assert "Combat" in p.loadouts
        assert "combat" not in p.loadouts

    def test_empty_label_rejected(self):
        p, _ = _player_with()
        ok, msg = p.save_loadout("")
        assert not ok
        assert "empty" in msg.lower()

    def test_whitespace_only_label_rejected(self):
        p, _ = _player_with()
        ok, msg = p.save_loadout("   ")
        assert not ok


class TestOverwriteAndCap:
    def test_case_insensitive_overwrite(self):
        """Saving ``Combat`` after ``combat`` overwrites the slot
        (not a second entry) and adopts the new casing."""
        p, (hat,) = _player_with("mushroom_hat")
        p.equip(hat)
        p.save_loadout("combat")
        p.save_loadout("Combat")  # different casing

        assert "Combat" in p.loadouts
        assert "combat" not in p.loadouts
        assert len(p.loadouts) == 1

    def test_capacity_cap_rejects_fourth_new_label(self):
        p, _ = _player_with()
        p.save_loadout("one")
        p.save_loadout("two")
        p.save_loadout("three")
        assert len(p.loadouts) == MAX_LOADOUTS

        ok, msg = p.save_loadout("four")
        assert not ok
        assert "three" in msg.lower() or str(MAX_LOADOUTS) in msg

    def test_overwrite_at_cap_still_allowed(self):
        """The cap only blocks adding NEW labels. Overwriting an
        existing label (even with different casing) must still
        succeed when the player is at MAX_LOADOUTS."""
        p, _ = _player_with()
        p.save_loadout("one")
        p.save_loadout("two")
        p.save_loadout("three")

        ok, label = p.save_loadout("ONE")  # casefold-match to "one"
        assert ok
        assert label == "ONE"
        assert len(p.loadouts) == MAX_LOADOUTS


class TestLoadLoadout:
    def test_load_restores_saved_equipment(self):
        p, (hat, wand) = _player_with("mushroom_hat", "wand")
        p.equip(hat)
        p.equip(wand)
        p.save_loadout("combat")

        # Unequip everything manually.
        p.remove(hat)
        p.remove(wand)
        assert p.part_equipment["head"]["helm"] is None
        assert p.part_equipment["arm.left"]["held"] is None

        ok, label, restored, skipped = p.load_loadout("combat")
        assert ok
        assert label == "combat"
        assert skipped == []
        assert p.part_equipment["head"]["helm"] is hat
        assert p.part_equipment["arm.left"]["held"] is wand
        # ``restored`` is a list of Item instances — pinned here
        # because the cog passes it to ``item_list_to_string``,
        # which calls ``.get_full_name()`` on each element. Before
        # the 2026-04-22 post-playtest fix, this was a list of
        # strings and blew up with "'str' object has no attribute
        # 'get_full_name'" on the first successful load.
        assert set(restored) == {hat, wand}
        for item in restored:
            assert hasattr(item, "get_full_name")

    def test_load_is_case_insensitive(self):
        p, (hat,) = _player_with("mushroom_hat")
        p.equip(hat)
        p.save_loadout("Combat")

        ok, label, _, _ = p.load_loadout("combat")
        assert ok
        assert label == "Combat"  # echoes original casing

    def test_load_unknown_label_returns_false(self):
        p, _ = _player_with()
        ok, label, restored, skipped = p.load_loadout("nope")
        assert not ok
        assert restored == []
        assert skipped == []

    def test_load_stows_current_gear_first(self):
        """Loading a different loadout must first release whatever
        is currently equipped, so the saved set can land cleanly."""
        p, (hat, wand, bow) = _player_with("mushroom_hat", "wand", "bow")
        p.equip(hat)
        p.equip(wand)
        p.save_loadout("combat")

        # Now swap to a different loadout via equip + save.
        p.remove(wand)
        p.equip(bow)  # two-handed, both arms
        p.save_loadout("ranged")

        # Current state: hat + bow. Load combat should drop bow,
        # re-equip the wand (hat already on, but it gets dropped
        # then re-equipped via the stow-all first step).
        ok, _, restored, skipped = p.load_loadout("combat")
        assert ok
        assert p.part_equipment["head"]["helm"] is hat
        assert p.part_equipment["arm.left"]["held"] is wand
        # Bow was stowed during load (not in saved set), not lost.
        assert p.inventory[bow.id] is bow

    def test_load_skips_missing_items_with_note(self):
        """If a saved loadout references an item that was sold/
        traded/removed since save, that entry is skipped with a
        human-readable note. Other items in the set still land."""
        p, (hat, wand) = _player_with("mushroom_hat", "wand")
        p.equip(hat)
        p.equip(wand)
        p.save_loadout("combat")

        # Manually invalidate the wand's reference in the saved
        # payload (simulates: item was sold after save, but the
        # _purge_item_refs hook somehow missed it — this pins
        # the runtime skip-and-note path).
        p.loadouts["combat"]["arm.left"]["held"] = "nonexistent-id-string"
        p.remove(hat)

        ok, _, restored, skipped = p.load_loadout("combat")
        assert ok
        assert len(restored) == 1  # hat
        assert len(skipped) == 1  # phantom wand id


class TestFuzzyLabelResolution:
    """``resolve_loadout_label`` powers ``$loadout load`` /
    ``$loadout clear`` — prefix-match a partial query to a saved
    label, exact case-insensitive match wins, multiple prefix
    matches surface as ambiguity candidates."""

    def test_exact_case_insensitive_match_wins(self):
        p, _ = _player_with()
        p.save_loadout("Combat")
        resolved, candidates = p.resolve_loadout_label("combat")
        assert resolved == "Combat"
        assert candidates == []

    def test_single_prefix_match_resolves(self):
        p, _ = _player_with()
        p.save_loadout("dual-wand")
        resolved, candidates = p.resolve_loadout_label("dual")
        assert resolved == "dual-wand"
        assert candidates == []

    def test_multiple_prefix_matches_surface_ambiguity(self):
        p, _ = _player_with()
        p.save_loadout("dual-wand")
        p.save_loadout("dual-axe")
        resolved, candidates = p.resolve_loadout_label("dual")
        assert resolved is None
        assert set(candidates) == {"dual-wand", "dual-axe"}

    def test_exact_match_beats_prefix_ambiguity(self):
        """If the player saved both ``"a"`` and ``"abc"``, typing
        ``$loadout load a`` must still resolve the short label —
        the exact match wins over prefix-ambiguity blocking."""
        p, _ = _player_with()
        p.save_loadout("a")
        p.save_loadout("abc")
        resolved, candidates = p.resolve_loadout_label("a")
        assert resolved == "a"
        assert candidates == []

    def test_no_match_returns_none_empty(self):
        p, _ = _player_with()
        p.save_loadout("combat")
        resolved, candidates = p.resolve_loadout_label("travel")
        assert resolved is None
        assert candidates == []

    def test_empty_query_returns_none(self):
        p, _ = _player_with()
        p.save_loadout("combat")
        resolved, candidates = p.resolve_loadout_label("")
        assert resolved is None
        assert candidates == []


class TestClearLoadout:
    def test_clear_removes_slot(self):
        p, _ = _player_with()
        p.save_loadout("tmp")
        assert "tmp" in p.loadouts

        ok, stored = p.clear_loadout("tmp")
        assert ok
        assert stored == "tmp"
        assert "tmp" not in p.loadouts

    def test_clear_is_case_insensitive(self):
        p, _ = _player_with()
        p.save_loadout("Combat")
        ok, stored = p.clear_loadout("COMBAT")
        assert ok
        assert stored == "Combat"

    def test_clear_unknown_label_returns_false(self):
        p, _ = _player_with()
        ok, stored = p.clear_loadout("nope")
        assert not ok
        assert stored == ""


class TestPurgeOnTakeItem:
    """``take_item`` is the centralized "player no longer owns
    this item" hook (sell, future trade, admin removal). Every
    successful take must prune the item's id from every saved
    loadout so ``$loadout load`` doesn't try to equip ghosts."""

    def test_selling_item_purges_from_loadouts(self):
        p, (hat, wand) = _player_with("mushroom_hat", "wand")
        p.equip(hat)
        p.equip(wand)
        p.save_loadout("combat")
        assert p.loadouts["combat"]["arm.left"]["held"] == str(wand.id)

        # Unequip wand, then sell it.
        p.remove(wand)
        p.sell(wand)

        # Saved payload should no longer reference the sold wand.
        assert "arm.left" not in p.loadouts["combat"]
        # Hat ref stays.
        assert p.loadouts["combat"]["head"]["helm"] == str(hat.id)

    def test_selling_two_handed_purges_both_arm_refs(self):
        """A two-handed weapon is saved at BOTH ``arm.left.held``
        and ``arm.right.held``. Selling it must purge BOTH refs
        in one pass — otherwise ``$loadout load`` would fail half-
        way through when the second ref's lookup returns None."""
        p, (bow,) = _player_with("bow")
        p.equip(bow)  # multi-placed: arm.left.held + arm.right.held
        p.save_loadout("archer")
        assert p.loadouts["archer"]["arm.left"]["held"] == str(bow.id)
        assert p.loadouts["archer"]["arm.right"]["held"] == str(bow.id)

        p.remove(bow)
        p.sell(bow)

        # Both part-entries should be pruned (bow was the only
        # item on either arm).
        assert "arm.left" not in p.loadouts["archer"]
        assert "arm.right" not in p.loadouts["archer"]


class TestPersistence:
    def test_loadouts_round_trip_through_to_dict_from_dict(self):
        p, (hat,) = _player_with("mushroom_hat")
        p.equip(hat)
        p.save_loadout("combat")

        doc = p.to_dict()
        assert "loadouts" in doc
        assert "combat" in doc["loadouts"]

        with patch(
            "caldanai.lib.rpg.creatures.player.Inventory.from_list",
            return_value=p.inventory,
        ):
            doc["_id"] = p.id or "roundtrip-id"
            doc.setdefault("channel_id", p.channel_id)
            doc.setdefault("last_active", None)
            doc.setdefault("skills_schema_version", p.skills_schema_version)
            restored = Player.from_dict(doc)

        assert restored is not None
        assert "combat" in restored.loadouts
        assert restored.loadouts["combat"]["head"]["helm"] == str(hat.id)

    def test_empty_loadouts_written_to_saved_doc(self):
        """Loadouts field is ALWAYS written, including when empty.
        Pre-2026-04-22 we omitted on empty, which caused a real
        bug: clearing the last loadout left stale data in Mongo
        because ``$set`` doesn't remove missing fields. Writing
        ``loadouts: {}`` overwrites cleanly."""
        p, _ = _player_with()
        doc = p.to_dict()
        assert doc.get("loadouts") == {}

    def test_clearing_last_loadout_persists_empty_dict(self):
        """After clearing every loadout the player had saved, the
        next ``to_dict`` must write ``loadouts: {}`` so the
        ``$set`` DB update clobbers the previously-saved labels.
        Regression test for the 2026-04-22 TEST playtest bug
        where restart resurrected cleared loadouts."""
        p, _ = _player_with()
        p.save_loadout("one")
        p.save_loadout("two")
        assert len(p.loadouts) == 2

        p.clear_loadout("one")
        p.clear_loadout("two")
        assert p.loadouts == {}

        doc = p.to_dict()
        # Field must be present with the empty value — NOT absent.
        # $set with an empty dict overwrites the DB field; an
        # absent key leaves the prior value untouched.
        assert "loadouts" in doc
        assert doc["loadouts"] == {}
