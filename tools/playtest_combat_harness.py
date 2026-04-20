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
import random
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional
from unittest.mock import MagicMock, patch

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities


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

    # Equip slots.
    if weapon:
        w_main = _instantiate_weapon(weapon, quality)
        if EquipmentSlots.MULTI_SLOT & w_main.slots:
            p.equip_slots[EquipmentSlots.LEFT_HELD.name] = w_main
            p.equip_slots[EquipmentSlots.RIGHT_HELD.name] = w_main
        else:
            p.equip_slots[EquipmentSlots.LEFT_HELD.name] = w_main
            if offhand:
                w_off = _instantiate_weapon(offhand, quality)
                if EquipmentSlots.MULTI_SLOT & w_off.slots:
                    raise SystemExit(
                        f"Offhand weapon '{offhand}' is two-handed; "
                        "pick a one-handed offhand or omit --offhand."
                    )
                p.equip_slots[EquipmentSlots.RIGHT_HELD.name] = w_off
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
    ap.add_argument("--player-hp", type=int, default=20,
                    help="Player HP (default 20).")
    ap.add_argument("--player-defense", type=int, default=3,
                    help="Player defense (default 3).")
    ap.add_argument("--player-dodge", type=int, default=15,
                    help="Player dodge (default 15).")
    ap.add_argument("--player-name", default="Harness",
                    help="Player name (default 'Harness').")
    ap.add_argument("--monster", required=True,
                    help="Monster stem (goblin / bandit / hydra / etc.).")
    ap.add_argument("--target-part", default=None,
                    help="Aim every swing at this part (fuzzy-matched via "
                         "monster.find_parts). Exercises the critical-"
                         "part-kill path.")
    ap.add_argument("--trials", type=int, default=100,
                    help="Trial count (default 100).")
    ap.add_argument("--rounds", type=int, default=50,
                    help="Max rounds per trial (default 50).")
    ap.add_argument("--seed", type=int, default=0,
                    help="RNG seed (default 0).")
    args = ap.parse_args(argv)

    random.seed(args.seed)

    quality = Qualities[args.quality]
    # Patch Dispatcher + DB so hook side effects don't reach Discord or Mongo.
    with (
        patch("caldanai.dispatcher.Dispatcher"),
        patch("caldanai.lib.rpg.Dispatcher"),
        patch("caldanai.lib.rpg.creatures.DB", create=True),
    ):
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
