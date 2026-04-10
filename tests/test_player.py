"""Tests for Caldanai.lib.rpg.creatures.player (Player class)."""

from math import floor
from unittest.mock import MagicMock, patch

import pytest

from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory import Inventory, Item
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from Caldanai.lib.rpg.inventory.stackables import Stackable
from bson.objectid import ObjectId


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player(**kwargs):
    """Create a Player with sensible test defaults."""
    defaults = dict(
        pid=ObjectId(),
        gid=100,
        uid=200,
        health=20,
        health_max=20,
        defense=6,
        dodge=6,
        gender="male",
        pronouns="he,him,his,his",
        weight_limit=100,
        clarks=50,
    )
    defaults.update(kwargs)
    p = Player(**defaults)
    # Attach a mock member so code referencing player.member works
    member = MagicMock()
    member.id = defaults["uid"]
    member.display_name = "TestPlayer"
    p.member = member
    p.name = member.display_name
    return p


def _make_item(name="widget", weight=1.0, value=10, quality=Qualities.ORDINARY, iid=None):
    return Item(
        iid=iid or ObjectId(),
        name=name,
        unit_weight=weight,
        unit_value=value,
        quality=quality,
    )


def _make_equipment(name="helm", slots=EquipmentSlots.HEAD, weight=2.0, value=20, iid=None):
    return Equipment(
        iid=iid or ObjectId(),
        name=name,
        slots=slots,
        unit_weight=weight,
        unit_value=value,
        quality=Qualities.ORDINARY,
    )


# ---------------------------------------------------------------------------
# apply_damage — Player overrides
# ---------------------------------------------------------------------------

class TestPlayerApplyDamage:
    def test_death_message(self):
        p = _make_player(health=5)
        msg = p.apply_damage(10)
        assert p.health == 0
        assert "crumples" in msg.lower() or "lifelessly" in msg.lower()
        assert p.is_dirty is True

    def test_resurrection_message(self):
        p = _make_player(health=0)
        msg = p.apply_damage(-5)
        assert p.health == 5
        assert "gasps" in msg.lower() or "life returns" in msg.lower()

    def test_no_special_message_on_normal_damage(self):
        p = _make_player(health=20)
        msg = p.apply_damage(3)
        assert msg == ""

    def test_dirty_flag_set_on_damage(self):
        p = _make_player(health=20)
        p.is_dirty = False
        p.apply_damage(1)
        assert p.is_dirty is True


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_to_dict_includes_health_regen(self):
        p = _make_player(health_regen=5)
        d = p.to_dict()
        assert "health_regen" in d
        assert d["health_regen"] == 5

    def test_to_dict_keys(self):
        p = _make_player()
        d = p.to_dict()
        for key in ("user_id", "guild_id", "defense", "dodge", "health",
                     "health_max", "clarks", "rolls", "skills", "gender",
                     "pronouns", "items", "equip_slots", "health_regen"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_omits_id_when_none(self):
        p = _make_player(pid=None)
        d = p.to_dict()
        assert "_id" not in d

    @patch("Caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_from_dict_returns_none_for_none(self, _):
        assert Player.from_dict(None) is None

    @patch("Caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_from_dict_round_trip_basic_fields(self, _):
        """Verify basic scalar fields survive a round-trip."""
        pid = ObjectId()
        d = {
            "_id": pid,
            "user_id": 200,
            "guild_id": 100,
            "weight_limit": 100,
            "joined": None,
            "clarks": 42,
            "defense": 8,
            "dodge": 7,
            "health": 15,
            "health_max": 20,
            "items": [],
            "rolls": {"d4": [0]*4, "d6": [0]*6, "d8": [0]*8,
                       "d10": [0]*10, "d12": [0]*12, "d20": [0]*20},
            "skills": {"unarmed": 100},
            "gender": "female",
            "pronouns": "she,her,hers,her",
            "equip_slots": {s.name: None for s in EquipmentSlots
                            if not EquipmentSlots.exclude_from_output(s.name)},
            "last_active": None,
            "health_regen": 3,
        }
        p = Player.from_dict(d)
        assert p is not None
        assert p.id == pid
        assert p.clarks == 42
        assert p.health == 15
        assert p.health_regen == 3
        assert p.skills == {"unarmed": 100}


# ---------------------------------------------------------------------------
# equip / replace_equipment / remove
# ---------------------------------------------------------------------------

class TestEquipment:
    def test_equip_to_auto_slot(self):
        p = _make_player()
        item = _make_equipment(name="cap", slots=EquipmentSlots.HEAD)
        success, msg = p.equip(item)
        assert success is True
        assert p.equip_slots[EquipmentSlots.HEAD.name] == item
        assert p.is_dirty is True

    def test_equip_already_equipped(self):
        p = _make_player()
        item = _make_equipment(name="cap", slots=EquipmentSlots.HEAD)
        p.equip(item)
        success, msg = p.equip(item)
        assert success is False
        assert "already equipped" in msg.lower()

    def test_replace_equipment(self):
        p = _make_player()
        item1 = _make_equipment(name="old cap", slots=EquipmentSlots.HEAD)
        item2 = _make_equipment(name="new cap", slots=EquipmentSlots.HEAD)
        p.equip(item1)
        success, replaced = p.replace_equipment(item2, EquipmentSlots.HEAD.name)
        assert success is True
        assert replaced == item1
        assert p.equip_slots[EquipmentSlots.HEAD.name] == item2

    def test_remove_equipped_item(self):
        p = _make_player()
        item = _make_equipment(name="cap", slots=EquipmentSlots.HEAD)
        p.equip(item)
        msg = p.remove(item)
        assert "removed" in msg.lower()
        assert p.equip_slots[EquipmentSlots.HEAD.name] is None

    def test_remove_none_returns_message(self):
        p = _make_player()
        msg = p.remove(None)
        assert "nothing" in msg.lower()

    def test_remove_unequipped_item(self):
        p = _make_player()
        item = _make_equipment(name="cap", slots=EquipmentSlots.HEAD)
        msg = p.remove(item)
        assert "does not seem" in msg.lower()


# ---------------------------------------------------------------------------
# give_item — weight limit
# ---------------------------------------------------------------------------

class TestGiveItem:
    def test_give_item_under_limit(self):
        p = _make_player(weight_limit=100)
        item = _make_item(weight=5.0)
        assert p.give_item(item) is True
        assert p.is_dirty is True

    def test_give_item_over_limit_rejected(self):
        p = _make_player(weight_limit=10)
        item = _make_item(weight=20.0)
        p.is_dirty = False
        assert p.give_item(item) is False
        assert p.is_dirty is False


# ---------------------------------------------------------------------------
# sell and take_item
# ---------------------------------------------------------------------------

class TestSellAndTakeItem:
    def test_sell_none_item(self):
        p = _make_player()
        msg, value = p.sell(None)
        assert value == 0
        assert "no item" in msg.lower()

    def test_sell_item(self):
        p = _make_player(clarks=100)
        item = _make_item(name="gem", value=25, weight=1.0)
        p.inventory.add(item)
        msg, value = p.sell(item)
        assert value == item.unit_value
        assert p.clarks == 100 + item.unit_value

    def test_take_item_removes_from_inventory(self):
        p = _make_player()
        item = _make_item(name="rock", weight=1.0)
        p.inventory.add(item)
        result = p.take_item(item)
        assert result == item

    def test_take_item_returns_none_if_equipped(self):
        """Items that are currently equipped cannot be taken."""
        p = _make_player()
        equip = _make_equipment(name="helm", slots=EquipmentSlots.HEAD)
        p.inventory.add(equip)
        p.equip(equip)
        result = p.take_item(equip)
        assert result is None


# ---------------------------------------------------------------------------
# gain_skill_experience
# ---------------------------------------------------------------------------

class TestGainSkillExperience:
    def test_new_skill_initializes_and_gains(self):
        p = _make_player()
        p.gain_skill_experience("swords")
        assert "swords" in p.skills
        assert p.skills["swords"] > 0
        assert p.is_dirty is True

    def test_two_handed_double_xp(self):
        p = _make_player()
        p.gain_skill_experience("two-handed swords")
        xp_two_handed = p.skills["two-handed swords"]

        p2 = _make_player()
        p2.gain_skill_experience("swords")
        xp_one_handed = p2.skills["swords"]

        assert xp_two_handed == 2 * xp_one_handed

    def test_no_gain_at_level_20(self):
        """At skill level 20, no more XP should be added."""
        p = _make_player()
        # Level 20 requires a very large xp value; formula:
        # level = min(20, floor((25 + (5*(125+xp))**0.5) / 50))
        # Set xp high enough that level is 20
        p.skills["swords"] = 999999
        assert p.get_skill_level("swords") == 20
        old_xp = p.skills["swords"]
        p.gain_skill_experience("swords")
        assert p.skills["swords"] == old_xp


# ---------------------------------------------------------------------------
# do_attack — event-driven refactor
# ---------------------------------------------------------------------------

class TestDoAttack:
    def test_calls_target_on_attacked(self):
        """Player.do_attack should delegate to target.on_attacked per hand."""
        p = _make_player()
        target = MagicMock()
        target.on_attacked.return_value = ("attack msg```\n", 5)
        target.get_dodge.return_value = 10

        msg, dmg = p.do_attack(target)

        # Unarmed player attacks with both fists — on_attacked called twice
        assert target.on_attacked.call_count == 2
        assert dmg == 10  # 5 per hand

    def test_two_handed_calls_on_attacked_once(self):
        """Two-handed weapon should only call on_attacked once."""
        p = _make_player()
        weapon = MagicMock(spec=Weapon)
        weapon.slots = EquipmentSlots.LEFT_HELD | EquipmentSlots.RIGHT_HELD | EquipmentSlots.MULTI_SLOT
        weapon.damage_type = None
        weapon.skill = "two-handed swords"
        weapon.attack = "2d6"
        weapon.bonus = 2
        p.equip_slots[EquipmentSlots.LEFT_HELD.name] = weapon
        p.equip_slots[EquipmentSlots.RIGHT_HELD.name] = None

        target = MagicMock()
        target.on_attacked.return_value = ("attack msg```\n", 8)
        target.get_dodge.return_value = 10

        msg, dmg = p.do_attack(target)

        assert target.on_attacked.call_count == 1
        assert dmg == 8

    def test_skill_xp_granted_on_hit(self):
        """Skill XP should be granted when on_attacked returns damage > 0."""
        p = _make_player()
        target = MagicMock()
        target.on_attacked.return_value = ("hit```\n", 5)
        target.get_dodge.return_value = 10

        p.do_attack(target)

        assert "unarmed" in p.skills
        assert p.skills["unarmed"] > 0

    def test_no_skill_xp_on_miss(self):
        """No skill XP when on_attacked returns 0 damage (miss)."""
        p = _make_player()
        target = MagicMock()
        target.on_attacked.return_value = ("miss```\n", 0)
        target.get_dodge.return_value = 10

        p.do_attack(target)

        assert p.skills.get("unarmed", 0) == 0

    def test_monster_can_modify_damage(self):
        """Monster's on_attacked override can reduce damage (e.g., math teacher)."""
        p = _make_player()
        target = MagicMock()
        # Monster halves prime damage
        target.on_attacked.side_effect = [
            ("left hit```\n", 3),   # left hand: monster reduced from 7 to 3
            ("right hit```\n", 4),  # right hand
        ]
        target.get_dodge.return_value = 10

        msg, dmg = p.do_attack(target)

        assert dmg == 7  # 3 + 4, not what player would have calculated alone

    def test_roll_counts_updated(self):
        """Roll statistics should be tracked after attack."""
        p = _make_player()
        target = MagicMock()
        target.on_attacked.return_value = ("msg```\n", 1)
        target.get_dodge.return_value = 10

        old_d20 = [c for c in p.rolls["d20"]]
        p.do_attack(target)

        # At least one d20 roll should have been recorded
        assert p.rolls["d20"] != old_d20


class TestMakeAttackRolls:
    def test_unarmed_uses_d4(self):
        p = _make_player()
        atk, dmg = p._make_attack_rolls(None)
        assert atk.sides == 20  # always d20 for attack
        assert dmg.sides == 4   # d4 for unarmed

    def test_weapon_uses_weapon_dice(self):
        p = _make_player()
        weapon = MagicMock(spec=Weapon)
        weapon.skill = "swords"
        weapon.attack = "3d8"
        weapon.bonus = 5
        atk, dmg = p._make_attack_rolls(weapon)
        assert atk.sides == 20
        assert dmg.sides == 8
