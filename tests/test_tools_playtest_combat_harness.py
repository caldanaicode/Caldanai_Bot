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
    _embed_field_int,
    _summarize,
    _validate_embed_stats,
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
        assert p.part_equipment["hand.left"]["held"] is None
        assert p.part_equipment["hand.right"]["held"] is None

    def test_single_weapon_equipped_to_left(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="shortsword", offhand=None,
            quality=Qualities.ORDINARY, skill_level=10,
        )
        assert p.part_equipment["hand.left"]["held"] is not None
        assert p.part_equipment["hand.left"]["held"].name == "shortsword"
        assert p.part_equipment["hand.right"]["held"] is None

    def test_dual_wield_fills_both_slots(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="mace", offhand="shortsword",
            quality=Qualities.ORDINARY, skill_level=10,
        )
        assert p.part_equipment["hand.left"]["held"].name == "mace"
        assert p.part_equipment["hand.right"]["held"].name == "shortsword"

    def test_two_handed_weapon_fills_both_slots_with_same_weapon(self):
        p = _build_player(
            name="Test", hp=20, defense=3, dodge=15,
            weapon="bow", offhand=None,
            quality=Qualities.ORDINARY, skill_level=10,
        )
        left = p.part_equipment["hand.left"]["held"]
        right = p.part_equipment["hand.right"]["held"]
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


class TestEmbedFieldInt:
    """``_embed_field_int`` parses the leading integer out of an
    embed field's value, tolerating commas and trailing markers."""

    def test_returns_int_for_plain_number(self):
        embed = MagicMock()
        embed.fields = [MagicMock(name="Defense", value="14")]
        embed.fields[0].name = "Defense"
        assert _embed_field_int(embed, "Defense") == 14

    def test_returns_int_with_trailing_marker(self):
        """Bandage marker (U+1FA79) appended to an injured stat —
        the integer should still parse cleanly off the front."""
        embed = MagicMock()
        f = MagicMock()
        f.name = "Defense"
        f.value = "14 \U0001fa79"
        embed.fields = [f]
        assert _embed_field_int(embed, "Defense") == 14

    def test_strips_thousands_separator(self):
        embed = MagicMock()
        f = MagicMock()
        f.name = "Health"
        f.value = "1,234"
        embed.fields = [f]
        assert _embed_field_int(embed, "Health") == 1234

    def test_returns_none_for_missing_field(self):
        embed = MagicMock()
        embed.fields = []
        assert _embed_field_int(embed, "Defense") is None

    def test_returns_none_for_non_numeric_value(self):
        embed = MagicMock()
        f = MagicMock()
        f.name = "Defense"
        f.value = "bandit"
        embed.fields = [f]
        assert _embed_field_int(embed, "Defense") is None


class TestValidateEmbedStats:
    """Smoke-check the property validator across the live bestiary.

    Mirrors what the operator runs via the CLI flag — a small
    sample count keeps the test cheap, and the assertion is binary
    ("no drift across the registry"). When this fails the harness
    prints per-monster drift events to stdout for debugging."""

    def test_full_bestiary_no_drift(self, capsys):
        with (
            patch("caldanai.dispatcher.Dispatcher"),
            patch("caldanai.lib.rpg.Dispatcher"),
            patch("caldanai.lib.rpg.creatures.DB", create=True),
        ):
            exit_code = _validate_embed_stats(stems=[], samples=5)
        out = capsys.readouterr().out
        assert exit_code == 0, (
            f"unexpected drift; output:\n{out}"
        )
        assert "ALL EMBED STATS MATCH RUNTIME" in out

    def test_scoped_stems_validates_only_those(self, capsys):
        """Passing explicit stems narrows the check — the report
        should only mention those monsters."""
        with (
            patch("caldanai.dispatcher.Dispatcher"),
            patch("caldanai.lib.rpg.Dispatcher"),
            patch("caldanai.lib.rpg.creatures.DB", create=True),
        ):
            exit_code = _validate_embed_stats(
                stems=["bearowl", "goblin"], samples=3,
            )
        out = capsys.readouterr().out
        assert exit_code == 0
        assert "bearowl" in out
        assert "goblin" in out
        # An unrelated monster should NOT appear in the scoped report.
        assert "dragon" not in out

    def test_unknown_stem_skipped_cleanly(self, capsys):
        """An unknown stem prints a skip line and doesn't crash —
        keeps the validator usable as a quick check on a typo."""
        with (
            patch("caldanai.dispatcher.Dispatcher"),
            patch("caldanai.lib.rpg.Dispatcher"),
            patch("caldanai.lib.rpg.creatures.DB", create=True),
        ):
            exit_code = _validate_embed_stats(
                stems=["nonexistent_monster"], samples=2,
            )
        out = capsys.readouterr().out
        # Skipped monsters don't count as drift.
        assert exit_code == 0
        assert "nonexistent_monster" in out
        assert "unknown monster" in out
