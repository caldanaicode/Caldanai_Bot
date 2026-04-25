"""Render synthetic combat-table markdown so layout edits to
``AttackSequence.to_markdown`` can be eyeballed across every shape
the resolver emits — without spinning up the bot, scripting a
fight, or reaching for ``python -c``.

Usage::

    python -m tools.render_combat_table                    # all scenarios
    python -m tools.render_combat_table --scenario default
    python -m tools.render_combat_table --scenario auto-hit
    python -m tools.render_combat_table --scenario miss
    python -m tools.render_combat_table --scenario multi-target

Why this exists: a tweak to the per-row column layout (Def column
reintroduced, ANSI vs diff fence, etc.) needs visual inspection
across every code path — single-vs-multi target, miss-vs-hit,
auto-hit dragon-breath shape. Inline ``python -c`` rebuilds the
synthetic ``AttackSequence`` from scratch each time and re-prompts
for permission. One tool covers every layout-regression workflow.
"""

from __future__ import annotations

import argparse
import sys
from typing import Callable, Dict, List, Optional
from unittest.mock import MagicMock

from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.helpers.roll_data import (
    AttackRoll, CombinedRoll, DamageRoll,
)


def _make_combined(
    *,
    forced_attack: int = 15,
    forced_damage: int = 6,
    dodge: int = 10,
) -> CombinedRoll:
    """Synthetic CombinedRoll. ``forced_attack`` of 20 → crit, 1 →
    fumble; anything in-between is a normal hit when ``forced_attack
    >= dodge``. Mirrors the test-helper convention so authored
    scenarios read the same as ``tests/test_attack_result.py``."""
    atk = AttackRoll(skill_bonus=0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    atk.rolls = (forced_attack,)
    atk.result = forced_attack
    atk.isCritical = forced_attack == 20
    atk.isFumble = forced_attack == 1
    dmg.rolls = (forced_damage,)
    dmg.result = forced_damage
    return CombinedRoll(atk, dmg, dodge)


def _make_source(label: str, dmg_type: DamageTypes) -> MagicMock:
    src = MagicMock()
    src.label = label
    src.damage_type = dmg_type
    return src


def _make_result(
    *,
    label: str = "Left",
    damage: int = 5,
    multiplier: float = 1.0,
    defense: int = 2,
    dodge: int = 10,
    dmg_type: DamageTypes = DamageTypes.SLASHING,
    is_miss: bool = False,
    is_critical: bool = False,
    auto_hit: bool = False,
    forced_damage: int = 6,
) -> AttackResult:
    forced_attack = (
        20 if is_critical else (1 if is_miss else 15)
    )
    combined = _make_combined(
        forced_attack=forced_attack,
        forced_damage=forced_damage,
        dodge=dodge,
    )
    r = AttackResult(
        source=_make_source(label, dmg_type),
        combined=combined,
        damage=damage,
        multiplier=multiplier,
        defense=defense,
        dodge=dodge,
        dmg_type=dmg_type,
    )
    if auto_hit:
        r.auto_hit = True
    return r


def _make_sequence(results: List[AttackResult]) -> AttackSequence:
    attacker = MagicMock()
    attacker.name = "bandit"
    attacker.member = None
    target = MagicMock()
    target.name = "Caels"
    return AttackSequence(attacker=attacker, target=target, results=results)


# ---------------------------------------------------------------------------
# Scenarios — each returns an AttackSequence ready to render.
# ---------------------------------------------------------------------------


def _scenario_default() -> AttackSequence:
    """Two-source dual-wield: one slash, one pierce, both hit, both
    have defense absorption. Most common combat shape."""
    return _make_sequence([
        _make_result(label="Left", damage=4, defense=2),
        _make_result(
            label="Right", damage=3, defense=3,
            dmg_type=DamageTypes.PIERCING,
        ),
    ])


def _scenario_auto_hit() -> AttackSequence:
    """Dragon-breath shape — both sources auto-hit, no roll v dodge
    column. Defense still absorbs. ``forced_damage`` is set high so
    the post-multiplier sub_damage exceeds the final damage by the
    defense amount — matches real-combat invariant where defense
    only absorbs, never amplifies."""
    return _make_sequence([
        _make_result(
            label="Breath", damage=6, defense=2, forced_damage=8,
            dmg_type=DamageTypes.FIRE, auto_hit=True,
        ),
        _make_result(
            label="Tail Slap", damage=4, defense=1, forced_damage=5,
            dmg_type=DamageTypes.BLUDGEONING, auto_hit=True,
        ),
    ])


def _scenario_miss() -> AttackSequence:
    """One miss, one hit. Confirms the Def column shows ``-`` on
    miss and a value on hit, and that column widths align."""
    return _make_sequence([
        _make_result(label="Left",  damage=0, is_miss=True),
        _make_result(label="Right", damage=4, defense=2,
                     dmg_type=DamageTypes.PIERCING),
    ])


def _scenario_no_absorption() -> AttackSequence:
    """Both hit, defense is 0 — exposes the ``Def: 0`` row that the
    pre-fix format collapsed away as a simple Total. Regression for
    the 2026-04-24 skeleton-vs-werewolf format-inconsistency
    finding."""
    return _make_sequence([
        _make_result(label="Left",  damage=6, defense=0, forced_damage=6),
        _make_result(label="Right", damage=6, defense=0, forced_damage=6,
                     dmg_type=DamageTypes.PIERCING),
    ])


def _scenario_multi_target() -> AttackSequence:
    """AOE hitting two distinct victims — exercises the per-victim
    Total breakout."""
    seq = _make_sequence([
        _make_result(label="Cleave → Caels",  damage=4, defense=2),
        _make_result(label="Cleave → Serena", damage=3, defense=3),
    ])
    seq.multi_target = True
    # Per-victim grouping path looks at ``r.victim`` first; populate
    # those so the breakout reads correctly under our synthetic
    # results (real combat sets these in ``Creature.resolve``).
    caels = MagicMock(); caels.name = "Caels"
    serena = MagicMock(); serena.name = "Serena"
    seq.results[0].victim = caels
    seq.results[1].victim = serena
    return seq


def _scenario_multi_target_untouched() -> AttackSequence:
    """Multi-target where one victim was aimed at but every result
    against them missed. Exercises the ``Victim: untouched`` short-
    circuit in the per-victim footer (added 2026-04-25 to drop the
    ``Victim: 0 raw - 0 absorbed → 0 damage`` noise that the live
    hydra playtest flagged)."""
    seq = _make_sequence([
        _make_result(label="Cleave → Caels", damage=4, defense=2),
        _make_result(label="Cleave → Serena", damage=0, is_miss=True),
    ])
    seq.multi_target = True
    caels = MagicMock(); caels.name = "Caels"
    serena = MagicMock(); serena.name = "Serena"
    seq.results[0].victim = caels
    seq.results[1].victim = serena
    return seq


SCENARIOS: Dict[str, Callable[[], AttackSequence]] = {
    "default":               _scenario_default,
    "auto-hit":              _scenario_auto_hit,
    "miss":                  _scenario_miss,
    "no-absorption":         _scenario_no_absorption,
    "multi-target":          _scenario_multi_target,
    "multi-target-untouched": _scenario_multi_target_untouched,
}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--scenario", default="all",
        choices=["all", *SCENARIOS.keys()],
        help="single scenario to render (default: 'all' — emits "
             "every shape stacked, useful for layout regressions).",
    )
    args = ap.parse_args(argv)

    if args.scenario == "all":
        for name, builder in SCENARIOS.items():
            print(f"\n## scenario: {name}\n")
            print(builder().to_markdown(), end="")
        return 0

    print(SCENARIOS[args.scenario]().to_markdown(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
