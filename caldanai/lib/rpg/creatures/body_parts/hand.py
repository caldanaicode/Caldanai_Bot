"""Hand body part plugin.

A dedicated hand node under each arm in the segmented anatomy
(Phase D). Holds weapons and gloves + rings — the real "end of
the arm" from a gameplay standpoint, separate from the arm
segment itself so armor localization and reachability semantics
work cleanly.

Design rationale
================

``health_max = "1d6"``
    Hands are small and break readily — a solid hit to a finger
    disarms a swordsman quickly. Lower HP than the arm they hang
    off (arm is 2d8) but not as fragile as an eye (1d6 but
    SOFT_PART exposure).

``is_critical = False``
    You can live without a hand. Destroying one drops it to
    USELESS, which (under the Phase B1 reachability semantics)
    doesn't unreach anything below — hands are tree leaves. The
    per-part drop-gear hook clears the weapon / glove / rings
    back to inventory.

Exposure
    Moderate across reaches — hands are center-mass in typical
    combat stances (held out to wield a weapon or gesture).
    Slightly lower in MELEE than torso because attackers swing
    for center of mass by default, not at outstretched hands.
    RANGED is higher: archers can line up on a prominent hand
    if they want to disarm.

Debuffs
    Losing a hand means losing the weapon it holds. The
    ATTACK-on-USELESS debuff captures the residual fumbling of
    whatever's left — a one-handed swing after losing the
    dominant hand isn't zero but isn't full power either.

Mixins
    ``Offensive`` (future punch / grapple actions — empty for
    now, creature-specific content can override), ``Equippable``
    (weapons, gloves, rings).
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.mixins import Equippable, Offensive
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class HandPlugin(BodyPartPlugin, Offensive, Equippable):
    """Hand as a depth-2 child of arm. Holds weapons + gloves + rings."""

    # Phase D placement keys. Weapons and shields go in ``held``;
    # gloves in ``worn``; paired rings via dotted keys so multiple
    # can coexist on one hand without a per-finger anatomy.
    PLACEMENT_KEYS = ["held", "worn", "ring.1", "ring.2"]

    name = "hand"
    health_max = "1d6"
    is_critical = False
    bleed_rate = 0.3
    exposure = {
        Reach.MELEE:  0.5,
        Reach.REACH:  0.5,
        Reach.THROWN: 0.4,
        Reach.RANGED: 0.6,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.ATTACK: -1},
        InjuryLevels.MODERATE: {Stat.ATTACK: -2},
        InjuryLevels.SEVERE:   {Stat.ATTACK: -3},
        InjuryLevels.USELESS:  {Stat.ATTACK: -5},
    }
