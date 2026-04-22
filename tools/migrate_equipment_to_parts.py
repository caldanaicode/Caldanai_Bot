"""One-shot migration: player ``equip_slots`` → ``part_equipment``.

The 2026-04-21 equipment-on-parts cutover removed the parallel
``equip_slots`` field in favor of body-part ownership
(``part_equipment[part_name][key] = item_id``). New code
(``Player.from_dict``) refuses to load legacy docs — so every
player document that still carries ``equip_slots`` must be
translated before the new bot boots.

This tool is the one-shot translator. Default mode is dry-run:
walk every player doc, compute the new shape in memory, print a
per-player diff of the translation, write nothing. Re-run with
``--write`` to actually apply the bulk update (drops
``equip_slots``, sets ``part_equipment``).

Usage::

    python -m tools.migrate_equipment_to_parts                  # dry-run LIVE
    python -m tools.migrate_equipment_to_parts TEST_DB_NAME     # dry-run test DB
    python -m tools.migrate_equipment_to_parts TEST_DB_NAME --write

Intended flow for a production migration:

1. Shut down the bot.
2. Run this tool in dry-run mode against the live DB. Inspect
   the diff carefully — every equipped item in every player doc
   should land at the expected ``(part, key)``.
3. Re-run with ``--write`` to actually apply.
4. Deploy the new bot code and start up. The ``from_dict``
   legacy guard will fail loudly if any doc was missed.

Translation rules (single source of truth:
``caldanai.lib.rpg.creatures.equipment_routing``):

- Each legacy ``equip_slots`` entry is resolved to ``(part,
  key)`` via the mapping table. Multi-placement items (two-
  handed weapons present in both ``LEFT_HELD`` and
  ``RIGHT_HELD`` slots) produce two entries in the new shape —
  same item id at both placements, matching the runtime
  shared-reference semantics.
- Items in slots that no longer exist (``SHOULDERS``,
  ``ABDOMEN``, or legacy ``NECK`` on ``high-collared_cape``)
  are silently dropped if nothing was equipped. If an item IS
  in such a slot, it's logged as a warning and the entry is
  skipped — the item stays in inventory so it's recoverable.
"""

import argparse
import sys
from typing import Dict, List, Optional, Tuple

from pymongo import UpdateOne

from tools._common import live_db, use_db_env_var

from caldanai.lib.rpg.creatures.equipment_routing import (
    SLOT_PAIR,
    SLOT_TO_PART_KEY,
)
from caldanai.lib.rpg.helpers.enums import EquipmentSlots
from caldanai.lib.rpg.inventory import Inventory


# Slot names that mapped to real placements at migration time.
# Anything in ``equip_slots`` whose key isn't in this set is a
# dropped-legacy-slot (SHOULDERS / ABDOMEN) and gets warned on.
_KNOWN_SLOT_NAMES = (
    {s.name for s in SLOT_TO_PART_KEY}
    | {s.name for s in SLOT_PAIR}
)


def _compute_part_equipment(
    legacy: Dict[str, Optional[str]],
    items_list: List[dict],
) -> Tuple[Dict[str, Dict[str, str]], List[str]]:
    """Translate one player doc's legacy ``equip_slots`` into the
    new ``part_equipment`` shape.

    Returns ``(new_shape, warnings)`` where ``new_shape`` is
    ``{part_name: {key: item_id_str}}`` (empty placements
    omitted) and ``warnings`` is a list of operator-facing
    strings describing anything skipped (legacy slots with items,
    items missing from inventory, etc.).

    Loads items from the ``items_list`` so each item's CURRENT
    ``.slots`` declaration drives the placement — items whose
    slots shape changed in code (e.g. ``high-collared_cape`` from
    ``NECK | CAPE`` to just ``CAPE``) migrate to their new
    single-slot home rather than their stale dual-slot home.
    """
    warnings: List[str] = []
    new_shape: Dict[str, Dict[str, str]] = {}

    # Load the item instances so we can read each item's declared
    # ``slots`` attribute. Item objects expose ``.id`` and
    # ``.slots`` after ``Inventory.load_item`` — we don't need
    # anything else for migration.
    items_by_id: Dict[str, object] = {}
    for item_dict in items_list:
        item = Inventory.load_item(data=item_dict)
        if item is None:
            continue
        items_by_id[str(item.id)] = item

    # Group legacy entries by item id first so we can make a
    # single placement decision per unique item — a two-handed
    # weapon appears at both LEFT_HELD and RIGHT_HELD pointing
    # at the same id, and high-collared_cape (pre-reroute) shows
    # up at both NECK and CAPE. Picking the right placement
    # requires seeing the full set of legacy slots the item
    # occupied AND the item's current ``.slots`` declaration.
    legacy_by_item: Dict[str, List[str]] = {}
    removed_slot_warnings: List[str] = []
    for slot_name, item_id in legacy.items():
        if item_id is None:
            continue
        item_id_str = str(item_id)
        if slot_name not in _KNOWN_SLOT_NAMES:
            # Items in SHOULDERS / ABDOMEN (slots we deleted) —
            # warn and drop. Item stays in inventory.
            removed_slot_warnings.append(
                f"legacy slot {slot_name!r} has no mapping in the "
                f"new shape — dropping (item_id={item_id_str!r})"
            )
            continue
        legacy_by_item.setdefault(item_id_str, []).append(slot_name)

    warnings.extend(removed_slot_warnings)

    for item_id_str, legacy_slots in legacy_by_item.items():
        item = items_by_id.get(item_id_str)
        if item is None:
            warnings.append(
                f"equipped item {item_id_str!r} at {legacy_slots!r} "
                "not found in inventory — skipping"
            )
            continue

        slots_mask = getattr(item, "slots", None)
        is_multi = slots_mask is not None and bool(
            slots_mask & EquipmentSlots.MULTI_SLOT
        )

        placements: List[Tuple[str, str]] = []
        if is_multi:
            # MULTI_SLOT: item occupies every slot in its current
            # mask simultaneously. Expand through the full mask —
            # two-handed weapons land on both ``arm.*.held``.
            for slot, placement in SLOT_TO_PART_KEY.items():
                if slot & slots_mask:
                    placements.append(placement)
            for slot, pair in SLOT_PAIR.items():
                if slot & slots_mask:
                    placements.extend(pair)
        else:
            # Single-slot: item occupies exactly one of its
            # compatible slots at runtime. Pick the legacy slot
            # that's STILL compatible with the current slots
            # mask — this is what reroutes high-collared_cape
            # from ``NECK+CAPE`` legacy down to just ``torso.cape``
            # after the item's slots declaration was reduced to
            # ``CAPE`` only.
            for slot_name in legacy_slots:
                slot_enum = EquipmentSlots[slot_name]
                if slots_mask is not None and not (slot_enum & slots_mask):
                    continue
                if slot_enum in SLOT_TO_PART_KEY:
                    placements.append(SLOT_TO_PART_KEY[slot_enum])
                    break
                if slot_enum in SLOT_PAIR:
                    placements.extend(SLOT_PAIR[slot_enum])
                    break

        # Dedupe placements (an item declaring both AMULET and
        # NECK maps to the same ``(neck, amulet)`` twice).
        deduped: List[Tuple[str, str]] = []
        seen_placements = set()
        for p in placements:
            if p not in seen_placements:
                deduped.append(p)
                seen_placements.add(p)

        if not deduped:
            warnings.append(
                f"item {item_id_str!r} resolved to no placements "
                f"(legacy slots={legacy_slots}, "
                f"current slots={int(slots_mask or 0)}) — skipping"
            )
            continue

        for (part_name, key) in deduped:
            new_shape.setdefault(part_name, {})[key] = item_id_str

    return new_shape, warnings


def _print_dry_run(
    migrated: List[dict],
    already_ok: int,
    skipped: int,
    total: int,
) -> None:
    print(f"== Equipment migration: dry-run ({total} player doc(s) scanned)\n")
    print(
        f"   {len(migrated)} doc(s) would be migrated  |  "
        f"{already_ok} already migrated  |  {skipped} empty / no-op"
    )
    print()

    if not migrated:
        print("Nothing to migrate.")
        return

    for entry in migrated:
        legacy = entry["legacy"]
        new_shape = entry["new_shape"]
        warnings = entry["warnings"]

        header = f"  Player {entry['_id']}"
        user = entry.get("user_id")
        guild = entry.get("guild_id")
        channel = entry.get("channel_id")
        if user is not None or guild is not None or channel is not None:
            bits = []
            if user is not None:
                bits.append(f"user={user}")
            if guild is not None:
                bits.append(f"guild={guild}")
            if channel is not None:
                bits.append(f"channel={channel}")
            header += f"  ({', '.join(bits)})"
        print(header)

        # Flatten the new shape into per-placement lines so the
        # operator can see exactly where every item landed.
        lines: List[str] = []
        for (part_name, keys) in new_shape.items():
            for (key, item_id) in keys.items():
                lines.append(f"    {part_name}.{key} = {item_id}")
        if lines:
            print("    new part_equipment:")
            for line in lines:
                print(line)
        else:
            print("    new part_equipment: (empty — nothing was equipped)")

        for w in warnings:
            print(f"    ! {w}")
        print()

    print("Dry-run. Re-run with --write to actually apply.")


def _print_write_summary(
    written: int, warnings_count: int, total: int, already_ok: int,
) -> None:
    print(f"== Migration complete: {written} doc(s) updated / {total} scanned")
    if already_ok:
        print(f"   {already_ok} doc(s) were already migrated — untouched.")
    if warnings_count:
        print(f"   {warnings_count} warning(s) surfaced — review above.")


def migrate(*, write: bool) -> int:
    """Walk ``players`` collection, translate legacy docs, either
    print the diff or apply the bulk update. Returns the exit
    status (0 on success, 1 on any warnings in write mode)."""
    players = live_db().players

    migrated: List[dict] = []
    already_ok = 0
    skipped = 0
    total = 0
    warnings_total = 0

    for doc in players.find({}):
        total += 1
        has_legacy = "equip_slots" in doc
        has_new = "part_equipment" in doc

        if has_new and not has_legacy:
            already_ok += 1
            continue
        if not has_legacy:
            # Rare: pre-migration doc with neither field. Treat
            # as empty — initialize to the empty new shape so the
            # new loader doesn't choke.
            migrated.append({
                "_id": doc.get("_id"),
                "user_id": doc.get("user_id"),
                "guild_id": doc.get("guild_id"),
                "channel_id": doc.get("channel_id"),
                "legacy": {},
                "new_shape": {},
                "warnings": [],
            })
            continue

        legacy = doc.get("equip_slots") or {}
        new_shape, warnings = _compute_part_equipment(
            legacy, doc.get("items") or [],
        )

        migrated.append({
            "_id": doc.get("_id"),
            "user_id": doc.get("user_id"),
            "guild_id": doc.get("guild_id"),
            "channel_id": doc.get("channel_id"),
            "legacy": legacy,
            "new_shape": new_shape,
            "warnings": warnings,
        })
        warnings_total += len(warnings)

    if not write:
        _print_dry_run(migrated, already_ok, skipped, total)
        return 0

    if not migrated:
        print("Nothing to migrate.")
        return 0

    ops = []
    for entry in migrated:
        ops.append(
            UpdateOne(
                {"_id": entry["_id"]},
                {
                    "$set": {"part_equipment": entry["new_shape"]},
                    "$unset": {"equip_slots": ""},
                },
            )
        )

    result = players.bulk_write(ops, ordered=False)
    _print_write_summary(
        written=result.modified_count,
        warnings_count=warnings_total,
        total=total,
        already_ok=already_ok,
    )
    return 1 if warnings_total else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Migrate player documents from the legacy ``equip_slots`` "
            "shape to the ``part_equipment`` shape. Dry-run by default."
        ),
    )
    parser.add_argument(
        "db_env_var",
        nargs="?",
        default="LIVE_DB_NAME",
        help=(
            "Name of the env var holding the Mongo DB name to target "
            "(default: LIVE_DB_NAME). Use TEST_DB_NAME for local testing."
        ),
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Actually apply the bulk update. Default: dry-run only.",
    )
    args = parser.parse_args(argv)

    use_db_env_var(args.db_env_var)
    return migrate(write=args.write)


if __name__ == "__main__":
    sys.exit(main())
