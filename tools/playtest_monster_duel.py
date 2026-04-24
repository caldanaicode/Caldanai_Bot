"""Monster-vs-monster duel harness.

The existing ``playtest_combat_harness`` is Player-oriented
(attacker uses ``pick_actions`` / ``pick_targets`` / ``resolve``
— the Player pipeline). For size-aware-targeting work we need
to watch monster-vs-monster interactions where one plugin plays
the "player" role — e.g. pixie-stabbing-dragon to confirm the
bias formula actually tilts the pixie's aim at the dragon's
small parts.

Both sides here call ``attack_random`` and alternate turns. The
key signal is the **target-part distribution**: which parts
each attacker aimed at across all rounds. For a pixie-vs-dragon
fight we want eye / head / wing (small, exposed) picks >>
torso; for dragon-vs-pixie we expect the opposite (torso
dominates, tiny parts rarely picked).

Usage::

    # Pixie-vs-dragon: TINY vs HUGE, ratio 0.5 (bias toward
    # small parts on the pixie's side, no collapse).
    python -m tools.playtest_monster_duel \\
        --attacker pixie --defender dragon --trials 50

    # Dragon-vs-pixie: HUGE vs TINY, ratio 3.5 (collapse fires
    # on every swing — eyes resolve on head, head resolves on
    # torso).
    python -m tools.playtest_monster_duel \\
        --attacker dragon --defender pixie --trials 50

    # Baseline: goblin-vs-bandit, same SMALL-vs-MEDIUM tier.
    python -m tools.playtest_monster_duel \\
        --attacker goblin --defender bandit --trials 100

The report: attacker aim distribution (pre- and post-collapse),
defender aim distribution (same), win rate, avg rounds to
resolution, destroyed parts. Writes to stdout.

Why a new tool instead of extending the Player harness:
``attack_random`` composes the monster pipeline end-to-end and
returns a rendered string — substituting a monster for the
"player" in the existing harness would mean disabling most of
its Player-specific reporting. Clean two-tool split keeps each
harness focused.
"""

from __future__ import annotations

import argparse
import random
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from caldanai.lib.rpg import creatures as creatures_module
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin


#: Default player loadout — shortsword (melee) + wand (ranged)
#: as a dual-wield. Matches what a realistic test-bot player
#: would be carrying at the time of the size-aware + B3/B4
#: design work. Override via ``--player-weapon`` /
#: ``--player-offhand``.
_DEFAULT_PLAYER_MAIN: str = "shortsword"
_DEFAULT_PLAYER_OFFHAND: str = "wand"
_DEFAULT_PLAYER_QUALITY: str = "ORDINARY"
_DEFAULT_PLAYER_SKILL: int = 10  # mid-level competence


def _instantiate_weapon(stem: str, quality_name: str):
    """Import a weapon plugin by stem and construct one instance
    at the given quality. Mirrors the helper in
    :mod:`tools.playtest_combat_harness` — duplicated here rather
    than shared to keep the two tools independently importable
    (avoids circular import chains through the harness when it
    grows further)."""
    import importlib
    from caldanai.lib.rpg.helpers.enums import Qualities

    module = importlib.import_module(
        f"caldanai.lib.rpg.inventory.equipment.weapons.{stem}"
    )
    return module.WeaponPlugin(
        iid=None, quality=Qualities[quality_name], bonus=None,
    )


def _build_player(
    main_weapon: str = _DEFAULT_PLAYER_MAIN,
    offhand_weapon: Optional[str] = _DEFAULT_PLAYER_OFFHAND,
    quality_name: str = _DEFAULT_PLAYER_QUALITY,
    skill_level: int = _DEFAULT_PLAYER_SKILL,
) -> "Creature":
    """Construct a fresh headless Player for duel participation.

    Dual-wields by default (shortsword + wand) so both melee and
    ranged attack-source paths are exercised. Skill-seeded at
    level 10 so hit rates reflect a real combatant rather than
    a fumbling rookie. Caller may swap weapons via the kwargs
    but the defaults mirror the typical test-bot loadout.
    """
    from unittest.mock import MagicMock
    from caldanai.lib.rpg.creatures.player import Player
    from caldanai.lib.rpg.helpers.enums import EquipmentSlots

    p = Player(
        pid=1, gid=1, uid=1,
        health=20, health_max=20,
        defense=3, dodge=5,
        gender="female", pronouns="she,her,hers,her",
        weight_limit=100, clarks=0,
    )
    p.name = "Duelist"
    p.member = MagicMock()
    p.member.id = 1
    p.member.roles = []

    if skill_level > 0:
        main = _instantiate_weapon(main_weapon, quality_name)
        p.skills[main.skill] = max(skill_level * 1000, 100)
        if offhand_weapon:
            off_preview = _instantiate_weapon(offhand_weapon, quality_name)
            if off_preview.skill not in p.skills:
                p.skills[off_preview.skill] = max(skill_level * 1000, 100)

    main_w = _instantiate_weapon(main_weapon, quality_name)
    if EquipmentSlots.MULTI_SLOT & main_w.slots:
        # Two-handed weapon — shares the same instance across
        # both arms. Ignore offhand in that case.
        p.place("hand.left", "held", main_w)
        p.place("hand.right", "held", main_w)
    else:
        p.place("hand.left", "held", main_w)
        if offhand_weapon:
            off_w = _instantiate_weapon(offhand_weapon, quality_name)
            if not (EquipmentSlots.MULTI_SLOT & off_w.slots):
                p.place("hand.right", "held", off_w)

    return p


def _is_player(creature) -> bool:
    """Test if a combatant uses the Player attack pipeline
    rather than ``attack_random``. Cheap type check; importing
    Player at module scope bloats argparse --help."""
    from caldanai.lib.rpg.creatures.player import Player
    return isinstance(creature, Player)


def _apply_body_damage_from_resolution(victim, resolution) -> None:
    """Mirror of the ``Game.do_combat`` post-resolve body-HP
    subtract for the Player-side attack path. ``Player.resolve``
    routes per-part damage during the stage itself; the body-HP
    floor needs a separate step (pre-B1 contract the harness
    captured and kept)."""
    if not resolution or resolution.num_hits == 0 or victim.is_dead():
        return
    defense = victim.get_defense()
    final = max(resolution.num_hits, resolution.body_damage_total - defense)
    victim.apply_damage(final)


@dataclass
class DuelOutcome:
    winner: str  # "attacker" | "defender" | "stalemate"
    rounds: int
    attacker_final_hp: int
    defender_final_hp: int
    attacker_aim_pre: Counter = field(default_factory=Counter)
    attacker_aim_post: Counter = field(default_factory=Counter)
    defender_aim_pre: Counter = field(default_factory=Counter)
    defender_aim_post: Counter = field(default_factory=Counter)
    destroyed_parts: Dict[str, List[str]] = field(default_factory=dict)


def _spawn(stem: str, **player_kwargs):
    """Build a combatant from a stem string. ``"player"`` yields
    a minimally-equipped Player (dual-wield shortsword + wand by
    default; kwargs override via ``_build_player``); any other
    stem resolves through the MonsterPlugin registry."""
    if stem == "player":
        return _build_player(**player_kwargs)
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(stem)
    if cls is None:
        known = sorted(MonsterPlugin._PLUGIN_REGISTRY.keys())
        raise SystemExit(
            f"Unknown combatant '{stem}'. Pass 'player' or one of: "
            f"{', '.join(known)}"
        )
    return cls()


def _attack_turn(attacker, defender) -> None:
    """Dispatch one attack turn using the right pipeline for
    each side. Monsters attack via ``attack_random`` (which
    internally applies body-HP damage); players go through
    ``pick_actions`` / ``pick_targets`` / ``resolve`` and the
    harness applies body-HP damage after."""
    if _is_player(attacker):
        actions = attacker.pick_actions()
        if not actions:
            return
        assignments = attacker.pick_targets(actions, [defender])
        if not assignments:
            return
        results = attacker.resolve(assignments)
        for victim, res in (results.per_victim or {}).items():
            _apply_body_damage_from_resolution(victim, res)
    else:
        attacker.attack_random([defender])


class _AimRecorder:
    """Patches ``pick_random_part`` and ``_collapse_to_region``
    at module scope to record every targeting decision, scoped
    to an attacker-vs-defender pair.

    The recording is keyed by ``id(defender)`` so we can tell
    which creature was being targeted at each call site — the
    resolver walks defender.get_targetable_parts(), so the first
    positional argument to pick_random_part identifies the
    defender (via ``id(parts[0].owner)`` would work if parts
    remembered their owner; instead we seed ``_active_defender``
    explicitly around each attack_random call).
    """

    def __init__(self) -> None:
        self._active_defender_id: Optional[int] = None
        # {defender_id: (pre_collapse Counter, post_collapse Counter)}
        self.buckets: Dict[int, "tuple[Counter, Counter]"] = defaultdict(
            lambda: (Counter(), Counter())
        )
        # Inner state: a stashed (part, ratio) captured by the
        # pick wrapper, consumed by the collapse wrapper so the
        # two records stay paired across a single targeting
        # decision.
        self._last_pick = None

        self._orig_pick = creatures_module.pick_random_part
        self._orig_collapse = creatures_module._collapse_to_region

    def bind_defender(self, defender: Creature) -> None:
        self._active_defender_id = id(defender)

    def unbind(self) -> None:
        self._active_defender_id = None

    def install(self) -> None:
        rec = self

        def pick_wrapper(parts, reach, attacker_scale=1.0, target_scale=1.0):
            picked = rec._orig_pick(parts, reach, attacker_scale, target_scale)
            if picked is not None and rec._active_defender_id is not None:
                pre_counter, _ = rec.buckets[rec._active_defender_id]
                pre_counter[picked.name] += 1
                # Stash for the collapse wrapper to pick up.
                rec._last_pick = picked.name
            return picked

        def collapse_wrapper(part, ratio):
            final = rec._orig_collapse(part, ratio)
            if rec._active_defender_id is not None and rec._last_pick is not None:
                _, post_counter = rec.buckets[rec._active_defender_id]
                post_counter[final.name] += 1
                rec._last_pick = None
            return final

        creatures_module.pick_random_part = pick_wrapper
        creatures_module._collapse_to_region = collapse_wrapper

    def restore(self) -> None:
        creatures_module.pick_random_part = self._orig_pick
        creatures_module._collapse_to_region = self._orig_collapse


def _run_one_duel(
    attacker_stem: str,
    defender_stem: str,
    rounds_cap: int,
    recorder: _AimRecorder,
    player_kwargs: Optional[Dict] = None,
) -> DuelOutcome:
    pkw = player_kwargs or {}
    attacker = _spawn(attacker_stem, **pkw) if attacker_stem == "player" else _spawn(attacker_stem)
    defender = _spawn(defender_stem, **pkw) if defender_stem == "player" else _spawn(defender_stem)

    # Fresh per-duel aim buckets for these specific IDs.
    recorder.buckets.pop(id(attacker), None)
    recorder.buckets.pop(id(defender), None)

    destroyed: Dict[str, List[str]] = {"attacker": [], "defender": []}

    def _snapshot_destroyed(creature: Creature, bucket: List[str]) -> None:
        for part in getattr(creature, "body_parts", []) or []:
            if part.is_destroyed() and part.name not in bucket:
                bucket.append(part.name)

    for r in range(1, rounds_cap + 1):
        if attacker.is_dead() or defender.is_dead():
            break

        # Attacker phase — defender is the victim.
        recorder.bind_defender(defender)
        try:
            _attack_turn(attacker, defender)
        finally:
            recorder.unbind()
        _snapshot_destroyed(defender, destroyed["defender"])
        if defender.is_dead():
            break

        # Defender phase — attacker is the victim (retaliation).
        recorder.bind_defender(attacker)
        try:
            _attack_turn(defender, attacker)
        finally:
            recorder.unbind()
        _snapshot_destroyed(attacker, destroyed["attacker"])
        if attacker.is_dead():
            break

    if attacker.is_dead() and not defender.is_dead():
        winner = "defender"
    elif defender.is_dead() and not attacker.is_dead():
        winner = "attacker"
    elif attacker.is_dead() and defender.is_dead():
        # Mutual kill in the same round — pre-existing contract:
        # call it "attacker" since they swing first.
        winner = "attacker"
    else:
        winner = "stalemate"

    atk_pre, atk_post = recorder.buckets.get(id(defender), (Counter(), Counter()))
    def_pre, def_post = recorder.buckets.get(id(attacker), (Counter(), Counter()))

    return DuelOutcome(
        winner=winner,
        rounds=r,
        attacker_final_hp=max(attacker.health, 0),
        defender_final_hp=max(defender.health, 0),
        attacker_aim_pre=Counter(atk_pre),
        attacker_aim_post=Counter(atk_post),
        defender_aim_pre=Counter(def_pre),
        defender_aim_post=Counter(def_post),
        destroyed_parts={k: list(v) for k, v in destroyed.items()},
    )


def _render_distribution(counter: Counter, total_label: str) -> str:
    if not counter:
        return f"  {total_label}: (no picks recorded)"
    total = sum(counter.values())
    lines = [f"  {total_label} (n={total}):"]
    for name, count in counter.most_common():
        pct = count / total * 100
        lines.append(f"    {name:<20} {count:>5} ({pct:5.1f}%)")
    return "\n".join(lines)


def _summarize_duels(
    outcomes: List[DuelOutcome],
    attacker_stem: str,
    defender_stem: str,
) -> None:
    total = len(outcomes)
    atk_wins = sum(1 for o in outcomes if o.winner == "attacker")
    def_wins = sum(1 for o in outcomes if o.winner == "defender")
    stales = sum(1 for o in outcomes if o.winner == "stalemate")
    avg_rounds = sum(o.rounds for o in outcomes) / total if total else 0

    print(f"# Monster duel: {attacker_stem} (attacker) vs {defender_stem} (defender)")
    print(f"  trials: {total}")
    print(
        f"  outcomes: attacker_wins={atk_wins} "
        f"defender_wins={def_wins} stalemates={stales} "
        f"(attacker_win_rate={atk_wins / total:.0%})"
    )
    print(f"  avg_rounds: {avg_rounds:.1f}")

    # Aggregate aim distributions across all trials.
    atk_pre_all = Counter()
    atk_post_all = Counter()
    def_pre_all = Counter()
    def_post_all = Counter()
    for o in outcomes:
        atk_pre_all.update(o.attacker_aim_pre)
        atk_post_all.update(o.attacker_aim_post)
        def_pre_all.update(o.defender_aim_pre)
        def_post_all.update(o.defender_aim_post)

    print(f"\n## {attacker_stem} targeting {defender_stem}")
    print(_render_distribution(atk_pre_all, "pre-collapse aim"))
    if atk_pre_all != atk_post_all:
        print(_render_distribution(atk_post_all, "post-collapse landing"))
    else:
        print("  (region-collapse inactive — no ratio-gap exceeded threshold)")

    print(f"\n## {defender_stem} targeting {attacker_stem}")
    print(_render_distribution(def_pre_all, "pre-collapse aim"))
    if def_pre_all != def_post_all:
        print(_render_distribution(def_post_all, "post-collapse landing"))
    else:
        print("  (region-collapse inactive — no ratio-gap exceeded threshold)")


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Monster-vs-monster (or monster-vs-player) duel harness.",
    )
    ap.add_argument(
        "--attacker", required=True,
        help=(
            "Combatant acting first each round. Pass a monster stem "
            "(e.g. 'pixie') OR 'player' for a headless Player with the "
            "default loadout."
        ),
    )
    ap.add_argument(
        "--defender", required=True,
        help="Combatant retaliating each round. Same options as --attacker.",
    )
    ap.add_argument("--trials", type=int, default=50)
    ap.add_argument("--rounds", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument(
        "--player-weapon", default=_DEFAULT_PLAYER_MAIN,
        help=(
            "Main-hand weapon stem for any 'player' combatant. "
            f"Default '{_DEFAULT_PLAYER_MAIN}'."
        ),
    )
    ap.add_argument(
        "--player-offhand", default=_DEFAULT_PLAYER_OFFHAND,
        help=(
            "Offhand weapon stem for any 'player' combatant. "
            f"Default '{_DEFAULT_PLAYER_OFFHAND}'. Pass empty string to "
            "disable offhand and go one-handed."
        ),
    )
    ap.add_argument(
        "--player-quality", default=_DEFAULT_PLAYER_QUALITY,
        help=(
            "Weapon quality tier (JUNK / ORDINARY / FINE / QUALITY / "
            f"SUPERIOR / MASTERWORK). Default '{_DEFAULT_PLAYER_QUALITY}'."
        ),
    )
    ap.add_argument(
        "--player-skill", type=int, default=_DEFAULT_PLAYER_SKILL,
        help=(
            f"Weapon skill level (0-20). Default {_DEFAULT_PLAYER_SKILL}."
        ),
    )
    ap.add_argument(
        "--depth-coef", type=int, default=None,
        help=(
            "Override DEPTH_COEFFICIENT for the depth-walk resolver. "
            "Default reads module value (currently 1)."
        ),
    )
    return ap.parse_args()


def main() -> None:
    args = _parse_args()
    random.seed(args.seed)

    if args.depth_coef is not None:
        creatures_module.DEPTH_COEFFICIENT = args.depth_coef

    player_kwargs = {
        "main_weapon": args.player_weapon,
        "offhand_weapon": args.player_offhand or None,
        "quality_name": args.player_quality,
        "skill_level": args.player_skill,
    }

    recorder = _AimRecorder()
    recorder.install()
    try:
        outcomes = [
            _run_one_duel(
                args.attacker, args.defender, args.rounds,
                recorder, player_kwargs,
            )
            for _ in range(args.trials)
        ]
    finally:
        recorder.restore()

    _summarize_duels(outcomes, args.attacker, args.defender)


if __name__ == "__main__":
    main()
