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
    # Show ``raw -> effective`` for defense / dodge so size-mod and
    # emergence aggregation are visible at a glance. Raw is the
    # rolled ``self.defense`` / ``self.dodge`` (the dice result of
    # the ``ndN`` spec); effective is what ``get_defense()`` /
    # ``get_dodge()`` return — the underlying creature pool that
    # combat starts from. The spawn embed itself shows the torso-
    # effective number (post 2026-04-28 contract shift), so we also
    # surface ``(torso N)`` to make the operator-side number match
    # what a player sees on $look. Body-less creatures (spirit) have
    # no torso; the suffix is omitted in that case.
    from caldanai.lib.rpg.creatures import effective_defense_for_part
    torso = m.get_part("torso") if m.body_parts else None
    if torso is None and m.body_parts:
        # Same fallback as the embed renderer — first critical part.
        torso = next(
            (p for p in m.body_parts if getattr(p, "is_critical", False)),
            m.body_parts[0],
        )
    if torso is not None:
        torso_def = effective_defense_for_part(m, torso)
        defense_str = (
            f"defense={m.defense}->{m.get_defense()} (torso {torso_def})"
        )
    else:
        defense_str = f"defense={m.defense}->{m.get_defense()}"
    lines = [
        f"==== {stem.upper()} ({m.__class__.__name__}) ====",
        f"  size={m.size.name}  body_hp={m.health_max}  "
        f"{defense_str}  "
        f"dodge={m.dodge}->{m.get_dodge()}  "
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
