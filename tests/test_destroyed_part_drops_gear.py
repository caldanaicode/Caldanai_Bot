"""Regression tests for stage 2a of the equipment-on-parts arc:
items at a destroyed body part return to the inventory pool.

Semantics (from ``project_equipment_on_parts`` memory, 2026-04-18
clarification): items are NOT lost or broken when a limb is
maimed. They stay in inventory; only the placements clear, so
the player loses the USE of those items until the part heals.

The trigger is ``Player.apply_damage`` detecting a body part
transitioning from not-USELESS to USELESS on a given call. An
already-USELESS part does not re-drop its gear — idempotent
across multiple damage hits to an already-dead limb.

Multi-placed items (two-handed weapons, paired gear) come off
FULLY when any one of their placements is at the destroyed
part. A two-hander can't be wielded with one good arm, so
dropping only the destroyed-arm placement and leaving the
other arm holding the reference would be a stuck state.
"""

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import InjuryLevels
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _player_with_inventory(*plugin_names):
    p = Player(uid=1, gid=2, cid=3)
    items = []
    for name in plugin_names:
        item = Inventory.load_item(name=name)
        p.inventory.add(item)
        items.append(item)
    return p, items


class TestSingleSlotDrop:
    def test_helm_returns_to_inventory_on_head_destroy(self):
        p, (hat,) = _player_with_inventory("mushroom_hat")
        p.equip(hat)
        assert p.part_equipment["head"]["worn"] is hat

        head = p.get_part("head")
        p.apply_damage(head.health, target_part=head)

        assert head.get_injury_level() == InjuryLevels.USELESS
        assert p.part_equipment["head"]["worn"] is None
        # Item stays in inventory — the point of the whole design.
        assert p.inventory[hat.id] is hat

    def test_wand_returns_on_left_arm_destroy(self):
        p, (wand,) = _player_with_inventory("wand")
        p.equip(wand)
        assert p.part_equipment["hand.left"]["held"] is wand

        left_arm = p.get_part("arm.left")
        p.apply_damage(left_arm.health, target_part=left_arm)

        assert left_arm.get_injury_level() == InjuryLevels.USELESS
        assert p.part_equipment["hand.left"]["held"] is None
        assert p.inventory[wand.id] is wand

    def test_other_parts_unaffected(self):
        """Destroying one part must not disturb items on other
        parts — only the placements at the destroyed part clear."""
        p, (hat, wand) = _player_with_inventory("mushroom_hat", "wand")
        p.equip(hat)
        p.equip(wand)

        head = p.get_part("head")
        p.apply_damage(head.health, target_part=head)

        # Head helm dropped, arm.left.held untouched.
        assert p.part_equipment["head"]["worn"] is None
        assert p.part_equipment["hand.left"]["held"] is wand


class TestMultiSlotDrop:
    def test_two_handed_weapon_drops_from_both_arms(self):
        """A two-handed weapon shares its ``Item`` reference across
        both arms. Destroying ONE arm must clear BOTH placements —
        the weapon can't be wielded with only one good arm, so
        leaving it visible on the intact arm would be a stuck
        state (player can't equip anything new there because the
        phantom two-hander is already occupying it)."""
        p, (bow,) = _player_with_inventory("bow")
        p.equip(bow)
        assert p.part_equipment["hand.left"]["held"] is bow
        assert p.part_equipment["hand.right"]["held"] is bow

        left_arm = p.get_part("arm.left")
        p.apply_damage(left_arm.health, target_part=left_arm)

        assert p.part_equipment["hand.left"]["held"] is None
        assert p.part_equipment["hand.right"]["held"] is None, (
            "Two-hander should not linger on the intact arm"
        )
        assert p.inventory[bow.id] is bow

    def test_two_handed_drop_leaves_arms_available_for_new_equip(self):
        """Post-drop, both arm.held placements are empty (the two-
        hander was cleared off both sides), so a new one-handed
        item can be explicitly equipped to the good arm via ``@r``.
        The equip code doesn't itself check injury — a weapon on a
        useless arm is allowed but combat just won't fire a source
        from it (``get_attack_sources`` filters by ``_is_arm_usable``
        independently). When the arm heals, the weapon becomes
        usable again without needing a re-equip."""
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots

        p, (bow, wand) = _player_with_inventory("bow", "wand")
        p.equip(bow)
        left_arm = p.get_part("arm.left")
        p.apply_damage(left_arm.health, target_part=left_arm)

        # Both arms' held slots are now empty. Explicitly equip
        # the wand to the right to verify the placement is free.
        ok, _ = p.equip(wand, EquipmentSlots.RIGHT_HELD)
        assert ok
        assert p.part_equipment["hand.right"]["held"] is wand
        assert p.part_equipment["hand.left"]["held"] is None


class TestIdempotency:
    def test_already_useless_part_does_not_re_drop(self):
        """Repeated damage to an already-dead part should not
        invoke the drop logic again — the gear already left on the
        first transition, and invoking ``remove()`` on a None
        placement would be a no-op but noisy."""
        p, (wand,) = _player_with_inventory("wand")
        p.equip(wand)
        left_arm = p.get_part("arm.left")
        p.apply_damage(left_arm.health, target_part=left_arm)

        # Sanity: wand already dropped from the first transition.
        assert p.part_equipment["hand.left"]["held"] is None

        # Now re-equip the wand (it's still in inventory). A
        # second damage hit to the already-useless arm must NOT
        # trigger another drop. Simulate a damage tick.
        # Re-equip first:
        ok, _ = p.equip(wand)
        assert ok, "Re-equip should succeed — arm is useless but this is a test state"
        # Force re-equip onto the left arm specifically for the test
        # (equip auto-routes; in reality the left arm being USELESS
        # would steer it to right, so write directly for this test).
        p.part_equipment["hand.right"]["held"] = None  # undo auto-right
        p.part_equipment["hand.left"]["held"] = wand

        # Damage again — already useless. Should not trigger drop.
        p.apply_damage(1, target_part=left_arm)
        assert p.part_equipment["hand.left"]["held"] is wand, (
            "Already-useless part must not re-trigger the drop"
        )


class TestNonUselessDamage:
    def test_minor_damage_does_not_drop_gear(self):
        """A hit that injures but doesn't destroy a part leaves
        gear in place — the player can still use it."""
        p, (hat,) = _player_with_inventory("mushroom_hat")
        p.equip(hat)

        head = p.get_part("head")
        # Hit for less than full health — still injured but not useless.
        p.apply_damage(max(1, head.health // 2), target_part=head)

        assert head.get_injury_level() != InjuryLevels.USELESS
        assert p.part_equipment["head"]["worn"] is hat


class TestArmorBonusStopsApplying:
    """The bonus from an item on a destroyed part should stop
    contributing to the player's aggregate stats after the drop —
    that's a natural consequence of the placement clearing,
    since ``get_armor_bonuses`` walks live placements only."""

    def test_dodge_bonus_stops_after_helm_drops(self):
        """After the helm drops on head destruction, its dodge
        contribution stops applying — the aggregate falls to
        whatever other equipped items provide (zero in this
        baseline). Doesn't assert a specific multiplier-scaled
        value for the helm; just that the contribution goes away."""
        p, (hat,) = _player_with_inventory("mushroom_hat")
        p.equip(hat)

        base_dodge = p.get_armor_bonuses("dodge").get("dodge", 0)
        assert base_dodge != 0, (
            "mushroom_hat should contribute a non-zero dodge bonus "
            "while equipped"
        )

        head = p.get_part("head")
        p.apply_damage(head.health, target_part=head)

        post_drop = p.get_armor_bonuses("dodge").get("dodge", 0)
        assert post_drop == 0, (
            "Dropped helm's dodge bonus must stop contributing"
        )


class TestDeathOrdering:
    """When a head-destroy blow also kills the player, the order
    of side effects is: damage applied → gear dropped → death
    narrative returned. All three must fire on the same call."""

    def test_head_destroy_drops_helm_and_returns_death_narrative(self):
        p, (hat,) = _player_with_inventory("mushroom_hat")
        p.equip(hat)

        head = p.get_part("head")
        result = p.apply_damage(head.health, target_part=head)

        # All three post-conditions on the same call:
        # 1. Damage applied → part useless
        assert head.get_injury_level() == InjuryLevels.USELESS
        # 2. Gear dropped → placement empty, item back in inventory
        assert p.part_equipment["head"]["worn"] is None
        assert p.inventory[hat.id] is hat
        # 3. Death narrative returned (head is critical)
        assert p.is_dead() is True
        assert result and "crumples" in result.lower()


class TestReviveStickiness:
    """A revived player does NOT automatically re-equip gear that
    was dropped on death. The dropped state is sticky until the
    player manually re-equips."""

    def test_heal_fully_does_not_re_equip_dropped_helm(self):
        p, (hat,) = _player_with_inventory("mushroom_hat")
        p.equip(hat)
        head = p.get_part("head")
        p.apply_damage(head.health, target_part=head)

        # Dropped + dead. Full divine heal.
        p.heal_fully()
        assert p.is_dead() is False
        assert head.get_injury_level() == InjuryLevels.NONE
        # Dropped state sticks through revive.
        assert p.part_equipment["head"]["worn"] is None
        assert p.inventory[hat.id] is hat


class TestPersistenceRoundTrip:
    """Dropped placements serialize/deserialize cleanly through
    ``to_dict`` / ``from_dict``. ``part_equipment`` only writes
    non-None placements, so an empty placement simply doesn't
    appear in the saved dict and rehydrates back to None."""

    def test_dropped_placements_survive_save_load_cycle(self):
        from unittest.mock import patch
        p, (hat, wand) = _player_with_inventory("mushroom_hat", "wand")
        p.equip(hat)
        p.equip(wand)

        # Destroy head → helm drops.
        head = p.get_part("head")
        p.apply_damage(head.health, target_part=head)
        assert p.part_equipment["head"]["worn"] is None
        assert p.part_equipment["hand.left"]["held"] is wand

        doc = p.to_dict()
        # Saved shape: head.worn is NOT in the serialized dict
        # (only non-None placements are written).
        assert "head" not in doc["part_equipment"] or (
            "worn" not in doc["part_equipment"].get("head", {})
        )
        assert doc["part_equipment"]["hand.left"]["held"] == str(wand.id)

        # Round-trip via from_dict. Use patch to stub inventory
        # rebuilding since we're not persisting items here, just
        # the placements shape.
        with patch("caldanai.lib.rpg.creatures.player.Inventory.from_list") as mock_inv:
            mock_inv.return_value = p.inventory
            doc["_id"] = p.id or "reload-id"
            # Fill minimal required fields for from_dict
            doc.setdefault("channel_id", p.channel_id)
            doc.setdefault("last_active", None)
            doc.setdefault("skills_schema_version", p.skills_schema_version)
            restored = Player.from_dict(doc)

        assert restored is not None
        assert restored.part_equipment["head"]["worn"] is None
        assert restored.part_equipment["hand.left"]["held"] is wand


class TestMultiPartItemDrop:
    """A multi-part item (e.g. ``CAPE | NECK | MULTI_SLOT`` like
    the old high-collared cape) occupies placements on DIFFERENT
    body parts. Destroying ANY one of those parts must drop it
    from ALL its placements — the item can't functionally split
    between intact and destroyed anatomy.

    No current item has this exact shape (high-collared_cape was
    simplified to single-slot ``CAPE`` in the migration), but the
    design supports it and future items may use it. This test
    constructs a multi-part item inline to lock the contract."""

    def test_multi_part_item_drops_from_all_placements(self):
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        from caldanai.lib.rpg.inventory.equipment.armor import Armor

        # Construct an item that spans torso.cape + neck.amulet
        # via the MULTI_SLOT flag, the same shape old high-
        # collared-cape used to have.
        item = Armor(
            name="twin-anchored cloak",
            desc="Anchored at the neck and draped over the torso.",
            unit_weight=1.0,
            unit_value=1,
            image=None,
            slots=EquipmentSlots.CAPE | EquipmentSlots.NECK | EquipmentSlots.MULTI_SLOT,
            bonuses={"dodge": 0},
        )
        p = Player(uid=1, gid=2, cid=3)
        p.inventory.add(item)
        ok, _ = p.equip(item)
        assert ok, "Multi-part item should equip to both placements"
        assert p.part_equipment["torso"]["outer"] is item
        assert p.part_equipment["neck"]["accent"] is item

        # Destroy the neck — must drop from BOTH placements (the
        # intact torso placement can't keep a phantom reference
        # to an item that's also anchored on a destroyed limb).
        neck = p.get_part("neck")
        p.apply_damage(neck.health, target_part=neck)

        assert neck.get_injury_level() == InjuryLevels.USELESS
        assert p.part_equipment["neck"]["accent"] is None
        assert p.part_equipment["torso"]["outer"] is None, (
            "Multi-part item must drop from every placement, not just "
            "the one on the destroyed part"
        )
        assert p.inventory[item.id] is item


class TestIsDirtyFlag:
    def test_drop_marks_player_dirty(self):
        """The drop path invokes ``remove()`` which sets is_dirty.
        Damage itself also sets is_dirty. Either way, the player
        must be dirty after a drop so the next save-tick persists
        the cleared placements."""
        p, (wand,) = _player_with_inventory("wand")
        p.equip(wand)
        p.is_dirty = False

        left_arm = p.get_part("arm.left")
        p.apply_damage(left_arm.health, target_part=left_arm)

        assert p.is_dirty is True
