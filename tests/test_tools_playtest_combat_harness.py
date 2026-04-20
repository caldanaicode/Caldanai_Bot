"""Tests for ``tools.playtest_combat_harness`` — real-pipeline
combat simulator.

Covers the headless-construction plumbing (Player factory, weapon
equipping, skill seeding) and the trial outcome/summary formatting.
Doesn't run full combat in tests — that's the tool's job in
exploratory use; a regression there would show up in the main
test suite via the pipeline's own tests."""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from tools.playtest_combat_harness import (
    TrialOutcome,
    _build_player,
    _summarize,
    _xp_for_level,
)


class TestXpForLevel:
    def test_cap_returns_large_value(self):
        assert _xp_for_level(20) >= 1_000_000
        assert _xp_for_level(50) >= 1_000_000

    def test_low_level_returns_bounded_value(self):
        assert _xp_for_level(0) >= 100  # minimum floor
        assert _xp_for_level(10) > _xp_for_level(0)


class TestBuildPlayer:
    def test_unarmed_has_no_weapons_equipped(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon=None, offhand=None,
            quality=Qualities.ORDINARY, skill_level=10,
        )
        assert p.equip_slots.get(EquipmentSlots.LEFT_HELD.name) is None
        assert p.equip_slots.get(EquipmentSlots.RIGHT_HELD.name) is None

    def test_single_weapon_equipped_to_left(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="shortsword", offhand=None,
            quality=Qualities.ORDINARY, skill_level=10,
        )
        assert p.equip_slots[EquipmentSlots.LEFT_HELD.name] is not None
        assert p.equip_slots[EquipmentSlots.LEFT_HELD.name].name == "shortsword"
        assert p.equip_slots.get(EquipmentSlots.RIGHT_HELD.name) is None

    def test_dual_wield_fills_both_slots(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="mace", offhand="shortsword",
            quality=Qualities.ORDINARY, skill_level=10,
        )
        assert p.equip_slots[EquipmentSlots.LEFT_HELD.name].name == "mace"
        assert p.equip_slots[EquipmentSlots.RIGHT_HELD.name].name == "shortsword"

    def test_two_handed_weapon_fills_both_slots_with_same_weapon(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="bow", offhand=None,
            quality=Qualities.ORDINARY, skill_level=10,
        )
        left = p.equip_slots[EquipmentSlots.LEFT_HELD.name]
        right = p.equip_slots[EquipmentSlots.RIGHT_HELD.name]
        assert left is not None
        assert left is right  # same weapon instance, two-handed
        assert left.name == "bow"

    def test_two_handed_offhand_rejected(self):
        with pytest.raises(SystemExit):
            _build_player(
                name="Test", hp=20, defense=3, dodge=15,
                weapon="shortsword", offhand="bow",
                quality=Qualities.ORDINARY, skill_level=10,
            )

    def test_skill_level_seeded_into_skills_dict(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="shortsword", offhand=None,
            quality=Qualities.ORDINARY, skill_level=10,
        )
        assert p.skills  # non-empty
        # get_skill_level should return a positive integer for the
        # shortsword's skill name.
        from caldanai.lib.rpg.inventory.equipment.weapons.shortsword import WeaponPlugin
        w = WeaponPlugin(iid=None, quality=Qualities.ORDINARY, bonus=None)
        assert p.get_skill_level(w.skill) > 0

    def test_zero_skill_seeds_nothing(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="shortsword", offhand=None,
            quality=Qualities.ORDINARY, skill_level=0,
        )
        assert p.skills == {}


class TestSummarize:
    def test_all_wins(self, capsys):
        outcomes = [
            TrialOutcome(
                winner="player", rounds=3, damage_dealt=20,
                damage_received=5, critical_part_kill=False,
            ),
            TrialOutcome(
                winner="player", rounds=5, damage_dealt=25,
                damage_received=10, critical_part_kill=True,
                destroyed_parts=["head"],
            ),
        ]
        _summarize(outcomes, "test header")
        out = capsys.readouterr().out
        assert "test header" in out
        assert "player_wins=2" in out
        assert "monster_wins=0" in out
        assert "player_win_rate=100%" in out
        assert "critical-part kills: 1/2" in out
        assert "head x1" in out

    def test_mixed_outcomes(self, capsys):
        outcomes = [
            TrialOutcome(winner="player", rounds=4, damage_dealt=30,
                         damage_received=10, critical_part_kill=False),
            TrialOutcome(winner="monster", rounds=6, damage_dealt=15,
                         damage_received=20, critical_part_kill=False),
            TrialOutcome(winner="stalemate", rounds=50, damage_dealt=40,
                         damage_received=15, critical_part_kill=False),
        ]
        _summarize(outcomes, "mixed")
        out = capsys.readouterr().out
        assert "player_wins=1" in out
        assert "monster_wins=1" in out
        assert "stalemates=1" in out

    def test_zero_outcomes_survives_division(self, capsys):
        # All stalemates — avg_damage_dealt / avg_damage_received
        # branches should be skipped cleanly.
        outcomes = [
            TrialOutcome(winner="stalemate", rounds=50, damage_dealt=0,
                         damage_received=0, critical_part_kill=False),
        ]
        _summarize(outcomes, "stale-only")
        out = capsys.readouterr().out
        assert "stalemates=1" in out
