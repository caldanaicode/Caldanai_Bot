"""Sweep the weapon catalog through the duel simulator so balance
can be eyeballed across weapon × quality × skill × creature-size
dimensions — without spinning up the bot.

Usage::

    # Default: every weapon at ORDINARY quality, skill 10, vs all
    # six size tiers. Broadest-view table.
    python -m tools.playtest_weapon_sweep

    # One weapon across every quality, vs all sizes.
    python -m tools.playtest_weapon_sweep --weapon shortsword --sweep-qualities

    # One weapon across snapshot skill levels (0, 5, 10, 15, 20).
    python -m tools.playtest_weapon_sweep --weapon mace --sweep-skills

    # Explicit single scenario (no sweep).
    python -m tools.playtest_weapon_sweep --weapon warhammer --quality FINE --skill 15

    # Dual-wield: main hand + offhand, both same skill level.
    python -m tools.playtest_weapon_sweep --weapon mace --offhand shortsword
    python -m tools.playtest_weapon_sweep --weapon shortsword --offhand mace \\
        --sweep-qualities

Player-side stats (HP, defense, dodge) aren't weapon-driven — they
default to an "average player" profile (HP 20, def 3, dodge 15) and
can be overridden via ``--player-hp / --player-defense / --player-dodge``.

Why this exists: the inventory folder defines the entire weapon
catalog; simulating one weapon at a time via ``playtest_action_dice
--attacker-dice`` drifts each rewrite as loadouts change. A
catalog-aware tool keeps the numbers honest against whatever ships.
"""

from __future__ import annotations

import argparse
import importlib
import math
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from caldanai.lib.rpg.helpers.enums import Qualities, Size
from caldanai.lib.rpg.creatures.body_parts.action_dice import (
    size_scaled_dice,
)

# Duel harness + size profiles are shared with playtest_action_dice.
from tools.playtest_action_dice import _SIZE_PROFILE, _duel, _ALL_SIZES


_WEAPONS_DIR = (
    Path(__file__).resolve().parents[1]
    / "caldanai" / "lib" / "rpg" / "inventory" / "equipment" / "weapons"
)

_ALL_QUALITIES: List[Qualities] = [
    Qualities.JUNK, Qualities.ORDINARY, Qualities.FINE,
    Qualities.QUALITY, Qualities.SUPERIOR, Qualities.MASTERWORK,
]

_SKILL_SNAPSHOTS: List[int] = [0, 5, 10, 15, 20]


def _skill_bonus(skill_level: int) -> Tuple[int, int]:
    """Mirror :meth:`Player.get_skill_bonus` without importing Player
    (which pulls in discord.py). ``atk = level // 2``, ``dmg = level
    // 4``. Documented in player.py:650."""
    return math.floor(skill_level / 2), math.floor(skill_level / 4)


def _discover_weapon_stems() -> List[str]:
    """Every ``*.py`` stem under the weapons directory except
    ``__init__``, alphabetically ordered."""
    return sorted(
        p.stem for p in _WEAPONS_DIR.glob("*.py") if p.stem != "__init__"
    )


def _instantiate_weapon(stem: str, quality: Qualities):
    """Construct a ``WeaponPlugin`` instance without hitting Mongo —
    ``iid=None`` is enough for catalog probing."""
    module = importlib.import_module(
        f"caldanai.lib.rpg.inventory.equipment.weapons.{stem}"
    )
    return module.WeaponPlugin(iid=None, quality=quality, bonus=None)


def _effective_dice(weapon, skill_level: int) -> str:
    """``{weapon.attack}+{weapon.bonus + skill_dmg_bonus}`` as the
    dice expression the duel harness will roll each swing."""
    _, dmg = _skill_bonus(skill_level)
    total_bonus = weapon.bonus + dmg
    if total_bonus == 0:
        return weapon.attack
    if total_bonus > 0:
        return f"{weapon.attack}+{total_bonus}"
    return f"{weapon.attack}-{abs(total_bonus)}"


def _run_scenario(
    label: str,
    attacker_dice: List[str],
    player_hp: int,
    player_defense: int,
    player_dodge: int,
    skill_atk: int,
    trials: int,
    rounds_cap: int,
) -> Dict[Size, Dict[str, object]]:
    """Run the attacker (player-side) against every size tier's
    default profile. Returns per-size summary for table rendering."""
    summaries: Dict[Size, Dict[str, object]] = {}
    for size in _ALL_SIZES:
        profile = _SIZE_PROFILE[size]
        dice = size_scaled_dice(profile["action"], size)
        # Capture stdout from _duel into a summary by patching print.
        # _duel prints to stdout; for table rendering we need the
        # numbers as data, not formatted lines. Re-implement the loop
        # inline so we can return numbers.
        summaries[size] = _duel_silent(
            attacker_dice,
            attacker_hp=player_hp,
            attacker_defense=player_defense,
            attacker_hit=skill_atk,
            attacker_dodge=player_dodge,
            target_dice_list=[dice, dice],
            target_hp=profile["hp"],
            target_defense=profile["defense"],
            target_hit=profile["hit"],
            target_dodge=profile["dodge"],
            rounds_cap=rounds_cap,
            trials=trials,
        )
    return summaries


def _duel_silent(
    attacker_dice_list: List[str],
    *,
    attacker_hp: int, attacker_defense: int,
    attacker_hit: int, attacker_dodge: int,
    target_dice_list: List[str],
    target_hp: int, target_defense: int,
    target_hit: int, target_dodge: int,
    rounds_cap: int, trials: int,
) -> Dict[str, object]:
    """Numeric-return variant of :func:`playtest_action_dice._duel`.
    No stdout side-effects; produces the stats the matrix renderer
    needs per-cell."""
    from tools.playtest_action_dice import _hit_check, _roll_expr

    attacker_wins = 0
    target_wins = 0
    a_rounds: List[int] = []
    t_rounds: List[int] = []

    for _ in range(trials):
        a_hp = attacker_hp
        t_hp = target_hp
        rounds = 0
        while rounds < rounds_cap:
            rounds += 1
            for dice in attacker_dice_list:
                if not _hit_check(attacker_hit, target_dodge):
                    continue
                t_hp -= max(_roll_expr(dice) - target_defense, 1)
                if t_hp <= 0:
                    break
            if t_hp <= 0:
                attacker_wins += 1
                a_rounds.append(rounds)
                break
            for dice in target_dice_list:
                if not _hit_check(target_hit, attacker_dodge):
                    continue
                a_hp -= max(_roll_expr(dice) - attacker_defense, 1)
                if a_hp <= 0:
                    break
            if a_hp <= 0:
                target_wins += 1
                t_rounds.append(rounds)
                break

    return {
        "attacker_wins": attacker_wins,
        "target_wins": target_wins,
        "trials": trials,
        "win_rate": attacker_wins / trials,
        "avg_win_rounds": (sum(a_rounds) / len(a_rounds)) if a_rounds else None,
        "avg_loss_rounds": (sum(t_rounds) / len(t_rounds)) if t_rounds else None,
    }


def _format_cell(summary: Dict[str, object]) -> str:
    """Compact per-cell formatting: win% and avg rounds (winner)."""
    rate = summary["win_rate"]
    if rate == 1.0:
        rounds = summary["avg_win_rounds"]
        return f"100% in {rounds:.1f}" if rounds else "100%"
    if rate == 0.0:
        rounds = summary["avg_loss_rounds"]
        return f"0% (die {rounds:.1f})" if rounds else "0%"
    win_r = summary["avg_win_rounds"]
    loss_r = summary["avg_loss_rounds"]
    pct = int(rate * 100)
    return f"{pct}% w{win_r:.0f}/l{loss_r:.0f}"


def _print_matrix(
    title: str,
    rows: List[Tuple[str, Dict[Size, Dict[str, object]]]],
) -> None:
    """Render a row_label × size_tier matrix."""
    print(f"# {title}")
    header = f"{'':<28}"
    for size in _ALL_SIZES:
        header += f" | {size.name:<16}"
    print(header)
    print("-" * len(header))
    for row_label, row_summaries in rows:
        line = f"{row_label:<28}"
        for size in _ALL_SIZES:
            line += f" | {_format_cell(row_summaries[size]):<16}"
        print(line)
    print()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--weapon", default=None,
                    help="Weapon stem to focus on (e.g. 'shortsword'). "
                         "Omit to sweep every weapon in the catalog.")
    ap.add_argument("--offhand", default=None,
                    help="Offhand weapon stem for dual-wield sims "
                         "(e.g. 'shortsword'). Both hands swing each "
                         "round. Skill level applies to both unless "
                         "--offhand-skill is supplied.")
    ap.add_argument("--offhand-skill", type=int, default=None,
                    help="Override skill level for the offhand weapon. "
                         "Defaults to --skill. Only damage bonus differs "
                         "per hand; the hit modifier uses the main-hand "
                         "skill for both swings (approximation — the "
                         "game would use each weapon's own skill).")
    ap.add_argument("--quality", default="ORDINARY",
                    choices=[q.name for q in _ALL_QUALITIES],
                    help="Weapon quality tier (default ORDINARY).")
    ap.add_argument("--offhand-quality", default=None,
                    choices=[q.name for q in _ALL_QUALITIES] + [None],
                    help="Offhand quality override. Defaults to --quality.")
    ap.add_argument("--skill", type=int, default=10,
                    help="Player skill level in the weapon's damage "
                         "type (0-20, default 10).")
    ap.add_argument("--sweep-qualities", action="store_true",
                    help="Fix weapon + skill, iterate all qualities.")
    ap.add_argument("--sweep-skills", action="store_true",
                    help="Fix weapon + quality, iterate skill snapshots "
                         f"({_SKILL_SNAPSHOTS}).")
    ap.add_argument("--player-hp", type=int, default=20,
                    help="Player HP (default 20).")
    ap.add_argument("--player-defense", type=int, default=3,
                    help="Player defense (default 3).")
    ap.add_argument("--player-dodge", type=int, default=15,
                    help="Player dodge (default 15).")
    ap.add_argument("--trials", type=int, default=200,
                    help="Duel trials per cell (default 200).")
    ap.add_argument("--rounds", type=int, default=30,
                    help="Max rounds per duel trial (default 30).")
    ap.add_argument("--seed", type=int, default=0,
                    help="Random seed (default 0).")
    args = ap.parse_args(argv)

    random.seed(args.seed)

    if args.sweep_qualities and args.sweep_skills:
        ap.error("--sweep-qualities and --sweep-skills are exclusive")

    offhand_skill = (
        args.offhand_skill if args.offhand_skill is not None else args.skill
    )

    def _build_dice_list(
        main_stem: str, main_quality: Qualities, main_skill: int,
    ) -> Tuple[List[str], str]:
        """Assemble attacker_dice for the duel harness, optionally
        adding the offhand. Returns (dice_list, label_suffix)."""
        w_main = _instantiate_weapon(main_stem, main_quality)
        dice = [_effective_dice(w_main, main_skill)]
        label = dice[0]
        if args.offhand:
            oh_quality = (
                Qualities[args.offhand_quality]
                if args.offhand_quality else main_quality
            )
            w_off = _instantiate_weapon(args.offhand, oh_quality)
            off_dice = _effective_dice(w_off, offhand_skill)
            dice.append(off_dice)
            label = f"{label} + {off_dice}"
        return dice, label

    if args.sweep_qualities:
        if not args.weapon:
            ap.error("--sweep-qualities requires --weapon")
        rows: List[Tuple[str, Dict[Size, Dict[str, object]]]] = []
        for q in _ALL_QUALITIES:
            dice_list, label = _build_dice_list(args.weapon, q, args.skill)
            atk_bonus, _ = _skill_bonus(args.skill)
            summaries = _run_scenario(
                label=f"{args.weapon} {q.name}",
                attacker_dice=dice_list,
                player_hp=args.player_hp,
                player_defense=args.player_defense,
                player_dodge=args.player_dodge,
                skill_atk=atk_bonus,
                trials=args.trials,
                rounds_cap=args.rounds,
            )
            rows.append((f"{q.name} [{label}]", summaries))
        title_suffix = f"+ {args.offhand}" if args.offhand else ""
        _print_matrix(
            f"{args.weapon} {title_suffix} × qualities (skill {args.skill}, "
            f"hp={args.player_hp} def={args.player_defense} "
            f"dodge={args.player_dodge})",
            rows,
        )
        return 0

    if args.sweep_skills:
        if not args.weapon:
            ap.error("--sweep-skills requires --weapon")
        quality = Qualities[args.quality]
        rows = []
        for lvl in _SKILL_SNAPSHOTS:
            dice_list, label = _build_dice_list(args.weapon, quality, lvl)
            atk_bonus, _ = _skill_bonus(lvl)
            summaries = _run_scenario(
                label=f"{args.weapon} skill{lvl}",
                attacker_dice=dice_list,
                player_hp=args.player_hp,
                player_defense=args.player_defense,
                player_dodge=args.player_dodge,
                skill_atk=atk_bonus,
                trials=args.trials,
                rounds_cap=args.rounds,
            )
            rows.append((f"skill {lvl:>2} [{label}] +{atk_bonus}hit", summaries))
        title_suffix = f"+ {args.offhand}" if args.offhand else ""
        _print_matrix(
            f"{args.weapon} {title_suffix} ({quality.name}) × skill levels "
            f"(hp={args.player_hp} def={args.player_defense} "
            f"dodge={args.player_dodge})",
            rows,
        )
        return 0

    # Default: full catalog sweep at one quality + skill.
    stems = [args.weapon] if args.weapon else _discover_weapon_stems()
    quality = Qualities[args.quality]
    atk_bonus, _ = _skill_bonus(args.skill)
    rows = []
    for stem in stems:
        dice_list, label = _build_dice_list(stem, quality, args.skill)
        summaries = _run_scenario(
            label=stem,
            attacker_dice=dice_list,
            player_hp=args.player_hp,
            player_defense=args.player_defense,
            player_dodge=args.player_dodge,
            skill_atk=atk_bonus,
            trials=args.trials,
            rounds_cap=args.rounds,
        )
        rows.append((f"{stem} [{label}]", summaries))
    title_suffix = f"+ {args.offhand}" if args.offhand else ""
    _print_matrix(
        f"Weapon catalog {title_suffix} × sizes (quality={quality.name}, "
        f"skill={args.skill}, hp={args.player_hp} def={args.player_defense} "
        f"dodge={args.player_dodge})",
        rows,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
