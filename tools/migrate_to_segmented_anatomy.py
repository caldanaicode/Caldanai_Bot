"""One-shot migration: pre-Phase-D ``part_equipment`` → segmented
anatomy + generic-key shape.

The 2026-04-23 Phase D rework moved equipment placements to a
deeper body tree (hands and feet are now real nodes) and
collapsed the key vocabulary to a generic set
(``worn``/``held``/``outer``/``accent`` + dotted sub-keys like
``worn.upper`` or ``ring.1``).

Old docs store equipment under the pre-D key names. If loaded
as-is, the rehydration path silently skips unrecognized keys —
items stay in inventory but equipped state is lost. This tool
rewrites every player's ``part_equipment`` dict to the new
shape so upgraded bots start with the same gear equipped.

Default is DRY-RUN. Inspect per-player diffs. Re-run with
``--write`` to apply.

Usage::

    python -m tools.migrate_to_segmented_anatomy                  # dry-run LIVE
    python -m tools.migrate_to_segmented_anatomy TEST_DB_NAME     # dry-run test
    python -m tools.migrate_to_segmented_anatomy TEST_DB_NAME --write

Translation rules live in :data:`_KEY_REMAP` below — the single
source of truth for which old ``(part, key)`` pair maps to
which new ``(part, key)`` pair. Anything not in the map is
preserved unchanged (future-compatible) so an already-migrated
doc is a no-op.
"""

import argparse
import sys
from typing import Any, Dict, List, Optional, Tuple

from pymongo import UpdateOne

from tools._common import live_db, use_db_env_var


#: Old ``(part, key)`` → new ``(part, key)`` remap for Phase D.
#: Tuples are hashable; dict lookup is O(1). Any entry not in
#: this dict is carried forward verbatim (future-compatible
#: with fresh docs already stored under the new shape).
_KEY_REMAP: Dict[Tuple[str, str], Tuple[str, str]] = {
    # Head layers
    ("head", "helm"):      ("head", "worn"),
    ("head", "face"):      ("head", "outer"),
    ("head", "ear.left"):  ("head", "earring.left"),
    ("head", "ear.right"): ("head", "earring.right"),
    # Torso layers
    ("torso", "chest"):    ("torso", "worn"),
    ("torso", "cape"):     ("torso", "outer"),
    ("torso", "belt"):     ("torso", "accent"),
    # Neck
    ("neck", "amulet"):    ("neck", "accent"),
    # Arms → segmented (armor stays on arm; weapon + glove + ring
    # move to the new hand node).
    ("arm.left",  "held"):     ("hand.left",  "held"),
    ("arm.right", "held"):     ("hand.right", "held"),
    ("arm.left",  "bracer"):   ("arm.left",   "worn.upper"),
    ("arm.right", "bracer"):   ("arm.right",  "worn.upper"),
    ("arm.left",  "vambrace"): ("arm.left",   "worn.lower"),
    ("arm.right", "vambrace"): ("arm.right",  "worn.lower"),
    ("arm.left",  "glove"):    ("hand.left",  "worn"),
    ("arm.right", "glove"):    ("hand.right", "worn"),
    ("arm.left",  "ring"):     ("hand.left",  "ring.1"),
    ("arm.right", "ring"):     ("hand.right", "ring.1"),
    # Legs → segmented (armor stays on leg; boot moves to foot).
    ("leg.left",  "greave"):   ("leg.left",   "worn.upper"),
    ("leg.right", "greave"):   ("leg.right",  "worn.upper"),
    ("leg.left",  "shin"):     ("leg.left",   "worn.lower"),
    ("leg.right", "shin"):     ("leg.right",  "worn.lower"),
    ("leg.left",  "boot"):     ("foot.left",  "worn"),
    ("leg.right", "boot"):     ("foot.right", "worn"),
}


def _remap_part_equipment(
    legacy: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    """Transform a pre-D ``part_equipment`` dict to the Phase D
    shape. Returns ``(new_shape, warnings)``.

    Entries with ``None`` values are dropped entirely — the new
    shape stores only occupied placements. Keys not in
    :data:`_KEY_REMAP` are carried forward verbatim (either a
    future-compat shape we haven't catalogued OR a doc already
    migrated — idempotent on second run)."""
    new_shape: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    if not isinstance(legacy, dict):
        return new_shape, warnings

    for old_part, placements in legacy.items():
        if not isinstance(placements, dict):
            continue
        for old_key, item_id in placements.items():
            if item_id is None:
                continue
            old_pair = (old_part, old_key)
            new_pair = _KEY_REMAP.get(old_pair, old_pair)
            new_part, new_key = new_pair
            if new_part not in new_shape:
                new_shape[new_part] = {}
            if new_key in new_shape[new_part]:
                # Collision — two old placements both point at
                # the same new placement. Preserve the first;
                # warn so the operator can inspect.
                warnings.append(
                    f"Collision: {old_pair} → {new_pair} "
                    f"already holds {new_shape[new_part][new_key]!r}; "
                    f"skipping item {item_id!r}"
                )
                continue
            new_shape[new_part][new_key] = item_id

    return new_shape, warnings


def _diff_for_display(
    old: Dict[str, Dict[str, Any]],
    new: Dict[str, Dict[str, Any]],
) -> List[str]:
    """Flat per-line diff suitable for dry-run inspection.
    Shows only the actual movement (no no-op lines)."""
    lines: List[str] = []

    def _flatten(shape: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for p, keys in shape.items():
            if not isinstance(keys, dict):
                continue
            for k, v in keys.items():
                if v is None:
                    continue
                out[f"{p}.{k}"] = v
        return out

    flat_old = _flatten(old)
    flat_new = _flatten(new)

    # Match items by id across old / new to produce "moved from
    # X to Y" lines. Items without an id pair become "+new" /
    # "-removed".
    old_by_id: Dict[Any, str] = {str(v): k for k, v in flat_old.items()}
    new_by_id: Dict[Any, str] = {str(v): k for k, v in flat_new.items()}
    all_ids = set(old_by_id) | set(new_by_id)
    for iid in sorted(all_ids, key=str):
        old_loc = old_by_id.get(iid)
        new_loc = new_by_id.get(iid)
        if old_loc == new_loc:
            continue
        if old_loc and new_loc:
            lines.append(f"    {iid}: {old_loc} → {new_loc}")
        elif new_loc:
            lines.append(f"    {iid}: (none) → {new_loc}")
        elif old_loc:
            lines.append(f"    {iid}: {old_loc} → (none)")
    return lines


def _iter_player_docs(db):
    return db.players.find({}, {
        "_id": 1, "user_id": 1, "guild_id": 1, "part_equipment": 1,
    })


def _canon(shape: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Strip ``None`` values and empty sub-dicts — gives the legacy
    ``part_equipment`` the same shape the new-side output has, so a
    fair equality check can decide "no-op."""
    canon: Dict[str, Dict[str, Any]] = {}
    for p, keys in shape.items():
        if not isinstance(keys, dict):
            continue
        kept = {k: v for k, v in keys.items() if v is not None}
        if kept:
            canon[p] = kept
    return canon


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Migrate player part_equipment to Phase D segmented "
            "anatomy + generic keys. Dry-run by default; pass "
            "--write to actually apply."
        ),
    )
    ap.add_argument(
        "env", nargs="?", default=None,
        help=(
            "DB env var name to route through (e.g. TEST_DB_NAME). "
            "Omitted = LIVE_DB_NAME (production)."
        ),
    )
    ap.add_argument(
        "--write", action="store_true",
        help="Actually apply updates. Default dry-run.",
    )
    args = ap.parse_args()

    if args.env:
        use_db_env_var(args.env)
    db = live_db()

    total = 0
    changed = 0
    no_change = 0
    warning_count = 0
    bulk_ops: List[UpdateOne] = []

    for doc in _iter_player_docs(db):
        total += 1
        legacy = doc.get("part_equipment") or {}
        new_shape, warnings = _remap_part_equipment(legacy)

        old_canon = _canon(legacy)
        if old_canon == new_shape:
            no_change += 1
            continue

        changed += 1
        warning_count += len(warnings)
        uid = doc.get("user_id")
        gid = doc.get("guild_id")
        header = f"Player uid={uid} gid={gid}:"
        diff_lines = _diff_for_display(old_canon, new_shape)
        print(header)
        for line in diff_lines:
            print(line)
        for w in warnings:
            print(f"  WARN: {w}")
        print()

        bulk_ops.append(UpdateOne(
            {"_id": doc["_id"]},
            {"$set": {"part_equipment": new_shape}},
        ))

    print("=" * 60)
    print(f"total docs:       {total}")
    print(f"changed:          {changed}")
    print(f"no change:        {no_change}")
    print(f"warning count:    {warning_count}")
    print(f"dry-run: {not args.write}")

    if args.write and bulk_ops:
        print(f"Applying {len(bulk_ops)} updates...")
        result = db.players.bulk_write(bulk_ops, ordered=False)
        print(f"matched={result.matched_count} modified={result.modified_count}")
    elif args.write:
        print("No updates to apply.")
    else:
        print("Re-run with --write to apply.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
