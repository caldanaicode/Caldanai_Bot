"""Tests for Caldanai.lib.rpg.creatures.player (Player class)."""

from math import floor
from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory import Inventory, Item
from caldanai.lib.rpg.inventory.equipment import Equipment
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from caldanai.lib.rpg.inventory.stackables import Stackable
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
                     "pronouns", "items", "part_equipment", "health_regen"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_omits_id_when_none(self):
        p = _make_player(pid=None)
        d = p.to_dict()
        assert "_id" not in d

    @patch("caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_from_dict_returns_none_for_none(self, _):
        assert Player.from_dict(None) is None

    @patch("caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
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
            "skills": {"unarmed bludgeoning": 100},
            "gender": "female",
            "pronouns": "she,her,hers,her",
            "part_equipment": {},
            "last_active": None,
            "health_regen": 3,
            # Doc is already on the current skills schema, so
            # ``_migrate_skills_if_needed`` is a no-op and the XP
            # round-trips unchanged. See TestSkillsMigration for the
            # legacy-doc migration behavior.
            "skills_schema_version": 2,
        }
        p = Player.from_dict(d)
        assert p is not None
        assert p.id == pid
        assert p.clarks == 42
        assert p.health == 15
        assert p.health_regen == 3
        assert p.skills == {"unarmed bludgeoning": 100}


# ---------------------------------------------------------------------------
# equip / replace_equipment / remove
# ---------------------------------------------------------------------------

class TestEquipment:
    def test_equip_to_auto_slot(self):
        p = _make_player()
        item = _make_equipment(name="cap", slots=EquipmentSlots.HEAD)
        success, msg = p.equip(item)
        assert success is True
        assert p.part_equipment["head"]["worn"] == item
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
        success, replaced = p.replace_equipment(item2, "head", "worn")
        assert success is True
        assert replaced == item1
        assert p.part_equipment["head"]["worn"] == item2

    def test_replace_two_handed_with_one_handed_clears_both_arms(self):
        """Playtest bug 2026-04-22: equipping a one-handed weapon to
        one arm while a two-handed weapon was already equipped left
        the two-handed phantom at the OTHER arm. ``replace_equipment``
        must walk every placement of the displaced item and clear
        the orphan references."""
        from caldanai.lib.rpg.inventory import Inventory
        from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin

        BodyPartPlugin.load_plugins()
        Inventory.discover_items()

        p = Player(uid=1, gid=2, cid=3)
        bow = Inventory.load_item(name="bow")  # two-handed
        rock = Inventory.load_item(name="rock")  # one-handed
        p.inventory.add(bow)
        p.inventory.add(rock)
        p.equip(bow)

        # Sanity: both arms hold the same bow instance.
        assert p.part_equipment["hand.left"]["held"] is bow
        assert p.part_equipment["hand.right"]["held"] is bow

        # Equip the rock to the right arm specifically (the cog
        # narrows RIGHT_SIDE & rock.slots → RIGHT_HELD before calling).
        p.equip(rock, EquipmentSlots.RIGHT_HELD)

        assert p.part_equipment["hand.right"]["held"] is rock
        assert p.part_equipment["hand.left"]["held"] is None, (
            "Left arm still holds the displaced two-hander (phantom)"
        )

    def test_equip_refuses_destroyed_specific_slot(self):
        """Playtest bug 2026-04-26: ``$equip wand@r`` succeeded
        when the right arm was destroyed (cascading hand.right to
        USELESS via ancestor-destroyed). Specific-slot equip must
        refuse with an informative message rather than silently
        riding the placement on a part the player no longer has."""
        p = _make_player()
        wand = _make_equipment(name="wand", slots=EquipmentSlots.RIGHT_HELD)
        # Destroy the right arm — hand.right cascades to USELESS
        # via BodyPart.is_destroyed walking ancestors.
        arm = next(part for part in p.body_parts if part.name == "arm.right")
        arm.health = 0

        success, msg = p.equip(wand, EquipmentSlots.RIGHT_HELD)
        assert success is False
        assert "damaged" in msg.lower()
        assert p.part_equipment["hand.right"]["held"] is None

    def test_equip_auto_skips_destroyed_lands_on_healthy(self):
        """Auto-equip must skip destroyed placements and land on
        the surviving counterpart. Player with a destroyed left
        arm `$equip glove` should land on hand.right."""
        p = _make_player()
        glove = _make_equipment(name="glove", slots=EquipmentSlots.GLOVES)
        arm = next(part for part in p.body_parts if part.name == "arm.left")
        arm.health = 0

        success, _ = p.equip(glove)
        assert success is True
        assert p.part_equipment["hand.right"]["worn"] is glove
        assert p.part_equipment["hand.left"]["worn"] is None

    def test_equip_multi_slot_refuses_when_any_part_destroyed(self):
        """Two-handed weapons need every required placement
        intact — equipping a bow with one severed arm would
        otherwise leave a half-wielded phantom reference."""
        from caldanai.lib.rpg.inventory import Inventory
        from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin

        BodyPartPlugin.load_plugins()
        Inventory.discover_items()

        p = Player(uid=1, gid=2, cid=3)
        bow = Inventory.load_item(name="bow")
        p.inventory.add(bow)
        arm = next(part for part in p.body_parts if part.name == "arm.right")
        arm.health = 0

        success, msg = p.equip(bow)
        assert success is False
        assert "damaged" in msg.lower()
        assert p.part_equipment["hand.left"]["held"] is None
        assert p.part_equipment["hand.right"]["held"] is None

    def test_remove_equipped_item(self):
        p = _make_player()
        item = _make_equipment(name="cap", slots=EquipmentSlots.HEAD)
        p.equip(item)
        msg = p.remove(item)
        assert "removed" in msg.lower()
        assert p.part_equipment["head"]["worn"] is None

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
        # Q.6 — two-handed doubling applies on the hit path; the
        # miss-path floor is a flat 2 XP regardless of skill.
        p = _make_player()
        p.gain_skill_experience("two-handed swords", damage=10, bleed_rate=0.7)
        xp_two_handed = p.skills["two-handed swords"]

        p2 = _make_player()
        p2.gain_skill_experience("swords", damage=10, bleed_rate=0.7)
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

class TestGetAttackSources:
    def test_unarmed_has_two_fists(self):
        p = _make_player()
        sources = p.get_attack_sources()
        assert len(sources) == 2
        assert sources[0].label == "Left"
        assert sources[1].label == "Right"

    def test_single_weapon_left_and_unarmed_right(self):
        from caldanai.lib.rpg.combat.attack_source import UnarmedAttackSource, WeaponAttackSource
        p = _make_player()
        weapon = MagicMock(spec=Weapon)
        weapon.slots = EquipmentSlots.LEFT_HELD
        weapon.damage_type = None
        weapon.skill = "one-handed slashing"
        weapon.attack = "1d6"
        weapon.bonus = 2
        p.part_equipment["hand.left"]["held"] = weapon

        sources = p.get_attack_sources()
        assert len(sources) == 2
        assert isinstance(sources[0], WeaponAttackSource)
        assert sources[0].label == "Left"
        assert isinstance(sources[1], UnarmedAttackSource)
        assert sources[1].label == "Right"

    def test_two_handed_weapon_at_right_only_still_guarded(self):
        """Playtest 2026-04-22 found that when a player reached a
        phantom state with a one-handed weapon at arm.left.held and
        a two-hander at arm.right.held only, both fired as separate
        one-handed attacks — bypassing the "two-handed requires both
        arms" rule. The ``get_attack_sources`` guard now checks BOTH
        hands for MULTI_SLOT so a right-arm-only two-hander is still
        recognized as two-handed (and the stray one-hander at the
        left arm is ignored). Defense-in-depth — the
        ``replace_equipment`` fix makes the phantom state unreachable
        via normal equip flow, but this guard catches any future
        path that could orphan a multi-slot item."""
        from caldanai.lib.rpg.combat.attack_source import WeaponAttackSource
        p = _make_player()
        one_hander = MagicMock(spec=Weapon)
        one_hander.slots = EquipmentSlots.EITHER_HELD
        one_hander.damage_type = None
        one_hander.skill = "one-handed slashing"
        one_hander.attack = "1d6"
        one_hander.bonus = 0

        two_hander = MagicMock(spec=Weapon)
        two_hander.slots = (
            EquipmentSlots.LEFT_HELD
            | EquipmentSlots.RIGHT_HELD
            | EquipmentSlots.MULTI_SLOT
        )
        two_hander.damage_type = None
        two_hander.skill = "two-handed swords"
        two_hander.attack = "2d6"
        two_hander.bonus = 0

        # Phantom shape: one-hander left, two-hander right only
        # (should not occur via equip path after the fix).
        p.part_equipment["hand.left"]["held"] = one_hander
        p.part_equipment["hand.right"]["held"] = two_hander

        sources = p.get_attack_sources()
        # Must recognize the two-hander and emit ONE source, not
        # two separate one-handed attacks.
        assert len(sources) == 1
        assert isinstance(sources[0], WeaponAttackSource)
        assert sources[0].label == "Two-Handed"

    def test_two_handed_yields_single_source(self):
        from caldanai.lib.rpg.combat.attack_source import WeaponAttackSource
        p = _make_player()
        weapon = MagicMock(spec=Weapon)
        weapon.slots = EquipmentSlots.LEFT_HELD | EquipmentSlots.RIGHT_HELD | EquipmentSlots.MULTI_SLOT
        weapon.damage_type = None
        weapon.skill = "two-handed swords"
        weapon.attack = "2d6"
        weapon.bonus = 2
        # Two-handed: same weapon at both arms, matching the runtime
        # shape produced by ``Player.equip`` for MULTI_SLOT items.
        p.part_equipment["hand.left"]["held"] = weapon
        p.part_equipment["hand.right"]["held"] = weapon

        sources = p.get_attack_sources()
        assert len(sources) == 1
        assert isinstance(sources[0], WeaponAttackSource)
        assert sources[0].label == "Two-Handed"


class TestDoAttack:
    def test_returns_attack_sequence(self):
        from caldanai.lib.rpg.combat.attack_result import AttackSequence

        p = _make_player()
        target = MagicMock()
        target.get_dodge.return_value = 10
        target.get_defense.return_value = 0
        target.get_trait_multiplier.return_value = 1.0
        # Make target.resolve_attack call the real Creature resolve_attack by mocking it directly
        from caldanai.lib.rpg.combat.attack_result import AttackResult
        target.resolve_attack.return_value = _make_attack_result(damage=5)

        seq = p.do_attack(target)
        assert isinstance(seq, AttackSequence)
        assert seq.attacker is p
        assert seq.target is target

    def test_unarmed_produces_two_results(self):
        p = _make_player()
        target = MagicMock()
        target.resolve_attack.return_value = _make_attack_result(damage=3)
        target.get_dodge.return_value = 10

        seq = p.do_attack(target)
        assert len(seq.results) == 2
        assert target.resolve_attack.call_count == 2
        assert seq.total_damage() == 6

    def test_two_handed_produces_one_result(self):
        p = _make_player()
        weapon = MagicMock(spec=Weapon)
        weapon.slots = EquipmentSlots.LEFT_HELD | EquipmentSlots.RIGHT_HELD | EquipmentSlots.MULTI_SLOT
        weapon.damage_type = None
        weapon.skill = "two-handed swords"
        weapon.attack = "2d6"
        weapon.bonus = 2
        # Two-handed: same weapon at both arms.
        p.part_equipment["hand.left"]["held"] = weapon
        p.part_equipment["hand.right"]["held"] = weapon

        target = MagicMock()
        target.resolve_attack.return_value = _make_attack_result(damage=8)
        target.get_dodge.return_value = 10

        seq = p.do_attack(target)
        assert len(seq.results) == 1
        assert target.resolve_attack.call_count == 1

    def test_skill_xp_granted_on_hit(self):
        p = _make_player()
        target = MagicMock()
        target.resolve_attack.return_value = _make_attack_result(damage=5, hit=True)
        target.get_dodge.return_value = 10

        p.do_attack(target)
        assert "unarmed bludgeoning" in p.skills
        assert p.skills["unarmed bludgeoning"] > 0

    def test_miss_grants_flat_progression_floor_xp(self):
        """Q.6 — misses grant a flat 2 XP per attempted source so
        low-skill players still progress when they miss a lot.
        ``do_attack`` dispatches two unarmed sources (left + right),
        so two misses = 4 XP."""
        p = _make_player()
        target = MagicMock()
        target.resolve_attack.return_value = _make_attack_result(damage=0, hit=False)
        target.get_dodge.return_value = 10

        p.do_attack(target)
        # 2 XP per missed source × 2 sources = 4 XP total.
        assert p.skills.get("unarmed bludgeoning", 0) == 4

    def test_monster_can_modify_damage(self):
        p = _make_player()
        target = MagicMock()
        # First hand hit for 3, second for 4 — simulating a monster override
        target.resolve_attack.side_effect = [
            _make_attack_result(damage=3, hit=True),
            _make_attack_result(damage=4, hit=True),
        ]
        target.get_dodge.return_value = 10

        seq = p.do_attack(target)
        assert seq.total_damage() == 7

    def test_roll_counts_updated(self):
        p = _make_player()
        target = MagicMock()
        target.resolve_attack.return_value = _make_attack_result(damage=1, hit=True)
        target.get_dodge.return_value = 10

        old_d20 = [c for c in p.rolls["d20"]]
        p.do_attack(target)
        assert p.rolls["d20"] != old_d20


def _make_attack_result(damage=5, hit=True):
    """Build a minimal AttackResult for Player do_attack tests."""
    from caldanai.lib.rpg.combat.attack_result import AttackResult
    from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
    from caldanai.lib.rpg.helpers.roll_data import AttackRoll, CombinedRoll, DamageRoll
    from caldanai.lib.rpg.helpers.dice import Dice

    atk = AttackRoll(skill_bonus=20 if hit else 0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    # Force hit/miss state
    atk.rolls = (20 if hit else 1,)
    atk.result = 20 if hit else 1
    atk.isCritical = False
    atk.isFumble = not hit
    combined = CombinedRoll(atk, dmg, 10)
    # Override isMiss directly since the rolled values may not agree
    combined.isMiss = not hit
    source = NaturalAttackSource(atk="1d4")
    return AttackResult(
        source=source,
        combined=combined,
        damage=damage,
        multiplier=1.0,
        defense=0,
        dodge=10,
    )


# ---------------------------------------------------------------------------
# Body parts: default anatomy, persistence, and stat emergence
# ---------------------------------------------------------------------------

class TestPlayerBodyParts:
    """Players carry a fixed humanoid anatomy. Head and torso are
    critical; arms, legs, and eyes degrade stats via the same emergence
    path monsters use. Persistence stores only current per-part health
    keyed by instance name so schema drift is cheap."""

    _EXPECTED_PART_NAMES = {
        "head", "neck", "torso",
        "arm.left", "arm.right",
        "hand.left", "hand.right",
        "leg.left", "leg.right",
        "foot.left", "foot.right",
        "eye.left", "eye.right",
    }

    def test_default_anatomy_has_nine_parts_at_full_health(self):
        p = _make_player()
        names = {part.name for part in p.body_parts}
        assert names == self._EXPECTED_PART_NAMES
        for part in p.body_parts:
            assert part.health == part.health_max

    def test_head_and_torso_are_critical(self):
        p = _make_player()
        parts_by_name = {part.name: part for part in p.body_parts}
        assert parts_by_name["head"].is_critical is True
        assert parts_by_name["torso"].is_critical is True
        # Non-critical anatomy
        for name in ("arm.left", "leg.right", "eye.left"):
            assert parts_by_name[name].is_critical is False

    def test_default_anatomy_is_deterministic(self):
        """Every player shares identical starting anatomy. Regression
        guard against the old behavior where each part's ``health_max``
        was rolled per-construction (inherited from the monster path),
        giving every player a slightly different constitution."""
        expected = {
            "head": 15, "neck": 8, "torso": 30,
            "arm.left": 10, "arm.right": 10,
            "hand.left": 6, "hand.right": 6,
            "leg.left": 12, "leg.right": 12,
            "foot.left": 8, "foot.right": 8,
            "eye.left": 4, "eye.right": 4,
        }
        # Construct two players and assert anatomy is identical.
        a = _make_player()
        b = _make_player()
        for player in (a, b):
            actual = {part.name: part.health_max for part in player.body_parts}
            assert actual == expected

    def test_body_parts_health_override_restores_injury_state(self):
        """Passing a body_parts_health dict through __init__ sets current
        health per part (clamped), matching the DB rehydration flow."""
        overrides = {"leg.left": 1, "eye.right": 0}
        p = _make_player(body_parts_health=overrides)
        parts_by_name = {part.name: part for part in p.body_parts}
        assert parts_by_name["leg.left"].health == 1
        assert parts_by_name["eye.right"].health == 0
        assert parts_by_name["leg.right"].health == parts_by_name["leg.right"].health_max

    def test_body_parts_health_clamped_to_valid_range(self):
        """Negative / out-of-range overrides are clamped to [0, health_max]."""
        p = _make_player(body_parts_health={"torso": -5})
        torso = next(part for part in p.body_parts if part.name == "torso")
        assert torso.health == 0

    def test_unknown_body_parts_health_keys_are_ignored(self):
        """Old DB entries with renamed/removed parts load cleanly."""
        p = _make_player(body_parts_health={"wing.left": 5, "tentacle": 3})
        names = {part.name for part in p.body_parts}
        assert names == self._EXPECTED_PART_NAMES


class TestPlayerBodyPartPersistence:
    """to_dict / from_dict round-trip preserves per-part injury state."""

    def test_to_dict_includes_body_parts_health(self):
        p = _make_player()
        d = p.to_dict()
        assert "body_parts_health" in d
        assert set(d["body_parts_health"].keys()) == {
            "head", "neck", "torso",
            "arm.left", "arm.right",
            "hand.left", "hand.right",
            "leg.left", "leg.right",
            "foot.left", "foot.right",
            "eye.left", "eye.right",
        }

    def test_to_dict_persists_health_max_per_part(self):
        """Every part must persist both ``health`` and ``health_max``
        so anatomy is stable across sessions (was a bug: only health
        was saved, so ``health_max`` rerolled every login and saved
        health got silently clamped to the new random max)."""
        p = _make_player()
        d = p.to_dict()
        for name, entry in d["body_parts_health"].items():
            assert isinstance(entry, dict), (
                f"{name} persisted as {type(entry).__name__}, "
                f"expected dict with health + health_max"
            )
            assert "health" in entry
            assert "health_max" in entry
            assert entry["health_max"] > 0

    @patch("caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_anatomy_stable_across_round_trip(self, _):
        """Saving + loading a player must preserve each part's
        ``health_max`` exactly. Before the fix, to_dict only saved
        ``health`` and ``health_max`` was rerolled on load; this test
        catches any regression of that behavior."""
        p = _make_player()
        original_maxes = {
            part.name: part.health_max for part in p.body_parts
        }

        payload = p.to_dict()
        restored = Player.from_dict(payload)

        restored_maxes = {
            part.name: part.health_max for part in restored.body_parts
        }
        assert restored_maxes == original_maxes

    @patch("caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_legacy_int_overrides_still_load(self, _):
        """DB documents written before the dict-of-dict migration used
        ``{name: int}`` for body_parts_health. Loading those must not
        crash — current health is clamped to the freshly-rolled max
        (legacy behavior) and the next save will upgrade the shape."""
        d = {
            "_id": ObjectId(),
            "user_id": 1, "guild_id": 2,
            "weight_limit": 100, "joined": None,
            "clarks": 0, "defense": 6, "dodge": 6,
            "health": 20, "health_max": 20, "items": [],
            "rolls": {"d4": [0]*4, "d6": [0]*6, "d8": [0]*8,
                      "d10": [0]*10, "d12": [0]*12, "d20": [0]*20},
            "skills": {},
            "gender": "female", "pronouns": "she,her,hers,her",
            "part_equipment": {},
            "last_active": None, "health_regen": 0,
            # Legacy int-form overrides.
            "body_parts_health": {"leg.left": 2, "head": 5},
        }
        restored = Player.from_dict(d)
        parts = {part.name: part for part in restored.body_parts}
        # Clamped to freshly-rolled max (whatever it came out to),
        # but never negative and never above max.
        assert 0 <= parts["leg.left"].health <= parts["leg.left"].health_max
        assert 0 <= parts["head"].health <= parts["head"].health_max

    @patch("caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_round_trip_preserves_injury_state(self, _):
        """A Player with a damaged leg survives a to_dict/from_dict cycle
        with that leg still damaged."""
        p = _make_player()
        leg = next(part for part in p.body_parts if part.name == "leg.left")
        # Drop leg to ~10% (SEVERE territory)
        damaged_health = max(1, int(leg.health_max * 0.1))
        leg.health = damaged_health

        payload = p.to_dict()
        # to_dict drops _id when pid is None, so the test _make_player
        # which assigns pid keeps _id here.
        restored = Player.from_dict(payload)

        restored_leg = next(part for part in restored.body_parts if part.name == "leg.left")
        assert restored_leg.health == damaged_health

    @patch("caldanai.lib.rpg.creatures.player.Inventory.from_list", return_value=Inventory())
    def test_from_dict_without_body_parts_health_returns_full_health(self, _):
        """Legacy DB entries (no body_parts_health key) rehydrate with
        full per-part health — no crashes, no missing parts."""
        d = {
            "_id": ObjectId(),
            "user_id": 1, "guild_id": 2,
            "weight_limit": 100, "joined": None,
            "clarks": 0, "defense": 6, "dodge": 6,
            "health": 20, "health_max": 20, "items": [],
            "rolls": {"d4": [0]*4, "d6": [0]*6, "d8": [0]*8,
                      "d10": [0]*10, "d12": [0]*12, "d20": [0]*20},
            "skills": {},
            "gender": "female", "pronouns": "she,her,hers,her",
            "part_equipment": {},
            "last_active": None, "health_regen": 0,
        }
        p = Player.from_dict(d)
        assert p is not None
        # Phase D anatomy: 3 spine (torso/neck/head) + 2 eyes +
        # 4 arm pieces (arm + hand × sides) + 4 leg pieces
        # (leg + foot × sides) = 13.
        assert len(p.body_parts) == 13
        for part in p.body_parts:
            assert part.health == part.health_max


class TestPlayerIsInjured:
    """``Player.is_injured()`` returns True when body HP is below max or
    any body part is below its max. Consolidates four previously inline
    predicates (``_is_injured``, ``_needs_healing``, and two ad-hoc
    ``needs_body / needs_part`` checks)."""

    def test_fresh_player_is_not_injured(self):
        p = _make_player()
        assert p.is_injured() is False

    def test_body_hp_below_max_is_injured(self):
        p = _make_player(health=10, health_max=20)
        assert p.is_injured() is True

    def test_any_part_below_max_is_injured(self):
        p = _make_player()
        leg = next(part for part in p.body_parts if part.name == "leg.left")
        leg.health = leg.health_max - 1
        assert p.is_injured() is True

    def test_destroyed_part_at_zero_is_injured(self):
        p = _make_player()
        arm = next(part for part in p.body_parts if part.name == "arm.right")
        arm.health = 0
        assert p.is_injured() is True


class TestPlayerHealFully:
    """``Player.heal_fully()`` restores body HP and every body part to
    max, resets regen bookkeeping, and marks the player dirty. Replaces
    four near-identical restore loops (pray d20==1, pray d20==20,
    unsmite, and any future divine-full-heal caller)."""

    def test_restores_body_hp_to_max(self):
        p = _make_player(health=1, health_max=20)
        p.heal_fully()
        assert p.health == p.get_health_max()

    def test_restores_every_part_to_max(self):
        p = _make_player()
        for part in p.body_parts:
            part.health = 0
        p.heal_fully()
        for part in p.body_parts:
            assert part.health == part.health_max

    def test_sets_is_dirty(self):
        p = _make_player()
        p.is_dirty = False
        p.heal_fully()
        assert p.is_dirty is True

    def test_resets_health_regen(self):
        p = _make_player()
        p.health_regen = 5
        p.heal_fully()
        assert p.health_regen == 0

    def test_heal_fully_is_idempotent_on_healthy_player(self):
        """Calling heal_fully on an already-full player must not produce
        an invalid state (e.g. health above max)."""
        p = _make_player()
        p.heal_fully()
        assert p.health == p.get_health_max()
        for part in p.body_parts:
            assert part.health == part.health_max


class TestPlayerStatEmergence:
    """Player dodge / defense now emerge from body parts the same way
    monster stats do, plus armor bonuses on top."""

    def test_get_dodge_drops_when_legs_injure(self):
        """Player with both legs healthy vs one leg destroyed: dodge
        emergence scales by the mobility ratio."""
        p = _make_player(dodge=6)
        healthy_dodge = p.get_dodge()
        # Destroy one leg → mobility ratio drops to 0.5
        leg = next(part for part in p.body_parts if part.name == "leg.left")
        leg.health = 0
        injured_dodge = p.get_dodge()
        assert injured_dodge < healthy_dodge

    def test_get_defense_drops_when_torso_injures(self):
        """Torso at ~50% HP (MODERATE) should reduce defense via
        emergence."""
        p = _make_player(defense=10)
        healthy_def = p.get_defense()
        torso = next(part for part in p.body_parts if part.name == "torso")
        torso.health = max(1, int(torso.health_max * 0.3))  # SEVERE range
        injured_def = p.get_defense()
        assert injured_def < healthy_def

    def test_critical_part_destruction_kills_player(self):
        """Routing enough damage to a critical part (head) kills the
        player outright via the critical-part short-circuit, even when
        body HP hasn't been touched."""
        p = _make_player(health=20, health_max=20)
        head = next(part for part in p.body_parts if part.name == "head")
        # Route enough damage to destroy the head.
        p.apply_damage(head.health_max + 10, target_part=head)
        assert head.is_destroyed()
        assert p.is_dead()


# ---------------------------------------------------------------------------
# Disabled attack slots — a USELESS arm drops that hand's attack
# ---------------------------------------------------------------------------

class TestDisabledArmDisablesAttackSlot:
    """When an arm reaches InjuryLevels.USELESS, attacks from that
    hand must stop firing entirely (no roll, no damage). Two-handed
    weapons require both arms; losing either stops the attack. The
    rendering surfaces a note explaining why a slot didn't swing."""

    def _cripple(self, player, instance_name: str) -> None:
        """Drive a part directly to 0 HP to simulate USELESS."""
        part = next(p for p in player.body_parts if p.name == instance_name)
        part.health = 0

    def test_useless_right_arm_removes_right_source(self):
        p = _make_player()
        self._cripple(p, "arm.right")
        sources = p.get_attack_sources()
        labels = [s.label for s in sources]
        assert "Right" not in labels
        assert "Left" in labels

    def test_useless_left_arm_removes_left_source(self):
        p = _make_player()
        self._cripple(p, "arm.left")
        labels = [s.label for s in p.get_attack_sources()]
        assert "Left" not in labels
        assert "Right" in labels

    def test_both_arms_useless_produces_no_sources(self):
        p = _make_player()
        self._cripple(p, "arm.left")
        self._cripple(p, "arm.right")
        assert p.get_attack_sources() == []

    def test_two_handed_requires_both_arms(self):
        from caldanai.lib.rpg.combat.attack_source import WeaponAttackSource
        p = _make_player()
        weapon = MagicMock(spec=Weapon)
        weapon.slots = (
            EquipmentSlots.LEFT_HELD | EquipmentSlots.RIGHT_HELD | EquipmentSlots.MULTI_SLOT
        )
        weapon.damage_type = None
        weapon.skill = "two-handed swords"
        weapon.attack = "2d6"
        weapon.bonus = 2
        # Two-handed: same weapon at both arms.
        p.part_equipment["hand.left"]["held"] = weapon
        p.part_equipment["hand.right"]["held"] = weapon

        # Baseline: both arms OK → one two-handed source.
        assert len(p.get_attack_sources()) == 1

        # Cripple either arm → no sources.
        self._cripple(p, "arm.right")
        assert p.get_attack_sources() == []

    def test_disabled_notes_populate_when_arm_is_useless(self):
        p = _make_player()
        self._cripple(p, "arm.right")
        notes = p.get_disabled_attack_notes()
        # A humanized note should reference the right arm being useless.
        assert any("right arm" in n.lower() for n in notes)

    def test_do_attack_attaches_notes_to_sequence(self):
        from caldanai.lib.rpg.combat.attack_result import AttackSequence
        p = _make_player()
        self._cripple(p, "arm.right")

        # Build a minimal target that survives resolve_attack.
        target = MagicMock()
        target.get_dodge.return_value = 10
        target.get_defense.return_value = 0
        target.get_trait_multiplier.return_value = 1.0
        target.body_parts = []
        target.get_targetable_parts.return_value = []

        from caldanai.lib.rpg.combat.attack_result import AttackResult
        def _resolve(_a, _s, atk, dmg, target_dodge=None, target_part=None):
            from caldanai.lib.rpg.helpers.roll_data import CombinedRoll
            combined = CombinedRoll(atk, dmg, target_dodge if target_dodge is not None else 10)
            return AttackResult(source=_s, combined=combined, damage=0,
                                multiplier=1.0, defense=0, dodge=10)
        target.resolve_attack.side_effect = _resolve

        seq = p.do_attack(target)
        assert any("right arm" in n.lower() for n in seq.notes)

    def test_attack_sequence_renders_notes_inside_diff_block(self):
        """Notes should surface in the rendered markdown so the player
        can see why a slot didn't swing."""
        from caldanai.lib.rpg.combat.attack_result import AttackSequence, AttackResult
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        from caldanai.lib.rpg.helpers.roll_data import (
            AttackRoll, DamageRoll, CombinedRoll,
        )
        from caldanai.lib.rpg.helpers.dice import Dice

        # Build a sequence with one result + one note.
        atk = AttackRoll(skill_bonus=0)
        atk.rolls = (10,)
        atk.result = 10
        atk.isCritical = False
        atk.isFumble = False
        dmg = DamageRoll(dice=Dice.d4(), skill_bonus=0, weapon_bonus=0)
        dmg.rolls = (3,)
        dmg.result = 3
        combined = CombinedRoll(atk, dmg, 8)
        attacker = MagicMock()
        attacker.name = "caels"
        attacker.member = None
        target = MagicMock()
        target.name = "dummy"
        result = AttackResult(
            source=NaturalAttackSource(atk="1d4", label="Left"),
            combined=combined,
            damage=3, multiplier=1.0, defense=0, dodge=8,
        )
        seq = AttackSequence(
            attacker=attacker, target=target, results=[result],
            notes=["The right arm hangs limp and useless."],
        )
        md = seq.to_markdown()
        assert "right arm hangs limp" in md
