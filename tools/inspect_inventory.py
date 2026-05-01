"""Dump a player's inventory from MongoDB with each item's
``plugin`` / ``quality`` / ``favorited`` flag side by side.

Replaces the ``python -c "from pymongo import...; db.players.find_one(...)"``
shell-snippet that would otherwise be needed to investigate
inventory grouping bugs (the trigger: 2026-04-29 ``$sell duplicates``
left 3 quality bandannas where keep=1 should leave 1, suggesting
a stealth ``plugin`` mismatch among items that look identical to
the player).

Output is one row per inventory entry:

    [SLOT] PLUGIN  QUALITY  NAME  flags=eq|fav|both|-

Slot is the persisted slot key (1-based after rekey). Equipped
detection scans the player's ``part_equipment`` map for items
whose ``_id`` matches each inventory entry. Favorited reads
straight off the inventory document.

Usage::

    python -m tools.inspect_inventory --user-name "Vael Caldanai"          # TEST DB (default)
    python -m tools.inspect_inventory --user-id 12345                      # TEST DB (default)
    python -m tools.inspect_inventory --user-name Vael --plugin bandanna   # TEST + filter
    python -m tools.inspect_inventory --live --user-name "Caels"           # LIVE DB (opt-in)
    python -m tools.inspect_inventory --db OTHER_DB_NAME ...               # explicit env override

Default DB env is ``TEST_DB_NAME`` — the typical agent investigation
target. ``--live`` swaps to ``LIVE_DB_NAME`` for real-player
forensics. ``--db`` overrides with any other env var when needed.

The ``--plugin`` filter limits output to one item plugin (or any
substring match against ``plugin`` / ``name``) — useful when you
only care about a specific group's mystery.
"""

import argparse
import sys

from tools._common import live_db, use_db_env_var


def _collect_equipped_ids(player_doc) -> set:
    """Walk the persisted ``part_equipment`` tree and gather the
    ID of every currently-equipped item. Persistence stores each
    placement as the item's ``_id`` rendered as a string (see
    ``Player.to_dict``), so we accept str ObjectIds here."""
    equipped = set()
    pe = player_doc.get("part_equipment") or {}
    for placements in pe.values():
        if not isinstance(placements, dict):
            continue
        for entry in placements.values():
            if entry is not None:
                # Inventory items serialize ``_id`` as ObjectId, but
                # ``part_equipment`` stores the same id stringified.
                # Normalize to str for set membership comparison.
                equipped.add(str(entry))
    return equipped


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m tools.inspect_inventory",
        description=(
            "Dump a player's inventory with per-item plugin / "
            "quality / equipped / favorited info."
        ),
    )
    db_group = parser.add_mutually_exclusive_group()
    db_group.add_argument(
        "--live", action="store_true",
        help="Read from LIVE_DB_NAME (real-player forensics). "
             "Default reads from TEST_DB_NAME — the usual agent "
             "investigation target.",
    )
    db_group.add_argument(
        "--db", default=None,
        help="Env var name pointing to a specific MongoDB DB to "
             "read (overrides default + --live).",
    )
    parser.add_argument(
        "--user-id", type=int, default=None,
        help="Filter by Discord user id.",
    )
    parser.add_argument(
        "--user-name", default=None,
        help="Substring match against Player.name. Quote if "
             "the name has spaces.",
    )
    parser.add_argument(
        "--plugin", default=None,
        help="Filter rows to those whose plugin OR name "
             "contains this substring (case-insensitive).",
    )
    args = parser.parse_args(argv)

    db_env = args.db or ("LIVE_DB_NAME" if args.live else "TEST_DB_NAME")
    use_db_env_var(db_env)
    db = live_db()

    query = {}
    if args.user_id is not None:
        query["user_id"] = args.user_id
    if args.user_name:
        query["name"] = {"$regex": args.user_name, "$options": "i"}

    players = list(db.players.find(query))
    if not players:
        print(f"No player matching {query!r}", file=sys.stderr)
        return 1

    for p in players:
        print(
            f"\n=== Player {p.get('name','?')!r}  "
            f"user_id={p.get('user_id')!r}  "
            f"guild_id={p.get('guild_id')!r}  "
            f"channel_id={p.get('channel_id')!r} ==="
        )

        equipped_ids = _collect_equipped_ids(p)
        # Persisted shape uses ``items`` for the inventory list —
        # see Player.to_dict. The local Inventory object's plugin
        # is round-tripped per entry so this view matches what
        # ``$sell duplicates`` actually sees.
        inv = p.get("items") or []

        rows = []
        for slot, entry in enumerate(inv, start=1):
            plugin = entry.get("plugin")
            quality = entry.get("quality")
            name = entry.get("name") or entry.get("plugin") or "?"
            iid = entry.get("_id")
            favorited = bool(entry.get("favorited"))
            equipped = str(iid) in equipped_ids

            if args.plugin:
                needle = args.plugin.lower()
                if (
                    needle not in (plugin or "").lower()
                    and needle not in (name or "").lower()
                ):
                    continue

            flags_parts = []
            if equipped:
                flags_parts.append("eq")
            if favorited:
                flags_parts.append("fav")
            flags = "|".join(flags_parts) or "-"

            rows.append(
                f"  [{slot:>3}] plugin={plugin!s:<24} "
                f"quality={quality!s:<10} "
                f"name={name!r:<30} "
                f"_id={iid!s:<28} "
                f"flags={flags}"
            )

        if not rows:
            print("  (no rows after filters)")
        else:
            for row in rows:
                print(row)

    return 0


if __name__ == "__main__":
    sys.exit(main())
