"""Slot → (body_part, key) routing for player equipment.

The 2026-04-21 equipment-on-parts migration collapsed the parallel
``Player.equip_slots`` dict onto body-part ownership. Items now live
at ``player.part_equipment[part_name][key] = Item`` — so a shield
equipped to the left arm is a field on ``arm.left``, and losing
that arm naturally loses access to the shield (Stage 2: drop back
to inventory on USELESS).

This module holds the single source of truth for translating an
:class:`EquipmentSlots` flag into one or more ``(part_name, key)``
placements. Items still declare their compatible slots via the
existing ``item.slots`` mask — the mapping here decides where each
slot lands.

Two lookup tables:

- :data:`SLOT_TO_PART_KEY` — one-to-one. A ``HEAD`` slot lands at
  ``("head", "helm")``; a ``LEFT_HELD`` lands at
  ``("arm.left", "held")``.
- :data:`SLOT_PAIR` — one-to-many. A ``GLOVES`` slot lands at both
  ``("arm.left", "glove")`` and ``("arm.right", "glove")``. Used
  for natural pairs (gloves, boots, bracers) where an item covers
  both sides by nature.

Helper :func:`resolve_placements` walks an item's ``slots`` mask
and returns the flat list of every ``(part, key)`` the item should
occupy. Multi-slot items (``TWO_HANDED`` weapons, future paired
gear) naturally expand into multiple placements against the same
``Item`` instance — both placements reference the same object so
e.g. a held two-hander shows up correctly in both hands' views.

Unused slots that have no current items (ARMS, FOREARMS, GLOVES,
LEGS, SHINS, FEET, LEFT_RING, RIGHT_RING, AMULET, LEFT_EAR,
RIGHT_EAR, WAIST, NECK) still have placements reserved here so
the body parts have natural "homes" waiting when items land.
"""

from typing import Dict, List, Tuple

from caldanai.lib.rpg.helpers.enums import EquipmentSlots


# One-to-one placements. Each slot maps to exactly one
# ``(part_name, key)`` pair. Two-handed weapons expand through
# ``LEFT_HELD`` + ``RIGHT_HELD`` (both present in the item's mask
# via ``EquipmentSlots.TWO_HANDED``) so they don't need a pair
# entry of their own.
SLOT_TO_PART_KEY: Dict[EquipmentSlots, Tuple[str, str]] = {
    # Head
    EquipmentSlots.HEAD:       ("head",      "helm"),
    EquipmentSlots.FACE:       ("head",      "face"),
    EquipmentSlots.LEFT_EAR:   ("head",      "ear.left"),
    EquipmentSlots.RIGHT_EAR:  ("head",      "ear.right"),
    # Torso
    EquipmentSlots.TORSO:      ("torso",     "chest"),
    EquipmentSlots.CAPE:       ("torso",     "cape"),
    EquipmentSlots.WAIST:      ("torso",     "belt"),
    # Neck (vestigial body part, amulet/jewelry key)
    EquipmentSlots.NECK:       ("neck",      "amulet"),
    EquipmentSlots.AMULET:     ("neck",      "amulet"),
    # Arms
    EquipmentSlots.LEFT_HELD:  ("arm.left",  "held"),
    EquipmentSlots.RIGHT_HELD: ("arm.right", "held"),
    EquipmentSlots.LEFT_RING:  ("arm.left",  "ring"),
    EquipmentSlots.RIGHT_RING: ("arm.right", "ring"),
}


# One-to-many placements. A single slot flag expands into both
# sides of a natural pair. A "pair of gloves" item declares
# ``slots = EquipmentSlots.GLOVES`` (no MULTI_SLOT needed — the
# pair expansion lives in routing, not in the item's mask).
SLOT_PAIR: Dict[EquipmentSlots, List[Tuple[str, str]]] = {
    EquipmentSlots.ARMS:     [("arm.left",  "bracer"),   ("arm.right", "bracer")],
    EquipmentSlots.FOREARMS: [("arm.left",  "vambrace"), ("arm.right", "vambrace")],
    EquipmentSlots.GLOVES:   [("arm.left",  "glove"),    ("arm.right", "glove")],
    EquipmentSlots.LEGS:     [("leg.left",  "greave"),   ("leg.right", "greave")],
    EquipmentSlots.SHINS:    [("leg.left",  "shin"),     ("leg.right", "shin")],
    EquipmentSlots.FEET:     [("leg.left",  "boot"),     ("leg.right", "boot")],
}


# Flattened: every ``(part, key)`` placement an item CAN land at,
# from any slot. Useful for the display path that walks every
# possible placement slot.
ALL_PLACEMENTS: List[Tuple[str, str]] = sorted(
    set(list(SLOT_TO_PART_KEY.values()) + [p for pairs in SLOT_PAIR.values() for p in pairs])
)


# Ordering used by ``Player.get_equipment`` / ``$gear`` so the
# display follows a head-to-toe anatomy. Slots (or individual
# per-part keys) not in this list are appended in declaration
# order afterward.
PLACEMENT_DISPLAY_ORDER: List[Tuple[str, str]] = [
    ("head",      "helm"),
    ("head",      "face"),
    ("head",      "ear.left"),
    ("head",      "ear.right"),
    ("neck",      "amulet"),
    ("torso",     "chest"),
    ("torso",     "cape"),
    ("torso",     "belt"),
    ("arm.left",  "held"),
    ("arm.right", "held"),
    ("arm.left",  "bracer"),
    ("arm.right", "bracer"),
    ("arm.left",  "vambrace"),
    ("arm.right", "vambrace"),
    ("arm.left",  "glove"),
    ("arm.right", "glove"),
    ("arm.left",  "ring"),
    ("arm.right", "ring"),
    ("leg.left",  "greave"),
    ("leg.right", "greave"),
    ("leg.left",  "shin"),
    ("leg.right", "shin"),
    ("leg.left",  "boot"),
    ("leg.right", "boot"),
]


def resolve_placements(slots_mask: EquipmentSlots) -> List[Tuple[str, str]]:
    """Expand an item's ``slots`` mask into a flat list of every
    ``(part_name, key)`` the item should occupy.

    Ordering: deterministic (iteration over ``SLOT_TO_PART_KEY`` /
    ``SLOT_PAIR`` in declaration order, which is anatomically
    head-to-toe). Callers that want display order should use
    :data:`PLACEMENT_DISPLAY_ORDER` instead.

    Duplicates are collapsed — e.g. an item declaring
    ``AMULET | NECK`` (both map to ``("neck", "amulet")``) returns
    that placement once.
    """
    placements: List[Tuple[str, str]] = []
    seen = set()

    for slot, placement in SLOT_TO_PART_KEY.items():
        if slot & slots_mask and placement not in seen:
            placements.append(placement)
            seen.add(placement)

    for slot, pair in SLOT_PAIR.items():
        if slot & slots_mask:
            for placement in pair:
                if placement not in seen:
                    placements.append(placement)
                    seen.add(placement)

    return placements


def keys_on_part(part_name: str) -> List[str]:
    """Every ``key`` that can land on a given body part, collected
    from both lookup tables. Useful for Player equipment init
    (pre-seed the nested dict with every valid key → None) and for
    fuzzy-matching ``$unequip <part>.<key>`` command input."""
    keys: List[str] = []
    seen = set()

    for placement in ALL_PLACEMENTS:
        p, k = placement
        if p == part_name and k not in seen:
            keys.append(k)
            seen.add(k)

    return keys
