"""Foot body part plugin.

Depth-2 leaf under each leg in the segmented anatomy (Phase D).
Wears boots; contributes to DODGE as a mobility leaf through
the creature's ``Mobility`` emergence path (feet are where the
ground-contact actually happens — the leg above just positions
the foot). Quadrupeds reuse this plugin for paws; monster-
specific plugins can override narration without needing a
separate FootPlugin / PawPlugin split.

Design rationale
================

``health_max = "1d8"``
    Bigger than a hand (1d6) because feet carry body weight —
    the musculature and bone structure is denser. Smaller than
    the leg they hang off (2d10).

``is_critical = False``
    Losing a foot drops the creature to useless-one-side
    mobility but isn't a critical-death source. Reachability
    leaf; no descendants to unreach.

Exposure
    Low across melee / reach (feet are on the ground; attackers
    swing at center-mass). Higher in ranged because an archer
    can deliberately aim at a foot to cripple mobility from a
    distance.

Debuffs
    Foot injury hurts DODGE more than ATTACK — it's a mobility
    organ. Pattern matches the tail / leg DODGE-penalty bias.

Mixins
    ``Mobility`` (grounded; contributes to DODGE),
    ``Equippable`` (boots). No Offensive by default — feet
    aren't natural attack sources. Quadruped paw variants can
    override to add Offensive (claw attacks).
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.mixins import Equippable, Mobility
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class FootPlugin(BodyPartPlugin, Mobility, Equippable):
    """Foot as a depth-2 child of leg. Wears boots; grounded mobility."""

    PLACEMENT_KEYS = ["worn"]

    name = "foot"
    health_max = "1d8"
    is_critical = False
    bleed_rate = 0.3
    exposure = {
        Reach.MELEE:  0.3,
        Reach.REACH:  0.3,
        Reach.THROWN: 0.3,
        Reach.RANGED: 0.5,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.DODGE: -1},
        InjuryLevels.MODERATE: {Stat.DODGE: -2},
        InjuryLevels.SEVERE:   {Stat.DODGE: -3},
        InjuryLevels.USELESS:  {Stat.DODGE: -5},
    }
