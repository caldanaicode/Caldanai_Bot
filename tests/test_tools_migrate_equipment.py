"""Regression tests for ``tools/migrate_equipment_to_parts.py``.

The migration is a one-shot cutover — if it's wrong, equipped
gear silently vanishes or lands in the wrong part. These tests
pin the translation logic at the unit level so the tool can be
trusted before a production dry-run.

Scope: ``_compute_part_equipment`` transforms one doc's
``equip_slots`` + ``items`` list into the new ``part_equipment``
shape. Input shapes covered:

- Simple single-slot items (hat, shirt, cape).
- Multi-slot two-handed weapons (same item id at both
  ``arm.*.held`` placements).
- Already-removed slots (SHOULDERS / ABDOMEN) with items
  — warn and skip rather than silently drop.
- Items whose slots mask changed in code
  (``high-collared_cape`` from NECK+CAPE to just CAPE).
- Empty / partial ``equip_slots`` dicts.
"""

from bson import ObjectId

from caldanai.lib.rpg.inventory import Inventory
from tools.migrate_equipment_to_parts import _compute_part_equipment


Inventory.discover_items()


def _item_dict(plugin: str, iid: ObjectId | None = None) -> dict:
    """Build a minimal item doc shaped like what the DB stores."""
    return {
        "_id": iid or ObjectId(),
        "plugin": plugin,
    }


class TestSingleSlotItems:
    def test_head_slot_maps_to_head_helm(self):
        hat = _item_dict("mushroom_hat")
        new_shape, warnings = _compute_part_equipment(
            legacy={"HEAD": hat["_id"]},
            items_list=[hat],
        )
        assert warnings == []
        assert new_shape == {"head": {"helm": str(hat["_id"])}}

    def test_torso_slot_maps_to_torso_chest(self):
        shirt = _item_dict("tee_shirt")
        new_shape, _ = _compute_part_equipment(
            legacy={"TORSO": shirt["_id"]},
            items_list=[shirt],
        )
        assert new_shape == {"torso": {"chest": str(shirt["_id"])}}

    def test_face_slot_maps_to_head_face(self):
        bandanna = _item_dict("bandanna")
        new_shape, _ = _compute_part_equipment(
            legacy={"FACE": bandanna["_id"]},
            items_list=[bandanna],
        )
        assert new_shape == {"head": {"face": str(bandanna["_id"])}}

    def test_cape_slot_maps_to_torso_cape(self):
        cape = _item_dict("cape")
        new_shape, _ = _compute_part_equipment(
            legacy={"CAPE": cape["_id"]},
            items_list=[cape],
        )
        assert new_shape == {"torso": {"cape": str(cape["_id"])}}

    def test_left_held_weapon_lands_on_arm_left(self):
        weapon = _item_dict("shortsword")
        new_shape, _ = _compute_part_equipment(
            legacy={"LEFT_HELD": weapon["_id"]},
            items_list=[weapon],
        )
        assert new_shape == {"arm.left": {"held": str(weapon["_id"])}}

    def test_right_held_weapon_lands_on_arm_right(self):
        weapon = _item_dict("shortsword")
        new_shape, _ = _compute_part_equipment(
            legacy={"RIGHT_HELD": weapon["_id"]},
            items_list=[weapon],
        )
        assert new_shape == {"arm.right": {"held": str(weapon["_id"])}}


class TestMultiSlot:
    def test_two_handed_weapon_lands_on_both_arms_same_id(self):
        """Two-handed weapons share the same Item reference across
        both arms — the migration must produce the same item id at
        both ``arm.left.held`` and ``arm.right.held``."""
        spear = _item_dict("spear")
        new_shape, warnings = _compute_part_equipment(
            legacy={
                "LEFT_HELD": spear["_id"],
                "RIGHT_HELD": spear["_id"],
            },
            items_list=[spear],
        )
        assert warnings == []
        iid = str(spear["_id"])
        assert new_shape == {
            "arm.left": {"held": iid},
            "arm.right": {"held": iid},
        }

    def test_two_handed_single_legacy_entry_still_covers_both_arms(self):
        """Even if the legacy doc only has one entry (rare —
        corrupt writes), the item's declared MULTI_SLOT mask
        drives placement of both arms. Migration uses the item's
        CURRENT slots attribute, not the legacy entry count."""
        bow = _item_dict("bow")
        new_shape, _ = _compute_part_equipment(
            legacy={"LEFT_HELD": bow["_id"]},
            items_list=[bow],
        )
        iid = str(bow["_id"])
        assert new_shape == {
            "arm.left": {"held": iid},
            "arm.right": {"held": iid},
        }


class TestHighCollaredCapeReroute:
    """The 2026-04-21 migration dropped ``NECK | CAPE | MULTI_SLOT``
    from ``high-collared_cape`` and made it a single-slot ``CAPE``
    item. Docs stored before that change have the cape registered
    at BOTH ``NECK`` and ``CAPE`` legacy slots — migration must
    resolve to the item's current (single) slot."""

    def test_reroutes_to_torso_cape_only(self):
        hc_cape = _item_dict("high-collared_cape")
        new_shape, warnings = _compute_part_equipment(
            legacy={
                "NECK": hc_cape["_id"],
                "CAPE": hc_cape["_id"],
            },
            items_list=[hc_cape],
        )
        # Item's CURRENT .slots is just CAPE, so placement is
        # only ``torso.cape`` — no lingering ``neck.amulet``.
        assert new_shape == {"torso": {"cape": str(hc_cape["_id"])}}
        assert warnings == []


class TestRemovedSlots:
    def test_empty_removed_slot_is_silent(self):
        """``SHOULDERS`` / ``ABDOMEN`` were deleted. Legacy docs
        with None in those slots must migrate silently — the slot
        was declared but never filled."""
        new_shape, warnings = _compute_part_equipment(
            legacy={"SHOULDERS": None, "ABDOMEN": None},
            items_list=[],
        )
        assert new_shape == {}
        assert warnings == []

    def test_populated_removed_slot_warns_and_drops(self):
        """If a player somehow had an item in ABDOMEN (we never
        shipped one but a third-party fork might have), log and
        skip rather than silently drop it into nowhere. The item
        stays in inventory so it's recoverable."""
        phantom = _item_dict("mushroom_hat")  # any item
        new_shape, warnings = _compute_part_equipment(
            legacy={"ABDOMEN": phantom["_id"]},
            items_list=[phantom],
        )
        assert new_shape == {}
        assert len(warnings) == 1
        assert "ABDOMEN" in warnings[0]


class TestEdgeCases:
    def test_empty_equip_slots_returns_empty(self):
        new_shape, warnings = _compute_part_equipment(
            legacy={}, items_list=[],
        )
        assert new_shape == {}
        assert warnings == []

    def test_all_none_slots_returns_empty(self):
        """Legacy docs always pre-seeded every slot to None.
        Migration must collapse those to an empty dict, not a
        dict-of-every-slot-None."""
        legacy = {
            "HEAD": None, "TORSO": None, "LEFT_HELD": None,
            "RIGHT_HELD": None, "CAPE": None, "FACE": None,
            "NECK": None, "WAIST": None, "GLOVES": None,
            "ARMS": None, "FOREARMS": None, "LEGS": None,
            "SHINS": None, "FEET": None, "LEFT_EAR": None,
            "RIGHT_EAR": None, "LEFT_RING": None, "RIGHT_RING": None,
            "AMULET": None,
        }
        new_shape, warnings = _compute_part_equipment(
            legacy=legacy, items_list=[],
        )
        assert new_shape == {}
        assert warnings == []

    def test_missing_item_from_inventory_warns(self):
        """If ``equip_slots`` references an item id not present in
        the inventory list (data corruption), warn and skip. Don't
        silently drop."""
        phantom_id = ObjectId()
        new_shape, warnings = _compute_part_equipment(
            legacy={"HEAD": phantom_id},
            items_list=[],  # phantom not present
        )
        assert new_shape == {}
        assert len(warnings) == 1
        assert str(phantom_id) in warnings[0]


class TestFullPlayerShape:
    def test_dressed_humanoid_migrates_completely(self):
        """A fully-equipped player exercises single-slot, multi-
        slot, and torso-stack cases in one shot."""
        helm = _item_dict("mushroom_hat")
        face = _item_dict("bandanna")
        shirt = _item_dict("tee_shirt")
        cape = _item_dict("cape")
        spear = _item_dict("spear")  # two-handed
        legacy = {
            "HEAD": helm["_id"],
            "FACE": face["_id"],
            "TORSO": shirt["_id"],
            "CAPE": cape["_id"],
            "LEFT_HELD": spear["_id"],
            "RIGHT_HELD": spear["_id"],
            # Empty placeholders that legacy docs ship with
            "NECK": None, "WAIST": None, "LEFT_RING": None,
        }
        new_shape, warnings = _compute_part_equipment(
            legacy=legacy,
            items_list=[helm, face, shirt, cape, spear],
        )
        assert warnings == []
        assert new_shape == {
            "head": {
                "helm": str(helm["_id"]),
                "face": str(face["_id"]),
            },
            "torso": {
                "chest": str(shirt["_id"]),
                "cape": str(cape["_id"]),
            },
            "arm.left": {"held": str(spear["_id"])},
            "arm.right": {"held": str(spear["_id"])},
        }
