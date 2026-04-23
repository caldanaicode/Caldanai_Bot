"""Dump a creature's body tree with per-node mixin tags and
equipment placements — the B-arc sibling of
:mod:`tools.inspect_monster`, which reports stat-level info.

Where ``inspect_monster`` answers "what are this monster's
Q.6-scaled stats?", this tool answers "what is the shape of
this creature's body tree?" — useful for verifying Phase B1
materialization, Phase B2 mixin tagging, and Phase B3 per-node
equipment placements.

Usage::

    # Inspect a monster's body tree.
    python -m tools.inspect_body_tree dragon
    python -m tools.inspect_body_tree goblin bearowl hydra

    # Inspect a fresh default player's body tree (no equipment
    # — all placements will read as empty).
    python -m tools.inspect_body_tree player

Tree is printed with indentation reflecting parent → child
depth. Each node line shows:

- name
- plugin class
- mixin tags (Offensive / Sensory / Mobility / Defensive /
  Equippable), with per-mixin attribute values in parens where
  relevant (e.g. ``Mobility(airborne)``, ``Sensory(primary)``)
- placements dict when Equippable, with None values shown as
  ``·`` and populated values as ``item_name``

Why a dedicated tool: future phases (B4 emergence tree-walk,
Phase C dodge rework) will need to read this same picture
repeatedly during tuning. A reusable entry point beats
reconstructing the walk inline each time.
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import List, Optional

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.mixins import (
    Defensive, Equippable, Mobility, Offensive, Sensory,
)
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.node import Node


def _mixin_tags(node: Node) -> str:
    """Render the mixin tags this node carries, with attribute
    detail in parentheses for mixins that vary per plugin."""
    tags: List[str] = []
    if isinstance(node, Offensive):
        tags.append("Offensive")
    if isinstance(node, Sensory):
        mode = "primary" if node.IS_PRIMARY_SENSE else "fallback"
        tags.append(f"Sensory({mode})")
    if isinstance(node, Mobility):
        tags.append(f"Mobility({node.MOBILITY_MODE})")
    if isinstance(node, Defensive):
        tags.append("Defensive")
    if isinstance(node, Equippable):
        tags.append("Equippable")
    return " ".join(tags) if tags else "—"


def _placements_summary(node: Node) -> str:
    """Render an Equippable node's current placements dict.
    Returns an empty string for non-Equippable nodes."""
    if not isinstance(node, Equippable):
        return ""
    if not getattr(node, "placements", None):
        return "  placements={}"
    parts = []
    for key, item in node.placements.items():
        if item is None:
            parts.append(f"{key}=·")
        else:
            name = getattr(item, "name", None) or repr(item)
            parts.append(f"{key}={name}")
    return "  placements={" + ", ".join(parts) + "}"


def _render_tree(root: Optional[Node], indent: int = 0) -> List[str]:
    if root is None:
        return ["  (no body tree)"]
    lines: List[str] = []
    pad = "  " * indent
    cls = type(root).__name__
    tags = _mixin_tags(root)
    placements = _placements_summary(root)
    lines.append(f"{pad}- {root.name:<22} [{cls}]  {tags}{placements}")
    for child in root.children:
        lines.extend(_render_tree(child, indent + 1))
    return lines


def _build_creature(target: str) -> Creature:
    """Construct a fresh creature for inspection. ``target`` is
    either ``"player"`` (fresh default Player) or a monster
    plugin stem resolved via ``MonsterPlugin.get_plugin_class``.
    """
    if target == "player":
        # Avoid importing Player at module top — it pulls the
        # whole inventory / cogs chain, which bloats --help.
        from unittest.mock import MagicMock
        from caldanai.lib.rpg.creatures.player import Player

        p = Player(pid=1, gid=1, uid=1, health=20, health_max=20)
        p.name = "InspectSubject"
        p.member = MagicMock()
        return p

    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(target)
    if cls is None:
        known = sorted(MonsterPlugin._PLUGIN_REGISTRY.keys())
        raise SystemExit(
            f"Unknown target '{target}'. Pass 'player' or a monster "
            f"stem: {', '.join(known)}"
        )
    return cls()


def _emergent_stats_sweep(creature: Creature) -> List[str]:
    """Run an injury sweep and report per-state emergent stats.

    Primary use: Phase B4 baseline capture. The B-arc plan is to
    rewrite :meth:`Creature.get_defense` / ``get_dodge`` /
    ``get_hit_modifier`` as tree reductions over mixin-filtered
    subsets (Defensive / Mobility / Sensory). The rewrite is
    expected to shift numbers — this sweep captures the pre-B4
    ground truth so the delta is measurable rather than
    speculative.

    Output rows:
    - ``@full``: all parts at full HP.
    - ``@<part>=0``: one non-critical part zeroed, rest healthy.
      Iterated in :attr:`body_parts` order so captures are stable
      across runs (with RNG seeded).

    Stat deltas at destroyed states are what B4 will actually
    change; full-health readings should stay identical pre/post.
    Part HP is restored between each injury so the sweep stays
    independent (no compounding state).
    """
    lines: List[str] = ["  stats:"]
    lines.append(
        f"    {'state':<20} {'defense':>8} {'dodge':>8} {'hit_mod':>8}"
    )

    def _row(label: str) -> str:
        return (
            f"    {label:<20} {creature.get_defense():>8} "
            f"{creature.get_dodge():>8} {creature.get_hit_modifier():>8}"
        )

    lines.append(_row("@full"))

    for part in list(creature.body_parts):
        if part.is_critical:
            # Critical parts zeroed would kill the creature and
            # wreck the sweep — the emergence contract defers to
            # the whole-creature death path there. Skip.
            continue
        saved = part.health
        part.health = 0
        lines.append(_row(f"@{part.name}=0"))
        part.health = saved

    return lines


def inspect(target: str, include_stats: bool = False) -> str:
    creature = _build_creature(target)
    header = (
        f"==== {target.upper()} ({type(creature).__name__}) ====\n"
        f"  size={creature.size.name}  "
        f"body_parts={len(creature.body_parts)}  "
        f"body_root={'yes' if creature.body_root else 'none'}"
    )
    tree_lines = _render_tree(creature.body_root)
    sections = [header] + tree_lines
    if include_stats:
        sections.extend(_emergent_stats_sweep(creature))
    return "\n".join(sections)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Dump a creature's body tree with mixin tags + placements.",
    )
    ap.add_argument(
        "targets",
        nargs="+",
        help=(
            "Creature targets to inspect. Each is 'player' for a fresh "
            "default Player, or a monster plugin stem (dragon / goblin / "
            "hydra / etc.)."
        ),
    )
    ap.add_argument(
        "--stats",
        action="store_true",
        help=(
            "Also report emergent stats (get_defense / get_dodge / "
            "get_hit_modifier) at full health and with each non-critical "
            "part zeroed in turn. Used to capture Phase B4 baselines — "
            "the tree-walk emergence rewrite will shift these numbers "
            "and we want a concrete pre/post delta."
        ),
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=0,
        help=(
            "RNG seed applied before each creature is constructed. "
            "Captures are otherwise non-deterministic for creatures "
            "with randomized construction (hydra variants, dragon's "
            "has-toes roll). Default 0 for stable baselines."
        ),
    )
    args = ap.parse_args(argv)

    for target in args.targets:
        random.seed(args.seed)
        print(inspect(target, include_stats=args.stats))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
