"""Size-scaled dice defaults for body-part actions.

Each active body-part plugin declares ``DEFAULT_ACTIONS`` with a
``dice`` field that should scale with creature size so a naked
goblin's ``bite`` works without a creature-level override and a
dragon's baseline bite is size-appropriate. The ``dice`` field on
any part-default entry stays as a plain string (``"1d4"``) —
``size_scaled_dice`` is the helper that builds that string from
``(action_name, Size)`` at populate time, or it can be called
dynamically from a ``get_dice`` callable when a creature needs
runtime scaling.

The per-action tier tables below are the balance knobs. Numbers
are deliberately modest — these are the *base* every creature
starts from, with creature-level ``ACTION_REPERTOIRE`` overrides
layering flavor on top.
"""

from typing import Dict

from caldanai.lib.rpg.helpers.enums import Size


# Per-action dice-by-size. Keys follow the action names shipped in
# Phase 3 (head/arm/leg/tail/wing/torso DEFAULT_ACTIONS). Missing
# combinations fall through to ``_FALLBACK`` below — a sensible
# MEDIUM=1d4 scale that keeps "unknown action" safe for tests and
# for any future action that hasn't declared its own tier.
_ACTION_TIERS: Dict[str, Dict[Size, str]] = {
    # Head
    "bite": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d3",
        Size.MEDIUM:   "1d4",
        Size.LARGE:    "1d6",
        Size.HUGE:     "1d8",
        Size.COLOSSAL: "2d6",
    },
    "headbutt": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d2",
        Size.MEDIUM:   "1d3",
        Size.LARGE:    "1d4",
        Size.HUGE:     "1d6",
        Size.COLOSSAL: "2d4",
    },
    # Arm
    "punch": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d2",
        Size.MEDIUM:   "1d3",
        Size.LARGE:    "1d4",
        Size.HUGE:     "1d6",
        Size.COLOSSAL: "2d4",
    },
    "grab": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d2",
        Size.MEDIUM:   "1d2",
        Size.LARGE:    "1d3",
        Size.HUGE:     "1d4",
        Size.COLOSSAL: "1d6",
    },
    # Leg
    "kick": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d3",
        Size.MEDIUM:   "1d3",
        Size.LARGE:    "1d4",
        Size.HUGE:     "1d6",
        Size.COLOSSAL: "2d4",
    },
    # Stomp scales faster than kick — heavy attack for heavy mass.
    "stomp": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d3",
        Size.MEDIUM:   "1d4",
        Size.LARGE:    "1d8",
        Size.HUGE:     "2d6",
        Size.COLOSSAL: "3d6",
    },
    # Tail
    "tail_swipe": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d3",
        Size.MEDIUM:   "1d4",
        Size.LARGE:    "1d6",
        Size.HUGE:     "2d4",
        Size.COLOSSAL: "2d6",
    },
    "tail_slam": {
        Size.TINY:     "1d3",
        Size.SMALL:    "1d4",
        Size.MEDIUM:   "1d6",
        Size.LARGE:    "1d8",
        Size.HUGE:     "2d6",
        Size.COLOSSAL: "3d6",
    },
    # Wing
    "wing_buffet": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d3",
        Size.MEDIUM:   "1d4",
        Size.LARGE:    "1d6",
        Size.HUGE:     "1d8",
        Size.COLOSSAL: "2d6",
    },
    # Torso
    "chestbutt": {
        Size.TINY:     "1d2",
        Size.SMALL:    "1d3",
        Size.MEDIUM:   "1d4",
        Size.LARGE:    "1d6",
        Size.HUGE:     "2d4",
        Size.COLOSSAL: "2d6",
    },
}

_FALLBACK: Dict[Size, str] = {
    Size.TINY:     "1d2",
    Size.SMALL:    "1d3",
    Size.MEDIUM:   "1d4",
    Size.LARGE:    "1d6",
    Size.HUGE:     "1d8",
    Size.COLOSSAL: "2d6",
}


def size_scaled_dice(action_name: str, size: Size) -> str:
    """Return the default dice string for ``action_name`` at ``size``.

    Unknown action names fall through to a generic MEDIUM=1d4 scale
    so test fixtures and future actions without a dedicated tier
    still resolve to something sensible."""
    tier = _ACTION_TIERS.get(action_name, _FALLBACK)
    return tier.get(size, _FALLBACK[Size.MEDIUM])
