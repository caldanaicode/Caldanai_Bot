"""Tests for Caldanai.lib.rpg.combat.attack_result."""

from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, CombinedRoll, DamageRoll
from caldanai.lib.rpg.helpers.dice import Dice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_combined(forced_attack=None, forced_damage=None, dodge=10):
    """Build a real CombinedRoll for testing. forced_* override dice results."""
    atk = AttackRoll(skill_bonus=0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    if forced_attack is not None:
        atk.rolls = (forced_attack,)
        atk.result = forced_attack
        atk.isCritical = forced_attack == 20
        atk.isFumble = forced_attack == 1
    if forced_damage is not None:
        dmg.rolls = (forced_damage,)
        dmg.result = forced_damage
    return CombinedRoll(atk, dmg, dodge)


def _make_source(label="Left", dmg_type=DamageTypes.SLASHING):
    src = MagicMock()
    src.label = label
    src.damage_type = dmg_type
    return src


def _make_result(damage=5, is_miss=False, is_critical=False, multiplier=1.0,
                 defense=2, dodge=10, label="Left", dmg_type=DamageTypes.SLASHING):
    # Force attack roll to produce the desired hit state
    forced_attack = 20 if is_critical else (1 if is_miss else 15)
    combined = _make_combined(forced_attack=forced_attack, forced_damage=6, dodge=dodge)
    source = _make_source(label=label, dmg_type=dmg_type)
    # Q.7: ``absorbed`` is the rolled 1d{defense} outcome stored
    # alongside ``defense``. Synthetic results infer absorbed from
    # sub_damage - final_damage so the renderer's Def column reads
    # correctly across mocked fixtures.
    sub = 0 if is_miss else max(1, int(6 * multiplier)) if multiplier > 0 else 0
    absorbed = max(0, sub - damage) if defense > 0 and not is_miss else 0
    return AttackResult(
        source=source,
        combined=combined,
        damage=damage,
        multiplier=multiplier,
        defense=defense,
        absorbed=absorbed,
        dodge=dodge,
        dmg_type=dmg_type,
    )


# ---------------------------------------------------------------------------
# AttackResult basics
# ---------------------------------------------------------------------------

class TestAttackResultBasics:
    def test_total_damage_returns_damage(self):
        r = _make_result(damage=7)
        assert r.total_damage() == 7

    def test_hit_true_when_not_miss(self):
        r = _make_result(is_miss=False)
        assert r.hit() is True

    def test_hit_false_when_miss(self):
        r = _make_result(is_miss=True)
        assert r.hit() is False

    def test_sub_damage_applies_multiplier(self):
        r = _make_result(multiplier=2.0)
        # combined.result is 6 (from forced_damage), sub_damage = 12
        assert r.sub_damage == 12

    def test_sub_damage_landed_hit_floors_at_one_on_partial_resistance(self):
        """Q.6.3 fix: a landed hit against a partial resistance
        (e.g. 0.75) with a low damage roll (e.g. 1) previously
        int-truncated to 0 and displayed ``* 0.75 = 0``. The hit
        connected, so the reported sub-damage and the applied
        damage both floor at 1."""
        combined = _make_combined(forced_attack=15, forced_damage=1, dodge=10)
        r = AttackResult(
            source=_make_source(),
            combined=combined,
            damage=1,
            multiplier=0.75,
            defense=0,
            dodge=10,
            dmg_type=DamageTypes.SLASHING,
        )
        assert r.sub_damage == 1

    def test_sub_damage_zero_on_full_immunity(self):
        """Full immunity (``multiplier == 0``) reads as 0 sub-damage
        even on a landed hit — the floor only applies when the
        target is merely resistant, not immune."""
        combined = _make_combined(forced_attack=15, forced_damage=6, dodge=10)
        r = AttackResult(
            source=_make_source(),
            combined=combined,
            damage=0,
            multiplier=0.0,
            defense=0,
            dodge=10,
            dmg_type=DamageTypes.SLASHING,
        )
        assert r.sub_damage == 0

    def test_sub_damage_miss_reads_zero(self):
        """Miss reads as 0 regardless of multiplier."""
        r = _make_result(is_miss=True, multiplier=1.0)
        assert r.sub_damage == 0


# ---------------------------------------------------------------------------
# AttackResult.to_markdown
# ---------------------------------------------------------------------------

class TestAttackResultToDisplayParts:
    def test_returns_dict_with_expected_keys(self):
        r = _make_result()
        parts = r.to_display_parts()
        expected = {
            "label", "roll_str", "hit_str", "is_miss", "is_critical", "is_fumble",
            "damage_breakdown", "damage_type_str", "damage_type_emoji",
            "sub_damage", "multiplier", "final_damage", "defense", "dodge", "extra_text",
        }
        assert expected.issubset(set(parts.keys()))

    def test_damage_type_emoji_present(self):
        r = _make_result(dmg_type=DamageTypes.FIRE)
        parts = r.to_display_parts()
        assert parts["damage_type_emoji"] == "🔥"

    def test_combined_damage_type_emoji(self):
        r = _make_result(dmg_type=DamageTypes.SLASHING | DamageTypes.FIRE)
        parts = r.to_display_parts()
        assert "🔪" in parts["damage_type_emoji"]
        assert "🔥" in parts["damage_type_emoji"]


class TestAttackResultToMarkdown:
    def test_label_included_as_header(self):
        r = _make_result(label="Left")
        md = r.to_markdown(label="Left")
        assert "**Left:**" in md

    def test_no_header_when_label_none(self):
        r = _make_result()
        md = r.to_markdown(label=None)
        assert "**" not in md  # no label header
        assert "```ansi" in md

    def test_hit_shows_total_line(self):
        r = _make_result(damage=4, is_miss=False, defense=2)
        md = r.to_markdown(label="Right")
        assert "Total" in md
        assert "vs Defense (2) = 4" in md

    def test_miss_omits_total_line(self):
        r = _make_result(damage=0, is_miss=True)
        md = r.to_markdown(label="Left")
        assert "Total" not in md

    def test_miss_shows_damage_block_with_zero(self):
        r = _make_result(damage=0, is_miss=True)
        md = r.to_markdown(label="Left")
        assert "Damage" in md
        assert "* 0" in md

    def test_damage_type_appears_in_output(self):
        r = _make_result(dmg_type=DamageTypes.FIRE)
        md = r.to_markdown(label="Breath")
        assert "Fire" in md or "FIRE" in md or "fire" in md

    def test_multiplier_shown_when_not_one(self):
        r = _make_result(multiplier=1.5)
        md = r.to_markdown(label="Left")
        assert "1.5" in md

    def test_multiplier_omitted_when_one(self):
        r = _make_result(multiplier=1.0)
        md = r.to_markdown(label="Left")
        # The literal "* 1" shouldn't appear as a multiplier
        assert "* 1" not in md.replace("* 10", "").replace("* 11", "").replace("* 12", "")

    def test_extra_text_appended(self):
        r = _make_result(damage=5)
        r.extra_text = "__LORD OF PRIMES!__"
        md = r.to_markdown(label="Left")
        assert "LORD OF PRIMES" in md


# ---------------------------------------------------------------------------
# AttackSequence
# ---------------------------------------------------------------------------

class TestAttackSequence:
    def test_empty_sequence_renders_empty_string(self):
        attacker = MagicMock()
        target = MagicMock()
        seq = AttackSequence(attacker=attacker, target=target, results=[])
        assert seq.to_markdown() == ""

    def test_total_damage_sums_results(self):
        attacker = MagicMock()
        target = MagicMock()
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[_make_result(damage=3), _make_result(damage=5)],
        )
        assert seq.total_damage() == 8

    def test_any_hit_true_when_one_hits(self):
        attacker = MagicMock()
        target = MagicMock()
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[_make_result(damage=0, is_miss=True), _make_result(damage=3)],
        )
        assert seq.any_hit() is True

    def test_any_hit_false_when_all_miss(self):
        attacker = MagicMock()
        target = MagicMock()
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[_make_result(damage=0, is_miss=True), _make_result(damage=0, is_miss=True)],
        )
        assert seq.any_hit() is False

    def test_monster_header_format(self):
        attacker = MagicMock()
        attacker.name = "dragon"
        # Deliberately not a Player instance
        attacker.member = None
        target = MagicMock()
        target.name = "Caels"
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[_make_result()],
        )
        md = seq.to_markdown()
        assert "Dragon attacks Caels" in md

    def test_player_header_uses_mention(self):
        from caldanai.lib.rpg.creatures.player import Player
        attacker = MagicMock(spec=Player)
        attacker.member = MagicMock()
        attacker.member.id = 12345
        attacker.name = "Caels"
        target = MagicMock()
        target.name = "dragon"
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[_make_result()],
        )
        md = seq.to_markdown()
        assert "<@!12345>" in md

    def test_multi_result_rendered_as_compact_table(self):
        attacker = MagicMock()
        attacker.name = "bandit"
        attacker.member = None
        target = MagicMock()
        target.name = "Caels"
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[
                _make_result(label="Left"),
                _make_result(label="Right"),
            ],
        )
        md = seq.to_markdown()
        # Compact table uses ```ansi fence and a single block
        assert "```ansi" in md
        # Both labels appear inside the table rows
        assert "Left" in md
        assert "Right" in md
        # Table has a Dodge column (per-row) and a total footer
        assert "Dodge" in md
        assert "Total:" in md

    def test_multi_result_total_damage_in_footer(self):
        """Q.6.2: defense is applied per-hit. When raw (sub_damage)
        diverges from damage, footer shows 'raw - armor absorbed →
        damage'; when they match, footer shows 'Total: N damage'."""
        attacker = MagicMock()
        attacker.name = "bandit"
        attacker.member = None
        target = MagicMock()
        target.name = "Caels"
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[
                _make_result(label="Left", damage=4),
                _make_result(label="Right", damage=3),
            ],
        )
        md = seq.to_markdown()
        # damage=4,3 totals 7; sub_damage is 6 each (forced_damage=6 * 1.0)
        # so raw_total=12. Divergence triggers the armor-absorbed form.
        assert "→ 7 damage" in md

    def test_multi_result_includes_damage_emoji(self):
        attacker = MagicMock()
        attacker.name = "bandit"
        attacker.member = None
        target = MagicMock()
        target.name = "Caels"
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[
                _make_result(label="Left", dmg_type=DamageTypes.FIRE),
                _make_result(label="Right", dmg_type=DamageTypes.WATER),
            ],
        )
        md = seq.to_markdown()
        assert "🔥" in md
        assert "💧" in md

    def test_multi_target_emits_per_victim_footer_lines(self):
        """Q.6.3-followup: a multi-target sequence (dragon breath,
        hydra AOE) renders a separate footer line per victim so
        readers can see what each victim actually took — not a
        single aggregate ``Total: N damage`` that misleads as
        "every victim took N."

        Dragon breath AOE: Caels takes 12, Serena takes 16. The
        footer should show both lines rather than one "Total: 28"."""
        attacker = MagicMock()
        attacker.name = "dragon"
        attacker.member = None
        caels = MagicMock(); caels.name = "Caels"
        serena = MagicMock(); serena.name = "Serena"
        # Manually build results with explicit ``victim`` populated
        # (the dragon-breath path sets this).
        r_caels = _make_result(label="Caels", damage=12)
        r_caels.victim = caels
        r_serena = _make_result(label="Serena", damage=16)
        r_serena.victim = serena
        seq = AttackSequence(
            attacker=attacker,
            target=caels,
            results=[r_caels, r_serena],
            multi_target=True,
        )
        md = seq.to_markdown()
        # Per-victim lines, not a single aggregate.
        assert "Caels:" in md
        assert "Serena:" in md
        assert "12" in md
        assert "16" in md

    def test_multi_target_footer_falls_back_to_source_label(self):
        """When ``result.victim`` isn't populated (legacy / bespoke
        AOE paths), the footer groups by ``source.label`` instead.
        Dragon breath historically labels each result with the
        victim's display name, so this fallback preserves the
        per-victim breakdown without requiring the caller to set
        ``victim`` explicitly."""
        attacker = MagicMock()
        attacker.name = "dragon"
        attacker.member = None
        target = MagicMock()
        target.name = "Party"
        # victim attribute left as default None
        r_alice = _make_result(label="Alice", damage=7)
        r_bob = _make_result(label="Bob", damage=9)
        seq = AttackSequence(
            attacker=attacker,
            target=target,
            results=[r_alice, r_bob],
            multi_target=True,
        )
        md = seq.to_markdown()
        assert "Alice:" in md
        assert "Bob:" in md

    def test_extra_text_appears_on_own_line(self):
        attacker = MagicMock()
        attacker.name = "math_teacher"
        attacker.member = None
        target = MagicMock()
        target.name = "Caels"
        r1 = _make_result(label="Left", damage=5)
        r1.extra_text = "LORD OF PRIMES! / 2 = 3"
        r2 = _make_result(label="Right", damage=4)
        seq = AttackSequence(attacker=attacker, target=target, results=[r1, r2])
        md = seq.to_markdown()
        assert "LORD OF PRIMES" in md
        # Extra text renders as an indented continuation line under
        # the row it belongs to — the dot-prefix outcome on the parent
        # row already carries the signal, so the continuation just
        # gets the column-header's 3-space leader and no marker.
        assert "\n   " in md
        # And the extra-text content lives on its own line, not
        # smushed onto the row.
        assert "Right" not in md.split("LORD OF PRIMES")[0].rsplit("\n", 1)[-1]
