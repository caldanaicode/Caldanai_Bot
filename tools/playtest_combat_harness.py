"""End-to-end combat harness driving the REAL pipeline stages
headlessly — no Discord, no Game orchestration. Lets balance-
checking see true numbers (part HP, critical-part kills, exposure-
weighted dodge, trait multipliers, etc.) instead of the simplified
dice math in ``playtest_action_dice`` / ``playtest_weapon_sweep``.

Usage::

    # Celowin-ish loadout vs minotaur, 200 trials seeded.
    python -m tools.playtest_combat_harness \\
        --weapon mace --offhand shortsword \\
        --monster minotaur --trials 200

    # Two-handed spear vs dragon, 50 trials.
    python -m tools.playtest_combat_harness \\
        --weapon spear --monster dragon --trials 50

    # Exercise the critical-part-kill path — aim every swing at head.
    python -m tools.playtest_combat_harness \\
        --weapon shortsword --monster goblin \\
        --target-part head --trials 200

    # Skill level + quality sweeping.
    python -m tools.playtest_combat_harness \\
        --weapon bow --quality MASTERWORK --skill 20 \\
        --monster hydra --trials 50

Invokes the Phase-6d Player pipeline (``pick_actions`` →
``pick_targets`` → ``resolve`` → body-HP) and the Phase-6b/c
Monster pipeline (``attack_random`` → pipeline stages) per round.
Runs until one side dies or ``--rounds`` caps out. Reports per-
trial outcome and aggregate stats: win rate, avg rounds, critical-
part-kill rate, total damage dealt/received.

Why this exists: ``playtest_weapon_sweep`` abstracts combat as a
damage-vs-HP math problem. A real combat run exercises exposure-
weighted target-part selection, critical-part kills (head
destruction = instant death regardless of body HP), trait
multipliers, arm-injury-driven attack dropout, size-scaled dodge,
and all the other emergent behavior the simplified sims don't
model. This harness gives balance work access to ground truth.
"""

from __future__ import annotations

import argparse
import importlib
import itertools
import os
import random
import statistics
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple
from unittest.mock import MagicMock, patch

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities


_WEAPONS_DIR = (
    Path(__file__).resolve().parents[1]
    / "caldanai" / "lib" / "rpg" / "inventory" / "equipment" / "weapons"
)


def _discover_weapon_stems() -> List[str]:
    return sorted(
        p.stem for p in _WEAPONS_DIR.glob("*.py") if p.stem != "__init__"
    )


def _classify_weapons() -> Tuple[List[str], List[str]]:
    """Return (one_handed_stems, two_handed_stems) by instantiating
    each weapon once and reading its slot mask."""
    one_h: List[str] = []
    two_h: List[str] = []
    for stem in _discover_weapon_stems():
        w = _instantiate_weapon(stem, Qualities.ORDINARY)
        if EquipmentSlots.MULTI_SLOT & w.slots:
            two_h.append(stem)
        else:
            one_h.append(stem)
    return one_h, two_h


@dataclass
class TrialOutcome:
    winner: str  # "player" | "monster" | "stalemate"
    rounds: int
    damage_dealt: int
    damage_received: int
    critical_part_kill: bool  # player killed monster via critical part
    destroyed_parts: List[str] = field(default_factory=list)


def _instantiate_weapon(stem: str, quality: Qualities):
    import importlib
    module = importlib.import_module(
        f"caldanai.lib.rpg.inventory.equipment.weapons.{stem}"
    )
    return module.WeaponPlugin(iid=None, quality=quality, bonus=None)


def _build_player(
    *, name: str, hp: int, defense: int, dodge: int,
    weapon: Optional[str], offhand: Optional[str],
    quality: Qualities, skill_level: int,
) -> Player:
    """Headless Player. No Discord Member, no DB. Equip slots seeded
    directly from the weapon plugin registry."""
    p = Player(
        pid=1, gid=1, uid=1,
        health=hp, health_max=hp,
        defense=defense, dodge=dodge,
        gender="female", pronouns="she,her,hers,her",
        weight_limit=100, clarks=0,
    )
    p.name = name
    p.member = MagicMock()
    p.member.id = 1
    p.member.roles = []

    # Seed the skill(s) a real player would have accrued.
    if skill_level > 0:
        if weapon:
            w = _instantiate_weapon(weapon, quality)
            p.skills[w.skill] = _xp_for_level(skill_level)
        if offhand:
            w = _instantiate_weapon(offhand, quality)
            if w.skill not in p.skills:
                p.skills[w.skill] = _xp_for_level(skill_level)

    # Equip into the part-equipment shape. Phase D moved weapons
    # from arm.*.held to hand.*.held.
    if weapon:
        w_main = _instantiate_weapon(weapon, quality)
        if EquipmentSlots.MULTI_SLOT & w_main.slots:
            p.part_equipment["hand.left"]["held"] = w_main
            p.part_equipment["hand.right"]["held"] = w_main
        else:
            p.part_equipment["hand.left"]["held"] = w_main
            if offhand:
                w_off = _instantiate_weapon(offhand, quality)
                if EquipmentSlots.MULTI_SLOT & w_off.slots:
                    raise SystemExit(
                        f"Offhand weapon '{offhand}' is two-handed; "
                        "pick a one-handed offhand or omit --offhand."
                    )
                p.part_equipment["hand.right"]["held"] = w_off
    return p


def _xp_for_level(level: int) -> int:
    """Enough XP to put ``Player.get_skill_level`` at ``level``.
    Mirrors the XP curve in Player.gain_skill_experience — 10 base
    per grant at level 0, scaling. We set a flat value above the
    level-20 cap so ``get_skill_level`` clamps to the intent."""
    if level >= 20:
        return 1_000_000  # past cap
    # Approximate inverse of the gain curve; over-provision is fine.
    return max(level * 1000, 100)


def _spawn_monster(stem: str):
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(stem)
    if cls is None:
        known = sorted(MonsterPlugin._PLUGIN_REGISTRY.keys())
        raise SystemExit(
            f"Unknown monster '{stem}'. Known: {', '.join(known)}"
        )
    return cls()


def _apply_body_damage(victim: Creature, result) -> None:
    """Mirror Game.do_combat's body-HP subtract post-resolve."""
    if not result or result.num_hits == 0 or victim.is_dead():
        return
    defense = victim.get_defense()
    final = max(result.num_hits, result.body_damage_total - defense)
    victim.apply_damage(final)


def _newly_destroyed_parts(
    victim: Creature, previously_destroyed: set
) -> List[str]:
    """Return names of parts that went alive→destroyed since the
    last snapshot."""
    out: List[str] = []
    for part in getattr(victim, "body_parts", []) or []:
        if part.is_destroyed() and part.name not in previously_destroyed:
            out.append(part.name)
            previously_destroyed.add(part.name)
    return out


def _run_one_trial(
    player: Player,
    monster,
    target_part: Optional[str],
    rounds_cap: int,
) -> TrialOutcome:
    """One seeded fight. Player acts first each round; monster
    retaliates via attack_random if still alive. Returns outcome."""
    start_player_hp = player.health
    start_monster_hp = monster.health
    destroyed = set()
    critical_kill = False

    for r in range(1, rounds_cap + 1):
        # Player block
        actions = player.pick_actions()
        if not actions:
            # Both arms useless / no equippable — stalemate on player side
            if monster.is_dead():
                break
            return TrialOutcome(
                winner="stalemate", rounds=r,
                damage_dealt=start_monster_hp - monster.health,
                damage_received=start_player_hp - player.health,
                critical_part_kill=critical_kill,
                destroyed_parts=sorted(destroyed),
            )

        # Build assignments — tuple-form for explicit part targeting.
        if target_part:
            from caldanai.lib.rpg.combat.block import Assignment
            parts = monster.find_parts(target_part)
            if parts:
                assignments = [
                    Assignment(source=src, target=(monster, parts[0]))
                    for src in actions
                ]
            else:
                assignments = player.pick_targets(actions, [monster])
        else:
            assignments = player.pick_targets(actions, [monster])

        results = player.resolve(assignments)
        # Capture critical-part signal BEFORE body-HP apply (apply
        # might push monster to is_dead via part zeroing side).
        if results.any_critical_part_kill:
            critical_kill = True
        for victim, res in (results.per_victim or {}).items():
            _apply_body_damage(victim, res)
            destroyed.update(_newly_destroyed_parts(victim, destroyed))

        if monster.is_dead():
            return TrialOutcome(
                winner="player", rounds=r,
                damage_dealt=start_monster_hp - max(monster.health, 0),
                damage_received=start_player_hp - max(player.health, 0),
                critical_part_kill=critical_kill,
                destroyed_parts=sorted(destroyed),
            )

        # Monster retaliation via real pipeline (6b / 6c override chain).
        monster.attack_random([player])
        destroyed.update(_newly_destroyed_parts(player, destroyed))
        if player.is_dead():
            return TrialOutcome(
                winner="monster", rounds=r,
                damage_dealt=start_monster_hp - max(monster.health, 0),
                damage_received=start_player_hp - max(player.health, 0),
                critical_part_kill=critical_kill,
                destroyed_parts=sorted(destroyed),
            )

    return TrialOutcome(
        winner="stalemate", rounds=rounds_cap,
        damage_dealt=start_monster_hp - max(monster.health, 0),
        damage_received=start_player_hp - max(player.health, 0),
        critical_part_kill=critical_kill,
        destroyed_parts=sorted(destroyed),
    )


def _summarize(outcomes: List[TrialOutcome], header: str) -> None:
    total = len(outcomes)
    wins = [o for o in outcomes if o.winner == "player"]
    losses = [o for o in outcomes if o.winner == "monster"]
    stales = [o for o in outcomes if o.winner == "stalemate"]
    crit_kills = sum(1 for o in outcomes if o.critical_part_kill)

    print(f"# {header}")
    print(f"  trials: {total}")
    print(
        f"  outcomes: player_wins={len(wins)} "
        f"monster_wins={len(losses)} stalemates={len(stales)} "
        f"(player_win_rate={len(wins) / total:.0%})"
    )
    if wins:
        print(
            f"  player-win rounds: min={min(o.rounds for o in wins)} "
            f"max={max(o.rounds for o in wins)} "
            f"mean={statistics.mean(o.rounds for o in wins):.1f}"
        )
    if losses:
        print(
            f"  monster-win rounds: min={min(o.rounds for o in losses)} "
            f"max={max(o.rounds for o in losses)} "
            f"mean={statistics.mean(o.rounds for o in losses):.1f}"
        )
    print(
        f"  critical-part kills: {crit_kills}/{total} "
        f"({crit_kills / total:.0%})"
    )
    if wins:
        avg_dealt = statistics.mean(o.damage_dealt for o in wins)
        print(f"  avg damage dealt (wins):      {avg_dealt:.1f}")
    if losses:
        avg_taken = statistics.mean(o.damage_received for o in losses)
        print(f"  avg damage received (losses): {avg_taken:.1f}")
    # Top destroyed parts across all trials.
    all_parts = Counter()
    for o in outcomes:
        all_parts.update(o.destroyed_parts)
    if all_parts:
        top = ", ".join(f"{n} x{c}" for n, c in all_parts.most_common(6))
        print(f"  parts destroyed (top 6): {top}")
    print()


def _run_sweep_scenarios(
    monster_stem: str,
    quality: Qualities,
    trials: int,
    rounds_cap: int,
    player_hp: int,
    player_defense: int,
    player_dodge: int,
) -> List[dict]:
    """Iterate all 1H x 1H combos + 2H solos across skill [0, 10, 20]
    and strategy [None, 'head', 'torso'], running ``trials`` per
    scenario against ``monster_stem``. Returns a flat list of
    per-scenario result dicts for the renderer."""
    one_h, two_h = _classify_weapons()
    # Symmetric pairs (main + offhand) including same-weapon pairs —
    # deduplicate so mace+shortsword and shortsword+mace aren't both
    # rendered (outcome is symmetric in the duel harness).
    pairs: List[Tuple[str, Optional[str]]] = []
    for i, a in enumerate(one_h):
        for b in one_h[i:]:
            pairs.append((a, b))
    for th in two_h:
        pairs.append((th, None))

    skills = [0, 10, 20]
    strategies = [None, "head", "torso"]
    results: List[dict] = []

    for main, offhand in pairs:
        for skill in skills:
            row: dict = {
                "main": main,
                "offhand": offhand,
                "skill": skill,
                "strategies": {},
            }
            for strat in strategies:
                outcomes: List[TrialOutcome] = []
                for _ in range(trials):
                    player = _build_player(
                        name="Harness",
                        hp=player_hp,
                        defense=player_defense,
                        dodge=player_dodge,
                        weapon=main,
                        offhand=offhand,
                        quality=quality,
                        skill_level=skill,
                    )
                    monster = _spawn_monster(monster_stem)
                    outcomes.append(_run_one_trial(
                        player, monster,
                        target_part=strat,
                        rounds_cap=rounds_cap,
                    ))
                wins = [o for o in outcomes if o.winner == "player"]
                row["strategies"][strat or "none"] = {
                    "win_rate": len(wins) / trials,
                    "avg_win_rounds": (
                        statistics.mean(o.rounds for o in wins)
                        if wins else None
                    ),
                    "crit_rate": sum(
                        1 for o in outcomes if o.critical_part_kill
                    ) / trials,
                }
            results.append(row)
    return results


def _format_sweep_cell(data: dict) -> str:
    rate = data["win_rate"]
    rounds = data["avg_win_rounds"]
    crit = data["crit_rate"]
    rate_s = f"{int(rate * 100):>3}%"
    rounds_s = f"r{rounds:>4.1f}" if rounds is not None else "r   -"
    crit_s = f"c{int(crit * 100):>3}%"
    return f"{rate_s} {rounds_s} {crit_s}"


def _compute_monster_summary(rows: List[dict]) -> dict:
    """Distill a sweep into the per-monster tuning view: best/median
    win% per strategy per skill, plus the 'torso exploit gap' (max
    per-loadout difference between torso-target and no-target win%)."""
    skills = sorted({r["skill"] for r in rows})
    out = {"per_skill": {}, "max_exploit_gap": 0.0}
    for skill in skills:
        matching = [r for r in rows if r["skill"] == skill]
        per_strat = {}
        for strat in ("none", "head", "torso"):
            rates = [r["strategies"][strat]["win_rate"] for r in matching]
            per_strat[strat] = {
                "best": max(rates) if rates else 0.0,
                "median": statistics.median(rates) if rates else 0.0,
                "worst": min(rates) if rates else 0.0,
            }
        out["per_skill"][skill] = per_strat
        # Exploit gap — for each loadout, torso_win - no_target_win.
        for r in matching:
            gap = (
                r["strategies"]["torso"]["win_rate"]
                - r["strategies"]["none"]["win_rate"]
            )
            if gap > out["max_exploit_gap"]:
                out["max_exploit_gap"] = gap
    return out


def _collect_monster_header(stem: str) -> Optional[str]:
    """Return the one-line monster stat readout string (None on unknown).

    Split out from ``_print_monster_header`` so the parallel sweep
    worker can compute the header inside a subprocess (where the
    monster instance lives) and return a string the parent prints
    in input order.
    """
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(stem)
    if cls is None:
        return None
    m = cls()
    size = getattr(m, "size", "?")
    torso_hp = None
    head_hp = None
    for part in getattr(m, "body_parts", []) or []:
        if part.name.startswith("torso"):
            torso_hp = part.health_max
        if part.name.startswith("head"):
            if head_hp is None or part.health_max > head_hp:
                head_hp = part.health_max
    return (
        f"[{stem}] size={size.name if hasattr(size, 'name') else size} "
        f"body_hp={m.health_max} def={m.get_defense()} dodge={m.get_dodge()} "
        f"torso_hp={torso_hp} head_hp={head_hp}"
    )


def _print_monster_header(stem: str) -> None:
    """One-line monster stat readout for the sweep header."""
    header = _collect_monster_header(stem)
    if header is None:
        print(f"[{stem}: unknown monster — skipping]")
    else:
        print(header)


def _sweep_monster_worker(
    stem: str,
    quality_name: str,
    trials: int,
    rounds_cap: int,
    player_hp: int,
    player_defense: int,
    player_dodge: int,
    depth_coef: "int | None" = None,
) -> dict:
    """Multiprocessing worker: sweep one monster end-to-end.

    Runs in a subprocess because each sweep is CPU-bound on Python
    dice / combat arithmetic. Re-establishes the
    ``Dispatcher`` / ``DB`` patches inside the child so hook side
    effects don't reach Discord / Mongo from the worker. Returns a
    dict the parent can print in input order (header, rows, summary).
    ``quality_name`` is the enum name rather than the instance — the
    enum isn't guaranteed to round-trip cleanly through the
    multiprocessing pickle boundary on every Python build.

    ``depth_coef`` is passed explicitly because each subprocess
    re-imports the creatures module with its default value —
    mutating the parent's module object doesn't propagate.
    """
    quality = Qualities[quality_name]
    if depth_coef is not None:
        from caldanai.lib.rpg import creatures as _creatures_module
        _creatures_module.DEPTH_COEFFICIENT = depth_coef
    with (
        patch("caldanai.dispatcher.Dispatcher"),
        patch("caldanai.lib.rpg.Dispatcher"),
        patch("caldanai.lib.rpg.creatures.DB", create=True),
    ):
        header = _collect_monster_header(stem)
        rows = _run_sweep_scenarios(
            monster_stem=stem,
            quality=quality,
            trials=trials,
            rounds_cap=rounds_cap,
            player_hp=player_hp,
            player_defense=player_defense,
            player_dodge=player_dodge,
        )
        summary = _compute_monster_summary(rows)
    return {"stem": stem, "header": header, "rows": rows, "summary": summary}


def _print_monster_summary(stem: str, summary: dict) -> None:
    """Compact per-skill win-rate summary for one monster."""
    print(f"  +- win rates (best across all loadouts) -----")
    for skill, per_strat in summary["per_skill"].items():
        print(
            f"  | skill {skill:>2}  "
            f"no-target:{per_strat['none']['best']:>5.0%}  "
            f"head:{per_strat['head']['best']:>5.0%}  "
            f"torso:{per_strat['torso']['best']:>5.0%}"
        )
    gap = summary["max_exploit_gap"]
    tag = (
        "TRIVIALIZED by torso" if gap >= 0.80
        else "major torso exploit" if gap >= 0.50
        else "moderate torso exploit" if gap >= 0.25
        else "balanced"
    )
    print(f"  +- max torso-target exploit gap: {gap:>5.0%}  [{tag}]")


def _print_sweep(
    monster: str, quality: Qualities, trials: int, rows: List[dict],
) -> None:
    """Render one compact table per skill level. Cell format:
    ``WW% rRR.R cCC%`` — win rate, mean rounds-to-win, crit rate."""
    skills = sorted({r["skill"] for r in rows})
    header_note = (
        f"win% rounds-to-win crit% — per strategy; "
        f"{trials} trials/scenario, seed 0"
    )
    for skill in skills:
        print(f"\n=== vs {monster}, {quality.name}, skill {skill} ===")
        print(f"  ({header_note})")
        print(
            f"  {'loadout':<28} | {'no-target':<16} | "
            f"{'head-tgt':<16} | {'torso-tgt':<16}"
        )
        print("  " + "-" * 82)
        matching = [r for r in rows if r["skill"] == skill]
        # Sort by torso win rate descending so the most exploitable
        # loadouts rise to the top — the user's balance question.
        matching.sort(
            key=lambda r: r["strategies"]["torso"]["win_rate"],
            reverse=True,
        )
        for r in matching:
            if r["offhand"] is None:
                label = f"{r['main']} (2H)"
            else:
                label = f"{r['main']} + {r['offhand']}"
            cells = " | ".join(
                _format_sweep_cell(r["strategies"][s])
                for s in ["none", "head", "torso"]
            )
            print(f"  {label:<28} | {cells}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--weapon", default=None,
                    help="Main-hand weapon stem (e.g. 'mace'). "
                         "Omit for unarmed.")
    ap.add_argument("--offhand", default=None,
                    help="Offhand weapon stem for dual-wield.")
    ap.add_argument("--quality", default="ORDINARY",
                    choices=[q.name for q in Qualities],
                    help="Weapon quality tier.")
    ap.add_argument("--skill", type=int, default=10,
                    help="Weapon skill level (0-20).")
    # Defaults match the live Player(...) constructor defaults
    # in caldanai/lib/rpg/creatures/player.py (hp/def/dodge 20/6/6).
    # Live gear routinely lifts dodge to 16-18 via armor bonuses;
    # these are the pre-gear baseline a fresh player starts with.
    ap.add_argument("--player-hp", type=int, default=20,
                    help="Player HP (default 20 — live Player init).")
    ap.add_argument("--player-defense", type=int, default=6,
                    help="Player base defense (default 6 — live Player init).")
    ap.add_argument("--player-dodge", type=int, default=6,
                    help="Player base dodge (default 6 — live Player init).")
    ap.add_argument("--player-name", default="Harness",
                    help="Player name (default 'Harness').")
    ap.add_argument("--monster", default=None,
                    help="Monster stem (goblin / bandit / hydra / etc.). "
                         "Required for single-monster and --sweep modes; "
                         "omit when using --sweep-monsters.")
    ap.add_argument("--target-part", default=None,
                    help="Aim every swing at this part (fuzzy-matched via "
                         "monster.find_parts). Exercises the critical-"
                         "part-kill path.")
    ap.add_argument("--trials", type=int, default=100,
                    help="Trial count (default 100).")
    ap.add_argument("--sweep", action="store_true",
                    help="Sweep all 1H dual-wield combos + 2H solos × "
                         "skill [0, 10, 20] × strategy [none, head, "
                         "torso] against --monster. Requires --monster. "
                         "Ignores --weapon / --offhand / --skill / "
                         "--target-part. Use --quality to pin a tier "
                         "(default MASTERWORK in sweep).")
    ap.add_argument("--sweep-trials", type=int, default=25,
                    help="Trials per scenario inside --sweep (default "
                         "25 — kept low since the sweep covers many "
                         "scenarios).")
    ap.add_argument("--sweep-monsters", default=None,
                    help="Comma-separated monster stems to sweep back-"
                         "to-back (alternative to --monster + --sweep). "
                         "Prints a condensed per-monster summary plus a "
                         "cross-monster tuning chart at the end.")
    ap.add_argument("--verbose-sweep", action="store_true",
                    help="When used with --sweep-monsters, also print "
                         "the full per-skill loadout table per monster "
                         "(otherwise only the summary lines).")
    ap.add_argument("--rounds", type=int, default=50,
                    help="Max rounds per trial (default 50).")
    ap.add_argument("--seed", type=int, default=0,
                    help="RNG seed (default 0).")
    ap.add_argument("--depth-coef", type=int, default=None,
                    help="Override DEPTH_COEFFICIENT for the depth-walk "
                         "resolver (default = module value, currently 1).")
    args = ap.parse_args(argv)

    random.seed(args.seed)

    if not args.monster and not args.sweep_monsters:
        ap.error("either --monster or --sweep-monsters is required")

    if args.depth_coef is not None:
        from caldanai.lib.rpg import creatures as _creatures_module
        _creatures_module.DEPTH_COEFFICIENT = args.depth_coef

    # Sweep modes default quality to MASTERWORK if user didn't
    # override, since the sweep's job is "what's possible at best gear."
    sweeping = args.sweep or args.sweep_monsters
    if sweeping and args.quality == "ORDINARY":
        quality = Qualities.MASTERWORK
    else:
        quality = Qualities[args.quality]

    # Patch Dispatcher + DB so hook side effects don't reach Discord or Mongo.
    with (
        patch("caldanai.dispatcher.Dispatcher"),
        patch("caldanai.lib.rpg.Dispatcher"),
        patch("caldanai.lib.rpg.creatures.DB", create=True),
    ):
        if args.sweep_monsters:
            stems = [s.strip() for s in args.sweep_monsters.split(",")]
            summaries = []
            # Parallelize per-monster sweeps. Each monster is an
            # independent CPU-bound run, so ProcessPoolExecutor (with
            # default workers = os.cpu_count()) gives ~N× speedup where
            # N = min(len(stems), cpus). Results are collected in input
            # order before printing so the per-monster block ordering
            # matches the command line.
            max_workers = min(len(stems), os.cpu_count() or 1)
            with ProcessPoolExecutor(max_workers=max_workers) as pool:
                futures = [
                    pool.submit(
                        _sweep_monster_worker,
                        stem,
                        quality.name,
                        args.sweep_trials,
                        args.rounds,
                        args.player_hp,
                        args.player_defense,
                        args.player_dodge,
                        args.depth_coef,
                    )
                    for stem in stems
                ]
                worker_results = [f.result() for f in futures]
            for result in worker_results:
                stem = result["stem"]
                print(f"\n\n==== {stem.upper()} ====")
                if result["header"] is None:
                    print(f"[{stem}: unknown monster — skipping]")
                    continue
                print(result["header"])
                _print_monster_summary(stem, result["summary"])
                if args.verbose_sweep:
                    _print_sweep(
                        stem, quality, args.sweep_trials, result["rows"],
                    )
                summaries.append((stem, result["summary"]))
            # Cross-monster chart
            print("\n\n==== CROSS-MONSTER TUNING CHART ====")
            print(
                f"  ({args.sweep_trials} trials/scenario, "
                f"{quality.name} gear, player hp={args.player_hp} "
                f"def={args.player_defense} dodge={args.player_dodge})\n"
            )
            print(
                f"  {'monster':<14} | {'skill-20 no-tgt':<16} | "
                f"{'skill-20 head':<14} | {'skill-20 torso':<15} | "
                f"{'exploit gap':<12}"
            )
            print("  " + "-" * 80)
            for stem, s in summaries:
                ps20 = s["per_skill"].get(20, {})
                def _b(k):
                    return f"{ps20.get(k, {}).get('best', 0):>5.0%}"
                gap = s["max_exploit_gap"]
                tag = (
                    "TRIVIAL" if gap >= 0.80
                    else "major" if gap >= 0.50
                    else "moderate" if gap >= 0.25
                    else "OK"
                )
                print(
                    f"  {stem:<14} | best={_b('none'):<11} "
                    f"| best={_b('head'):<9} "
                    f"| best={_b('torso'):<10} "
                    f"| {gap:>5.0%} [{tag}]"
                )
            return 0

        if args.sweep:
            rows = _run_sweep_scenarios(
                monster_stem=args.monster,
                quality=quality,
                trials=args.sweep_trials,
                rounds_cap=args.rounds,
                player_hp=args.player_hp,
                player_defense=args.player_defense,
                player_dodge=args.player_dodge,
            )
            _print_sweep(args.monster, quality, args.sweep_trials, rows)
            return 0

        outcomes: List[TrialOutcome] = []
        for trial in range(args.trials):
            player = _build_player(
                name=args.player_name,
                hp=args.player_hp,
                defense=args.player_defense,
                dodge=args.player_dodge,
                weapon=args.weapon,
                offhand=args.offhand,
                quality=quality,
                skill_level=args.skill,
            )
            monster = _spawn_monster(args.monster)
            outcome = _run_one_trial(
                player, monster,
                target_part=args.target_part,
                rounds_cap=args.rounds,
            )
            outcomes.append(outcome)

    loadout = args.weapon or "unarmed"
    if args.offhand:
        loadout += f" + {args.offhand}"
    if args.target_part:
        loadout += f" -> {args.target_part}"
    header = (
        f"{args.player_name} ({loadout}, {args.quality} skill-{args.skill}, "
        f"hp={args.player_hp} def={args.player_defense} "
        f"dodge={args.player_dodge}) vs {args.monster}"
    )
    _summarize(outcomes, header)
    return 0


if __name__ == "__main__":
    sys.exit(main())
