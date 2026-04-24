"""Slot → (body_part, key) routing for player equipment.

Phase D (2026-04-23) rewrites the routing for the segmented
anatomy: hands and feet are dedicated body-part nodes, armor
layering on arms / legs uses dotted sub-keys (``worn.upper``
for bracers, ``worn.lower`` for vambraces), and key vocabulary
collapses to a small generic set (``worn`` / ``held`` / ``outer``
/ ``accent``).

The EquipmentSlots enum values that items declare stay unchanged;
this file just re-routes each to its new (part, key) home. A
migration tool rewrites saved ``part_equipment`` docs to match.

Under Phase D:

- Weapons land on ``hand.*.held`` (moved from ``arm.*.held``).
- Gloves land on ``hand.*.worn``; rings on ``hand.*.ring.1``.
- Bracers and greaves live at ``{arm,leg}.*.worn.upper``;
  vambraces and shin-pieces at ``...worn.lower``.
- Boots move to ``foot.*.worn``.
- Capes, bandannas, masks use ``outer`` as the overlay layer.
- Amulets, belts, earrings, circlets use ``accent``.

Helper :func:`resolve_placements` still walks the item's mask
and returns a flat list of ``(part, key)`` placements — same
shape as before, just pointing at the new anatomy.
"""

from typing import Dict, List, Tuple

from caldanai.lib.rpg.helpers.enums import EquipmentSlots


# Phase D mapping. Bit values on the enum side carry the item's
# "which slot is this thing" metadata; this table translates each
# to the anatomical (part, key) home.
SLOT_TO_PART_KEY: Dict[EquipmentSlots, Tuple[str, str]] = {
    # Head + face layers.
    EquipmentSlots.HEAD:          ("head",       "worn"),
    EquipmentSlots.FACE:          ("head",       "outer"),
    # Ears: single accent slot each on head (per-side via dotted key).
    EquipmentSlots.LEFT_EAR:      ("head",       "earring.left"),
    EquipmentSlots.RIGHT_EAR:     ("head",       "earring.right"),
    # Torso layers.
    EquipmentSlots.TORSO:         ("torso",      "worn"),
    EquipmentSlots.CAPE:          ("torso",      "outer"),
    EquipmentSlots.WAIST:         ("torso",      "accent"),
    # Neck accessory.
    EquipmentSlots.NECK:          ("neck",       "accent"),
    EquipmentSlots.AMULET:        ("neck",       "accent"),
    # Arms — bracers on the upper arm layer, vambraces on the lower.
    EquipmentSlots.LEFT_ARM:      ("arm.left",   "worn.upper"),
    EquipmentSlots.RIGHT_ARM:     ("arm.right",  "worn.upper"),
    EquipmentSlots.LEFT_FOREARM:  ("arm.left",   "worn.lower"),
    EquipmentSlots.RIGHT_FOREARM: ("arm.right",  "worn.lower"),
    # Hands — weapons held, gloves worn, rings on ring.1 (first
    # slot). The migration can later route second rings to ring.2
    # if an item explicitly lands there.
    EquipmentSlots.LEFT_HELD:     ("hand.left",  "held"),
    EquipmentSlots.RIGHT_HELD:    ("hand.right", "held"),
    EquipmentSlots.LEFT_GLOVE:    ("hand.left",  "worn"),
    EquipmentSlots.RIGHT_GLOVE:   ("hand.right", "worn"),
    EquipmentSlots.LEFT_RING:     ("hand.left",  "ring.1"),
    EquipmentSlots.RIGHT_RING:    ("hand.right", "ring.1"),
    # Legs — greaves on upper, shin-pieces on lower.
    EquipmentSlots.LEFT_LEG:      ("leg.left",   "worn.upper"),
    EquipmentSlots.RIGHT_LEG:     ("leg.right",  "worn.upper"),
    EquipmentSlots.LEFT_SHIN:     ("leg.left",   "worn.lower"),
    EquipmentSlots.RIGHT_SHIN:    ("leg.right",  "worn.lower"),
    # Feet — boots.
    EquipmentSlots.LEFT_FOOT:     ("foot.left",  "worn"),
    EquipmentSlots.RIGHT_FOOT:    ("foot.right", "worn"),
}


# One-to-many placements. Empty in Phase D: the sided-slot rework
# from pre-D already eliminated the old pair entries. Kept as a
# future hook for set-required items (manacles, paired bracelets
# that must land on both hands simultaneously).
SLOT_PAIR: Dict[EquipmentSlots, List[Tuple[str, str]]] = {}


# Flattened: every ``(part, key)`` placement an item CAN land at.
# Used by display / migration code that needs to enumerate every
# valid home.
ALL_PLACEMENTS: List[Tuple[str, str]] = sorted(
    set(
        list(SLOT_TO_PART_KEY.values())
        + [p for pairs in SLOT_PAIR.values() for p in pairs]
    )
)


# Head-to-toe rendering order for ``$gear`` / equipment embeds.
# Keeps the display stable across migrations and anatomy changes.
PLACEMENT_DISPLAY_ORDER: List[Tuple[str, str]] = [
    ("head",       "worn"),
    ("head",       "outer"),
    ("head",       "earring.left"),
    ("head",       "earring.right"),
    ("head",       "accent"),
    ("neck",       "accent"),
    ("torso",      "worn"),
    ("torso",      "outer"),
    ("torso",      "accent"),
    ("arm.left",   "worn.upper"),
    ("arm.right",  "worn.upper"),
    ("arm.left",   "worn.lower"),
    ("arm.right",  "worn.lower"),
    ("hand.left",  "held"),
    ("hand.right", "held"),
    ("hand.left",  "worn"),
    ("hand.right", "worn"),
    ("hand.left",  "ring.1"),
    ("hand.left",  "ring.2"),
    ("hand.right", "ring.1"),
    ("hand.right", "ring.2"),
    ("leg.left",   "worn.upper"),
    ("leg.right",  "worn.upper"),
    ("leg.left",   "worn.lower"),
    ("leg.right",  "worn.lower"),
    ("foot.left",  "worn"),
    ("foot.right", "worn"),
]


def resolve_placements(slots_mask: EquipmentSlots) -> List[Tuple[str, str]]:
    """Expand an item's ``slots`` mask into a flat list of every
    ``(part_name, key)`` the item should occupy.

    Ordering: deterministic (iteration order of
    :data:`SLOT_TO_PART_KEY` + :data:`SLOT_PAIR`, which is
    head-to-toe). Callers that want display order should use
    :data:`PLACEMENT_DISPLAY_ORDER` instead.

    Duplicates are collapsed — an item declaring both
    ``AMULET | NECK`` (both map to ``("neck", "accent")``)
    returns the placement once.
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
    from both lookup tables. Pre-B3 this seeded the player's nested
    placement dict; post-B3 each Equippable node self-inits its
    :attr:`placements` so the caller is mostly migration tooling
    and fuzzy-matching helpers."""
    keys: List[str] = []
    seen = set()

    for placement in ALL_PLACEMENTS:
        p, k = placement
        if p == part_name and k not in seen:
            keys.append(k)
            seen.add(k)

    return keys
