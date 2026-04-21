"""Dump a monster's canonical stats (size, body HP, defense, dodge) and
per-part HP after ``_scale_part_hp`` settles, for quick sanity checks
while tuning creature balance.

Replaces ad-hoc ``python -c`` snippets like:

    python -c "from ... import MonsterPlugin; MonsterPlugin.load_plugins(); \\
               d = MonsterPlugin._PLUGIN_REGISTRY['dragon'](); \\
               print(d.health_max, d.get_defense())"

Use instead:

    python -m tools.inspect_monster dragon
    python -m tools.inspect_monster dragon bearowl hydra
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin


def inspect(stem: str) -> str:
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(stem)
    if cls is None:
        return f"unknown monster: {stem}"
    m = cls()
    lines = [
        f"==== {stem.upper()} ({m.__class__.__name__}) ====",
        f"  size={m.size.name}  body_hp={m.health_max}  "
        f"defense={m.get_defense()}  dodge={m.get_dodge()}  "
        f"BLEED_MOD={m.BLEED_MOD}",
    ]
    for p in m.body_parts:
        crit = "*CRIT*" if p.is_critical else "      "
        lines.append(
            f"  {crit} {p.name:<20} hp={p.health_max:>4}  "
            f"bleed_rate={getattr(p, 'bleed_rate', 1.0):.2f}  "
            f"defense_bonus={getattr(p, 'defense_bonus', 0):+d}"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Dump a monster's Q.6-scaled part HP + stats.",
    )
    ap.add_argument("stems", nargs="+", help="Monster plugin stems to inspect.")
    args = ap.parse_args(argv)

    for stem in args.stems:
        print(inspect(stem))
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
