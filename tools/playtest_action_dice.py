"""Roll Phase 3 body-part action dice across sizes so the numbers
can be eyeballed for feel before runtime wires them in.

Usage::

    # Matrix: every action × every size, N rolls each (default 20).
    python -m tools.playtest_action_dice

    # Focused: one action at one size, show each roll.
    python -m tools.playtest_action_dice --action stomp --size LARGE

    # More samples to smooth out variance.
    python -m tools.playtest_action_dice --rolls 200

    # "How many rounds to kill a 30-HP target with defense 5?"
    python -m tools.playtest_action_dice --action bite --size LARGE \\
        --fight --target-hp 30 --target-defense 5 --rounds 10

Why this exists: Phase 3's ``size_scaled_dice`` tier tables set the
baseline damage every creature starts from. Tuning them requires
seeing sample distributions, not just reading a table.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
from typing import List, Optional, Tuple

from caldanai.lib.rpg.creatures.body_parts.action_dice import (
    _ACTION_TIERS, _FALLBACK, size_scaled_dice,
)
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import Size


_ALL_ACTIONS = list(_ACTION_TIERS.keys())
_ALL_SIZES = [
    Size.TINY, Size.SMALL, Size.MEDIUM,
    Size.LARGE, Size.HUGE, Size.COLOSSAL,
]


# Representative target profiles per size tier, grounded in current
# monster stats (pixie/goblin/bandit/minotaur/giant/-). COLOSSAL has
# no live example — numbers extrapolated from HUGE trajectory.
# Numbers are rolled-equivalent point estimates (HP/def rolled at
# spawn is variable; this picks a middling value).
_SIZE_PROFILE = {
    Size.TINY:     {"hp":   5, "defense":  2, "dodge": 15, "hit": 3, "action": "bite"},
    Size.SMALL:    {"hp":  17, "defense":  6, "dodge":  3, "hit": 1, "action": "bite"},
    Size.MEDIUM:   {"hp":  14, "defense":  7, "dodge":  3, "hit": 2, "action": "bite"},
    Size.LARGE:    {"hp":  33, "defense":  7, "dodge":  3, "hit": 4, "action": "bite"},
    Size.HUGE:     {"hp":  98, "defense":  9, "dodge":  2, "hit": 6, "action": "bite"},
    Size.COLOSSAL: {"hp": 250, "defense": 12, "dodge":  2, "hit": 8, "action": "bite"},
}


def _parse_dice_expr(expr: str) -> Tuple[str, int]:
    """Split ``NdM+K`` / ``NdM-K`` into (dice_part, modifier)."""
    expr = expr.replace(" ", "")
    if "+" in expr:
        dice_part, _, mod_part = expr.partition("+")
        return dice_part, int(mod_part)
    if "-" in expr and "d" in expr.split("-", 1)[0]:
        dice_part, _, mod_part = expr.partition("-")
        return dice_part, -int(mod_part)
    return expr, 0


def _roll_expr(expr: str) -> int:
    """Roll ``NdM+K`` / ``NdM-K`` / ``NdM``. Dice.quick_roll doesn't
    handle the modifier suffix — this helper does."""
    dice_part, mod = _parse_dice_expr(expr)
    return Dice.quick_roll(dice_part) + mod


def _expected(dice_str: str) -> float:
    """Analytical expected value for an ``NdM[+K]`` dice string."""
    dice_part, mod = _parse_dice_expr(dice_str)
    count_str, _, faces_str = dice_part.partition("d")
    count = int(count_str) if count_str else 1
    faces = int(faces_str)
    return count * (faces + 1) / 2 + mod


def _roll_samples(dice_str: str, n: int) -> List[int]:
    return [_roll_expr(dice_str) for _ in range(n)]


def _stats(samples: List[int]) -> Tuple[float, int, int, float]:
    mean = statistics.mean(samples)
    stdev = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    return mean, min(samples), max(samples), stdev


def _matrix(rolls: int) -> None:
    header = f"{'action':<12}"
    for size in _ALL_SIZES:
        header += f" | {size.name:<15}"
    print(header)
    print("-" * len(header))
    for action in _ALL_ACTIONS:
        row = f"{action:<12}"
        for size in _ALL_SIZES:
            dice_str = size_scaled_dice(action, size)
            samples = _roll_samples(dice_str, rolls)
            mean, mn, mx, _ = _stats(samples)
            cell = f"{dice_str} {mean:4.1f} [{mn},{mx}]"
            row += f" | {cell:<15}"
        print(row)
    print()
    print(f"(each cell: dice-string  empirical-mean  [min,max] over {rolls} rolls)")


def _focused(action: str, size: Size, rolls: int) -> None:
    dice_str = size_scaled_dice(action, size)
    samples = _roll_samples(dice_str, rolls)
    mean, mn, mx, stdev = _stats(samples)
    print(f"# {action} at {size.name} — dice={dice_str} "
          f"(expected avg {_expected(dice_str):.1f})")
    print(f"  rolls: {samples}")
    print(f"  min={mn}, max={mx}, mean={mean:.2f}, stdev={stdev:.2f}")


def _fight(
    action: str,
    size: Size,
    target_hp: int,
    target_defense: int,
    rounds_cap: int,
    trials: int,
) -> None:
    """Run ``trials`` simulated fights. Each fight: repeatedly roll the
    action, subtract ``target_defense`` (floored at 1), accumulate
    until ``target_hp`` is depleted or ``rounds_cap`` is reached.
    Report rounds-to-kill distribution."""
    dice_str = size_scaled_dice(action, size)
    rounds_to_kill: List[int] = []
    overruns = 0
    for _ in range(trials):
        hp = target_hp
        for r in range(1, rounds_cap + 1):
            raw = _roll_expr(dice_str)
            final = max(raw - target_defense, 1)
            hp -= final
            if hp <= 0:
                rounds_to_kill.append(r)
                break
        else:
            overruns += 1

    print(
        f"# {action} at {size.name} vs target HP={target_hp} "
        f"defense={target_defense} (dice={dice_str}, {trials} trials)"
    )
    if rounds_to_kill:
        mean = statistics.mean(rounds_to_kill)
        median = statistics.median(rounds_to_kill)
        print(
            f"  rounds-to-kill: min={min(rounds_to_kill)}, "
            f"max={max(rounds_to_kill)}, mean={mean:.1f}, median={median:.0f}"
        )
    if overruns:
        print(f"  overruns (target survived {rounds_cap} rounds): {overruns}")


def _hit_check(hit_mod: int, dodge: int) -> bool:
    """d20 + hit_mod vs dodge. Matches the combat helper's shape
    (``roll + mod >= dodge`` → HIT). With both defaults at 0, every
    swing connects — useful for pure-damage evaluation."""
    return random.randint(1, 20) + hit_mod >= dodge


def _duel(
    attacker_dice_list: List[str],
    attacker_hp: int,
    attacker_defense: int,
    attacker_hit: int,
    attacker_dodge: int,
    target_dice_list: List[str],
    target_hp: int,
    target_defense: int,
    target_hit: int,
    target_dodge: int,
    rounds_cap: int,
    trials: int,
    label: str,
) -> None:
    """Two-sided simulation. Each round: every attacker dice rolls a
    hit check (``d20 + attacker_hit`` vs ``target_dodge``); on hit,
    damage rolls and is defense-subtracted (floor 1). Then target
    swings back the same way. Continues until one side's HP hits 0
    or ``rounds_cap`` elapses.

    Defaults of hit=0 and dodge=0 produce the pure-damage view
    (every swing connects). Set ``--attacker-dodge 18 --target-hit 2``
    to model Celowin's dodge stat saving him from small creatures."""
    attacker_wins = 0
    target_wins = 0
    stalemates = 0
    rounds_when_attacker_wins: List[int] = []
    rounds_when_target_wins: List[int] = []
    attacker_hits = attacker_misses = 0
    target_hits = target_misses = 0

    for _ in range(trials):
        a_hp = attacker_hp
        t_hp = target_hp
        rounds = 0
        while rounds < rounds_cap:
            rounds += 1
            # Attacker's swings.
            for dice in attacker_dice_list:
                if not _hit_check(attacker_hit, target_dodge):
                    attacker_misses += 1
                    continue
                attacker_hits += 1
                raw = _roll_expr(dice)
                final = max(raw - target_defense, 1)
                t_hp -= final
                if t_hp <= 0:
                    break
            if t_hp <= 0:
                attacker_wins += 1
                rounds_when_attacker_wins.append(rounds)
                break
            # Target's swings.
            for dice in target_dice_list:
                if not _hit_check(target_hit, attacker_dodge):
                    target_misses += 1
                    continue
                target_hits += 1
                raw = _roll_expr(dice)
                final = max(raw - attacker_defense, 1)
                a_hp -= final
                if a_hp <= 0:
                    break
            if a_hp <= 0:
                target_wins += 1
                rounds_when_target_wins.append(rounds)
                break
        else:
            stalemates += 1

    print(f"# {label}")
    print(
        f"  attacker: dice={attacker_dice_list} hp={attacker_hp} "
        f"def={attacker_defense} hit=+{attacker_hit} dodge={attacker_dodge}"
    )
    print(
        f"  target:   dice={target_dice_list} hp={target_hp} "
        f"def={target_defense} hit=+{target_hit} dodge={target_dodge}"
    )
    print(f"  trials={trials} rounds_cap={rounds_cap}")
    attacker_total = attacker_hits + attacker_misses
    target_total = target_hits + target_misses
    if attacker_total:
        print(
            f"  attacker accuracy: {attacker_hits}/{attacker_total} "
            f"({attacker_hits / attacker_total:.0%} hit rate)"
        )
    if target_total:
        print(
            f"  target accuracy:   {target_hits}/{target_total} "
            f"({target_hits / target_total:.0%} hit rate)"
        )
    print(
        f"  outcomes: attacker_wins={attacker_wins} "
        f"target_wins={target_wins} stalemates={stalemates} "
        f"(attacker_win_rate={attacker_wins / trials:.0%})"
    )
    if rounds_when_attacker_wins:
        mean = statistics.mean(rounds_when_attacker_wins)
        print(
            f"  attacker win rounds: min={min(rounds_when_attacker_wins)} "
            f"max={max(rounds_when_attacker_wins)} mean={mean:.1f}"
        )
    if rounds_when_target_wins:
        mean = statistics.mean(rounds_when_target_wins)
        print(
            f"  target win rounds:   min={min(rounds_when_target_wins)} "
            f"max={max(rounds_when_target_wins)} mean={mean:.1f}"
        )


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--action", default=None,
                    help=f"focus one action (one of: {', '.join(_ALL_ACTIONS)}). "
                         "Omit for matrix mode.")
    ap.add_argument("--size", default=None,
                    help="focus one size (TINY/SMALL/MEDIUM/LARGE/HUGE/"
                         "COLOSSAL). Omit for matrix or full-size focused.")
    ap.add_argument("--rolls", type=int, default=20,
                    help="samples per cell / focused roll (default 20).")
    ap.add_argument("--seed", type=int, default=None,
                    help="seed random for reproducible runs.")
    # Fight / duel modes
    ap.add_argument("--fight", action="store_true",
                    help="simulate fights vs a target HP/defense. "
                         "Requires --action and --size.")
    ap.add_argument("--target-hp", type=int, default=30,
                    help="target HP (default 30).")
    ap.add_argument("--target-defense", type=int, default=0,
                    help="target defense subtracted per hit, "
                         "floored at 1 damage (default 0).")
    ap.add_argument("--rounds", type=int, default=20,
                    help="max rounds per fight/duel trial (default 20).")
    ap.add_argument("--trials", type=int, default=50,
                    help="fight/duel trial count (default 50).")
    ap.add_argument("--duel", action="store_true",
                    help="two-sided simulation: attacker vs target, "
                         "both swing each round, both have HP. No "
                         "hit-roll/dodge modeling (pure damage exchange).")
    ap.add_argument("--attacker-dice", default=None,
                    help="comma-separated dice for duel-mode attacker "
                         "(e.g. '2d4+4,2d6+3' for dual-wield). Each "
                         "expression is one swing per round.")
    ap.add_argument("--attacker-hp", type=int, default=20,
                    help="attacker HP for --duel mode (default 20).")
    ap.add_argument("--attacker-defense", type=int, default=0,
                    help="attacker defense for --duel mode (default 0).")
    ap.add_argument("--attacker-hit", type=int, default=0,
                    help="attacker to-hit modifier (d20 + mod vs "
                         "target_dodge). Default 0.")
    ap.add_argument("--attacker-dodge", type=int, default=0,
                    help="attacker dodge; target swings miss below this. "
                         "Default 0 (every target swing connects).")
    ap.add_argument("--target-dice", default=None,
                    help="comma-separated dice for duel-mode target. "
                         "If omitted and --action+--size supplied, "
                         "falls back to size-scaled action dice.")
    ap.add_argument("--target-hit", type=int, default=0,
                    help="target to-hit modifier (d20 + mod vs "
                         "attacker_dodge). Default 0.")
    ap.add_argument("--target-dodge", type=int, default=0,
                    help="target dodge; attacker swings miss below this. "
                         "Default 0 (every attacker swing connects).")
    ap.add_argument("--label", default="duel",
                    help="label shown in --duel mode output header.")
    ap.add_argument("--vs-sizes", action="store_true",
                    help="Run --duel against every size tier's default "
                         "creature profile (TINY..COLOSSAL). Uses "
                         "--action + creature-per-size attack pattern. "
                         "One python invocation instead of a bash sweep. "
                         "Requires --attacker-dice (and optionally "
                         "--attacker-hp/def/hit/dodge).")
    ap.add_argument("--action-per-size", default="bite",
                    help="Action used by creatures in --vs-sizes sweeps "
                         "(default 'bite'). Combined 2x per round to "
                         "mirror default creature action budget.")
    args = ap.parse_args(argv)

    if args.seed is not None:
        random.seed(args.seed)

    if args.vs_sizes:
        if not args.attacker_dice:
            ap.error("--vs-sizes requires --attacker-dice")
        attacker_dice_list = [s.strip() for s in args.attacker_dice.split(",")]
        for size in _ALL_SIZES:
            profile = _SIZE_PROFILE[size]
            dice = size_scaled_dice(args.action_per_size, size)
            _duel(
                attacker_dice_list,
                attacker_hp=args.attacker_hp,
                attacker_defense=args.attacker_defense,
                attacker_hit=args.attacker_hit,
                attacker_dodge=args.attacker_dodge,
                target_dice_list=[dice, dice],  # creature default budget: 2
                target_hp=profile["hp"],
                target_defense=profile["defense"],
                target_hit=profile["hit"],
                target_dodge=profile["dodge"],
                rounds_cap=args.rounds,
                trials=args.trials,
                label=(
                    f"{args.label} vs {size.name} creature "
                    f"(2x {dice}, hp={profile['hp']} def={profile['defense']} "
                    f"dodge={profile['dodge']} hit=+{profile['hit']})"
                ),
            )
            print()
        return 0

    if args.duel:
        if not args.attacker_dice:
            ap.error("--duel requires --attacker-dice")
        attacker_dice_list = [s.strip() for s in args.attacker_dice.split(",")]
        if args.target_dice:
            target_dice_list = [s.strip() for s in args.target_dice.split(",")]
        elif args.action and args.size:
            size = Size[args.size.upper()]
            target_dice_list = [size_scaled_dice(args.action, size)]
        else:
            ap.error("--duel requires --target-dice OR (--action AND --size)")
        _duel(
            attacker_dice_list,
            attacker_hp=args.attacker_hp,
            attacker_defense=args.attacker_defense,
            attacker_hit=args.attacker_hit,
            attacker_dodge=args.attacker_dodge,
            target_dice_list=target_dice_list,
            target_hp=args.target_hp,
            target_defense=args.target_defense,
            target_hit=args.target_hit,
            target_dodge=args.target_dodge,
            rounds_cap=args.rounds,
            trials=args.trials,
            label=args.label,
        )
        return 0

    if args.fight:
        if not args.action or not args.size:
            ap.error("--fight requires --action and --size")
        size = Size[args.size.upper()]
        _fight(
            args.action, size,
            target_hp=args.target_hp,
            target_defense=args.target_defense,
            rounds_cap=args.rounds,
            trials=args.trials,
        )
        return 0

    if args.action and args.size:
        size = Size[args.size.upper()]
        _focused(args.action, size, args.rolls)
        return 0

    if args.action:
        for size in _ALL_SIZES:
            _focused(args.action, size, args.rolls)
            print()
        return 0

    _matrix(args.rolls)
    return 0


if __name__ == "__main__":
    sys.exit(main())
