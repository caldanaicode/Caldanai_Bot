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
# ``(part_name, key)`` pair. Compound aliases (``ARMS`` =
# ``LEFT_ARM | RIGHT_ARM``, etc.) don't appear here — their bits
# resolve through the sided entries below, so a compound mask
# naturally expands to both entries via the bit-test loop in
# :func:`resolve_placements`.
SLOT_TO_PART_KEY: Dict[EquipmentSlots, Tuple[str, str]] = {
    # Head
    EquipmentSlots.HEAD:          ("head",      "helm"),
    EquipmentSlots.FACE:          ("head",      "face"),
    EquipmentSlots.LEFT_EAR:      ("head",      "ear.left"),
    EquipmentSlots.RIGHT_EAR:     ("head",      "ear.right"),
    # Torso
    EquipmentSlots.TORSO:         ("torso",     "chest"),
    EquipmentSlots.CAPE:          ("torso",     "cape"),
    EquipmentSlots.WAIST:         ("torso",     "belt"),
    # Neck (vestigial body part, amulet/jewelry key)
    EquipmentSlots.NECK:          ("neck",      "amulet"),
    EquipmentSlots.AMULET:        ("neck",      "amulet"),
    # Arms — per-side sided slots (2026-04-22 rework). Compound
    # aliases (``ARMS`` / ``FOREARMS`` / ``GLOVES``) expand to
    # both sides automatically via the bit-test loop.
    EquipmentSlots.LEFT_HELD:     ("arm.left",  "held"),
    EquipmentSlots.RIGHT_HELD:    ("arm.right", "held"),
    EquipmentSlots.LEFT_ARM:      ("arm.left",  "bracer"),
    EquipmentSlots.RIGHT_ARM:     ("arm.right", "bracer"),
    EquipmentSlots.LEFT_FOREARM:  ("arm.left",  "vambrace"),
    EquipmentSlots.RIGHT_FOREARM: ("arm.right", "vambrace"),
    EquipmentSlots.LEFT_GLOVE:    ("arm.left",  "glove"),
    EquipmentSlots.RIGHT_GLOVE:   ("arm.right", "glove"),
    EquipmentSlots.LEFT_RING:     ("arm.left",  "ring"),
    EquipmentSlots.RIGHT_RING:    ("arm.right", "ring"),
    # Legs — same sided pattern
    EquipmentSlots.LEFT_LEG:      ("leg.left",  "greave"),
    EquipmentSlots.RIGHT_LEG:     ("leg.right", "greave"),
    EquipmentSlots.LEFT_SHIN:     ("leg.left",  "shin"),
    EquipmentSlots.RIGHT_SHIN:    ("leg.right", "shin"),
    EquipmentSlots.LEFT_FOOT:     ("leg.left",  "boot"),
    EquipmentSlots.RIGHT_FOOT:    ("leg.right", "boot"),
}


# One-to-many placements. A single slot flag expands into multiple
# ``(part, key)`` pairs — for items that MUST span that shape and
# have no single-side equivalent. Currently empty; the 2026-04-22
# enum rework replaced the old pair-slot entries (ARMS, GLOVES,
# FEET, etc.) with sided bits + compound aliases, which compose
# cleanly with limb-loss (each side drops independently when its
# arm/leg is destroyed). The table is kept for future content:
# manacles (force-pair wrist items), magical sets that refuse to
# function alone, or any other "no lone-side variant" gear.
SLOT_PAIR: Dict[EquipmentSlots, List[Tuple[str, str]]] = {}


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
