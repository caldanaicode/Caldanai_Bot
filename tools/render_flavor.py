"""Render a monster's flavor strings (arrival / escape / death /
on_hugged / on_social) through the ``parse()`` pipeline so new
templates can be eyeballed for token bugs without spinning up the
bot.

Usage::

    python -m tools.render_flavor <monster_stem>
    python -m tools.render_flavor bandit --count 40
    python -m tools.render_flavor bandit --actor-name Serena --seed 0
    python -m tools.render_flavor bandit --cmd high_five
    python -m tools.render_flavor bandit --json

``<monster_stem>`` is the plugin filename stem (``bandit``,
``math_teacher``, ...), matched the same way the ``$spawn monster``
command does.

Each ``on_hugged`` / ``on_social`` branch is sampled ``--count``
times and the unique parsed outputs are dumped. Static flavor
(arrival, flavor, escape, death) is rendered once.

Why this exists: rendering templates with inline ``python -c``
forces an approval every time and drifts each rewrite. A fixed
entrypoint lets a single permission cover all flavor-proofing
runs and keeps the output shape consistent.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from typing import Dict, List, Optional

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.helpers import warmth


def _build_actor(name: str) -> Player:
    p = Player(clarks=500)
    p.name = name
    p.uses_article = False
    return p


def _resolve_monster(stem: str) -> MonsterPlugin:
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(stem)
    if cls is None:
        known = sorted(MonsterPlugin._PLUGIN_REGISTRY.keys())
        raise SystemExit(
            f"unknown monster '{stem}'. known: {', '.join(known)}"
        )
    return cls()


def _render_static(monster: Creature, actor: Player) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {}
    for field in ("arrival", "flavor", "escape", "death"):
        raw = getattr(monster, field, None)
        out[field] = parse(raw, monster, actor) if raw else None
    return out


def _sample_branches(
    fn,
    count: int,
    post_parse: bool,
    monster: Creature,
    actor: Player,
) -> List[str]:
    """Call ``fn(...)`` ``count`` times and return unique non-empty
    outputs, optionally routing each result through ``parse()``.
    """
    seen: Dict[str, None] = {}
    for _ in range(count):
        raw = fn()
        if not raw:
            continue
        rendered = parse(raw, monster, actor) if post_parse else raw
        seen.setdefault(rendered, None)
    return list(seen)


def _render_on_hugged(
    monster: Creature, actor: Player, count: int,
) -> List[str]:
    # ``on_hugged`` returns raw template text; the ``on_social``
    # delegation path is what applies ``parse()``. Mirror that here.
    return _sample_branches(
        lambda: monster.on_hugged(actor, "hug"),
        count=count,
        post_parse=True,
        monster=monster,
        actor=actor,
    )


def _render_on_social(
    monster: Creature, actor: Player, cmd: str, count: int,
) -> List[str]:
    # ``on_social`` is already expected to return parsed text, so do
    # not double-parse here.
    return _sample_branches(
        lambda: monster.on_social(cmd, actor, cmd),
        count=count,
        post_parse=False,
        monster=monster,
        actor=actor,
    )


def _print_section(title: str, lines: List[str]) -> None:
    print(f"\n== {title} ==")
    if not lines:
        print("  (empty)")
        return
    for line in lines:
        # Indent multi-line entries so branch boundaries stay legible.
        for i, part in enumerate(line.split("\n")):
            prefix = "  - " if i == 0 else "    "
            print(f"{prefix}{part}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stem", help="monster plugin filename stem (e.g. 'bandit')")
    ap.add_argument("--count", type=int, default=40,
                    help="sample iterations per random branch (default 40)")
    ap.add_argument("--actor-name", default="Caels",
                    help="name for the Player actor used in rendering")
    ap.add_argument("--cmd", default=None,
                    help="only render a single social cmd (e.g. 'high_five')")
    ap.add_argument("--seed", type=int, default=None,
                    help="seed random.choice so output is reproducible")
    ap.add_argument("--json", action="store_true",
                    help="emit JSON instead of human-readable sections")
    args = ap.parse_args(argv)

    if args.seed is not None:
        random.seed(args.seed)

    monster = _resolve_monster(args.stem)
    actor = _build_actor(args.actor_name)

    static = _render_static(monster, actor)
    on_hugged = _render_on_hugged(monster, actor, args.count)

    social: Dict[str, List[str]] = {}
    cmds = [args.cmd] if args.cmd else list(warmth.SOCIAL_COMMANDS)
    for cmd in cmds:
        social[cmd] = _render_on_social(monster, actor, cmd, args.count)

    if args.json:
        print(json.dumps(
            {"static": static, "on_hugged": on_hugged, "on_social": social},
            indent=2,
            ensure_ascii=False,
        ))
        return 0

    print(f"# {monster.__class__.__name__} vs {args.actor_name} "
          f"(count={args.count}, seed={args.seed})")
    _print_section("static flavor", [
        f"{k}: {v!r}" for k, v in static.items()
    ])
    _print_section("on_hugged branches", on_hugged)
    for cmd, lines in social.items():
        label = f"on_social({cmd!r})"
        _print_section(label, lines)
    return 0


if __name__ == "__main__":
    sys.exit(main())
