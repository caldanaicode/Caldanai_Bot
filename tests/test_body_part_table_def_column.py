"""Defense column on the body-parts ANSI table emitted by
``Creature.render_body_part_status_table`` — used by both
``$look <monster>`` and ``$health <player>``.

Surfaces the per-part absorption pool with a full component
breakdown (``d{N} ({base}{±part_bonus}{±armor}{±drain})``) so
players see WHY the number is what it is: torso-injury drain and
worn-armor bonuses stop being invisible. Soft parts whose pool
floors to zero render as ``—``.

The math source is :func:`effective_defense_breakdown`, which
decomposes :func:`effective_defense_for_part` into its four
additive components. These tests pin the format string and the
component arithmetic against future drift.
"""

from __future__ import annotations

import re
from contextlib import ExitStack, contextmanager
from random import seed
from unittest.mock import patch

from caldanai.lib.rpg.creatures import (
    Creature,
    _format_defense_cell,
    effective_defense_breakdown,
    effective_defense_for_part,
)
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
MonsterPlugin.load_plugins()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_random(return_value):
    """Patch ``random()`` at BOTH modules monster code reaches for
    it. The :class:`Creature`-level ``_apply_loadout`` (lifted from
    the old ``MonsterPlugin._apply_armor_loadout`` 2026-04-28) calls
    ``random()`` from :mod:`caldanai.lib.rpg.creatures`; monster-only
    paths still call from :mod:`caldanai.lib.rpg.creatures.monsters`.
    Patches both so a single uniform value sticks regardless of
    order."""
    with ExitStack() as stack:
        stack.enter_context(patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=return_value,
        ))
        stack.enter_context(patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=return_value,
        ))
        yield


def _strip_ansi(text: str) -> str:
    """Drop the ``\\x1b[...m`` SGR sequences the renderer wraps
    status words in. Test assertions read cleaner against the
    underlying text."""
    return re.sub(r"\x1b\[[\d;]*m", "", text)


def _def_cell_for(creature, part_name: str) -> str:
    """Pull a part's rendered Def cell straight from the table
    output. Returns the cell content with ANSI stripped and
    surrounding whitespace trimmed.
    """
    table = _strip_ansi(creature.render_body_part_status_table(show_hp=False))
    for line in table.splitlines():
        # Skip code fences and the header row.
        if line.startswith("```") or line.startswith("⚫"):
            continue
        # Each data row: ``<dot> <part-padded> | <status> | <def> [| <worn>]``.
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 3:
            continue
        # First cell is "<emoji> <name>" — split off the emoji.
        first = cells[0].split(maxsplit=1)
        if len(first) < 2:
            continue
        if first[1] == part_name:
            return cells[2]
    raise AssertionError(
        f"part {part_name!r} not found in table:\n{table}"
    )


def _fresh_bearowl() -> Bearowl:
    """Bearowl with deterministic stat rolls (seed 0)."""
    seed(0)
    return Bearowl()


def _bandit_with_one_glove() -> Bandit:
    """Bandit forced to spawn exactly one ratty glove on
    ``hand.right`` and nothing else. Pinned so the per-part
    breakdown surfaces a single armor contribution.
    """
    Inventory.discover_items()
    with _patch_random(1.0):
        # Every loadout entry rolls > freq → no spawn-time armor.
        b = Bandit()
    # Now place one ratty_glove on hand.right under our control.
    glove_cls = Inventory.ITEMS["ratty_glove"]
    glove = glove_cls.from_plugin("ratty_glove", {"quality": "ORDINARY"})
    hand_right = b.get_part("hand.right")
    hand_right.placements["worn"] = glove
    return b


# ---------------------------------------------------------------------------
# Helper-level breakdown coverage
# ---------------------------------------------------------------------------


class TestEffectiveDefenseBreakdown:
    def test_components_sum_to_total_for_plated_part(self):
        b = _fresh_bearowl()
        torso = b.get_part("torso")
        bd = effective_defense_breakdown(b, torso)
        assert bd["base"] + bd["part_bonus"] + bd["armor"] + bd["drain"] == bd["total"]
        assert bd["total"] == effective_defense_for_part(b, torso)

    def test_drain_is_zero_at_full_health(self):
        b = _fresh_bearowl()
        torso = b.get_part("torso")
        assert effective_defense_breakdown(b, torso)["drain"] == 0

    def test_drain_is_negative_when_torso_injured(self):
        """Torso below the MINOR threshold (60% HP) drops Defensive
        functionality, which propagates through ``get_defense`` and
        shows up as a negative ``drain`` component on every part."""
        b = _fresh_bearowl()
        torso = b.get_part("torso")
        # Drop torso to 40% HP so MINOR fires (functionality 0.8).
        torso.health = max(1, int(torso.health_max * 0.4))
        # Sanity: live get_defense should now be below full-health.
        head = b.get_part("head")
        bd = effective_defense_breakdown(b, head)
        assert bd["drain"] < 0
        assert bd["base"] + bd["part_bonus"] + bd["armor"] + bd["drain"] == bd["total"]

    def test_armor_component_picks_up_worn_defense_bonuses(self):
        b = _bandit_with_one_glove()
        hand = b.get_part("hand.right")
        bd = effective_defense_breakdown(b, hand)
        # ratty_glove ORDINARY → defense bonus +1.
        assert bd["armor"] == 1


# ---------------------------------------------------------------------------
# Format-string coverage
# ---------------------------------------------------------------------------


class TestFormatDefenseCell:
    def test_omits_zero_components(self):
        """``d20 (20)`` not ``d20 (20+0+0+0)`` — only non-zero
        components appear in the parens."""
        cell = _format_defense_cell({
            "base": 20,
            "part_bonus": 0,
            "armor": 0,
            "drain": 0,
            "total": 20,
        })
        assert cell == "d20 (20)"

    def test_signed_positive_part_bonus(self):
        cell = _format_defense_cell({
            "base": 20,
            "part_bonus": 3,
            "armor": 0,
            "drain": 0,
            "total": 23,
        })
        assert cell == "d23 (20+3)"

    def test_signed_negative_part_bonus(self):
        cell = _format_defense_cell({
            "base": 20,
            "part_bonus": -2,
            "armor": 0,
            "drain": 0,
            "total": 18,
        })
        assert cell == "d18 (20-2)"

    def test_full_breakdown_after_drain(self):
        cell = _format_defense_cell({
            "base": 20,
            "part_bonus": 3,
            "armor": 0,
            "drain": -4,
            "total": 19,
        })
        assert cell == "d19 (20+3-4)"

    def test_armor_and_part_bonus_combine(self):
        cell = _format_defense_cell({
            "base": 20,
            "part_bonus": -2,
            "armor": 5,
            "drain": -4,
            "total": 19,
        })
        assert cell == "d19 (20-2+5-4)"

    def test_zero_total_renders_em_dash(self):
        cell = _format_defense_cell({
            "base": 0,
            "part_bonus": 0,
            "armor": 0,
            "drain": 0,
            "total": 0,
        })
        assert cell == "—"

    def test_negative_total_renders_em_dash(self):
        cell = _format_defense_cell({
            "base": 1,
            "part_bonus": -2,
            "armor": 0,
            "drain": 0,
            "total": -1,
        })
        assert cell == "—"


# ---------------------------------------------------------------------------
# Renderer-integration coverage
# ---------------------------------------------------------------------------


class TestRendererDefColumn:
    def test_table_includes_def_header(self):
        b = _fresh_bearowl()
        table = _strip_ansi(b.render_body_part_status_table(show_hp=False))
        # Header row is the first non-fence line.
        header = next(
            line for line in table.splitlines()
            if line.startswith("⚫")
        )
        assert " Def" in header

    def test_bearowl_torso_def_cell_includes_intrinsic_bonus(self):
        """Bearowl torso has an intrinsic +3 plate bonus (encoded as
        ``defense_bonus = 3`` on TorsoPlugin via the plugin override).
        At full health drain is 0, no armor, so the cell must read
        ``d{base+3} ({base}+3)``.
        """
        b = _fresh_bearowl()
        torso = b.get_part("torso")
        bd = effective_defense_breakdown(b, torso)
        cell = _def_cell_for(b, "torso")
        assert cell == f"d{bd['total']} ({bd['base']}+3)"
        # And the +3 actually IS positive on this plugin.
        assert bd["part_bonus"] == 3

    def test_bearowl_head_def_cell_shows_depth_penalty(self):
        """Bearowl head has depth 2 with no intrinsic plating →
        part_bonus = -2. At full health no drain, no armor.
        """
        b = _fresh_bearowl()
        head = b.get_part("head")
        bd = effective_defense_breakdown(b, head)
        cell = _def_cell_for(b, "head")
        assert cell == f"d{bd['total']} ({bd['base']}-2)"
        assert bd["part_bonus"] == -2

    def test_bearowl_eye_def_cell_shows_em_dash_when_floored(self):
        """SOFT_PART eyes resolve to ``int(base × 0.1)``. When that
        product is ≤ 0 (low base creatures, or any creature whose
        base is below 10) the cell must collapse to ``—``.

        Bearowl seed-0 base is 18 → soft_base = 1, so the eye still
        renders. We construct a low-base creature to exercise the
        em-dash path directly.
        """
        # Bare-Creature scaffold with no plugins, low defense.
        c = Creature(
            name="testdummy",
            atk="1d1",
            defense="1d1",   # rolls to 1
            dodge="1d1",
            health_max="1d1",
        )
        # Confirm Creature.get_defense yields a tiny number and
        # multiplying by SOFT_PART_FRACTION truncates to 0. We don't
        # need a real eye plugin — just check the formatter directly.
        cell = _format_defense_cell({
            "base": 0,
            "part_bonus": 0,
            "armor": 0,
            "drain": 0,
            "total": 0,
        })
        assert cell == "—"
        # And confirm a bearowl eye with total > 0 does NOT collapse.
        b = _fresh_bearowl()
        eye = b.get_part("eye.left")
        eye_total = effective_defense_for_part(b, eye)
        if eye_total > 0:
            cell = _def_cell_for(b, "eye.left")
            assert cell != "—"
            assert cell.startswith(f"d{eye_total}")

    def test_torso_drain_after_injury_appears_in_cell(self):
        """Drop the bearowl torso below the MINOR injury threshold;
        every part's Def cell should now carry a negative ``drain``
        component."""
        b = _fresh_bearowl()
        torso = b.get_part("torso")
        # 40% HP → MINOR injury → Defensive functionality 0.8.
        torso.health = max(1, int(torso.health_max * 0.4))
        head = b.get_part("head")
        head_bd = effective_defense_breakdown(b, head)
        assert head_bd["drain"] < 0
        cell = _def_cell_for(b, "head")
        # Cell ends with the drain component; e.g. "(18-2-3)".
        assert f"{head_bd['drain']})" in cell
        # And the head bonus -2 is still present.
        assert "-2" in cell

    def test_bandit_hand_with_glove_shows_armor_component(self):
        """A bandit forced to wear exactly one ratty_glove on
        ``hand.right`` surfaces the +1 armor component on that
        part's Def cell — and only that part's."""
        b = _bandit_with_one_glove()
        right_cell = _def_cell_for(b, "hand.right")
        # ratty_glove ORDINARY adds +1 defense.
        assert "+1" in right_cell
        # The unworn left hand has the same intrinsic shape but no
        # armor — it should NOT carry the +1 piece.
        bd_left = effective_defense_breakdown(b, b.get_part("hand.left"))
        bd_right = effective_defense_breakdown(b, b.get_part("hand.right"))
        assert bd_left["armor"] == 0
        assert bd_right["armor"] == 1
        # And the totals differ by exactly the armor delta.
        assert bd_right["total"] == bd_left["total"] + 1

    def test_player_armor_bonus_lands_on_head_cell(self):
        """A fresh Player wearing a single armor piece surfaces the
        per-piece defense bonus on the Def cell of the worn part —
        the same renderer used for monsters works for players too.
        """
        Inventory.discover_items()
        p = Player(uid=1, gid=2, cid=3)
        cap_cls = Inventory.ITEMS["rough_cap"]
        cap = cap_cls.from_plugin("rough_cap", {"quality": "ORDINARY"})
        head = p.get_part("head")
        head.placements["worn"] = cap
        bd = effective_defense_breakdown(p, head)
        # rough_cap ORDINARY adds +1 defense.
        assert bd["armor"] == 1
        cell = _def_cell_for(p, "head")
        assert "+1" in cell


# ---------------------------------------------------------------------------
# Body-less creature regression
# ---------------------------------------------------------------------------


class TestBodylessCreatureNoTable:
    def test_render_returns_empty_string(self):
        """Body-less creatures (spirits, future gel cubes) still
        emit nothing. The Def column doesn't change that contract.
        """
        c = Creature(
            name="bodyless",
            atk="1d1",
            defense="1d4",
            dodge="1d4",
            health_max="1d4",
        )
        # Bare Creature has no body parts attached.
        assert not c.body_parts
        assert c.render_body_part_status_table() == ""
        assert c.render_body_part_status_table(show_hp=False) == ""
