"""Generic ``LegPlugin`` -- Phase 1.B item 2.4.

The fourth base body-part plugin and the second *non-critical* base
part (after the arm). Where the arm (2.3) carries the primary ATTACK
debuff, the leg carries the primary DODGE debuff -- legs are the
mobility and footwork limb, and a hobbled leg cripples evasion more
than anything else. A secondary ATTACK penalty accounts for the loss
of kicks and the inability to brace for a swing.

Design rationale
================

``health_max = "2d10"``
    Legs are slightly larger than arms (2d8) — the sturdiest limb,
    bearing the creature's weight. Post-Q.5 rebalance: ~11 avg at
    MEDIUM, ~44 on HUGE. Leg destruction cripples dodge via the
    emergence system (mobility sources), not via flat debuffs.

``is_critical = False``
    You can lose a leg and live -- you'll just be useless in combat.
    Destroying a leg drops it to ``InjuryLevels.USELESS`` but does
    *not* kill the creature. In the current ``Creature.apply_damage``
    routing, this means the body still only takes
    ``BODY_DAMAGE_FRACTION`` (0.5) of the final damage, and the
    ``is_critical`` death short-circuit doesn't fire. The USELESS
    debuff row is therefore *reachable* for legs (unlike head/torso,
    where the creature dies before the row is ever consulted) and
    needs to be a real, balanced row.

Exposure (melee-uniform, range-reduced)
    - ``MELEE: 1.0`` and ``REACH: 1.0`` -- a sword swing or polearm
      naturally has the angle. You can't NOT hit a leg with a sword
      once you're in the fight. Both reach bands are uniform at 1.0.
    - ``THROWN: 0.7`` -- a javelin or thrown knife in flight is
      slightly less likely to land on a leg than on the torso; a
      thrower naturally aims center-mass or higher.
    - ``RANGED: 0.7`` -- arrows and bolts travel a flatter, more
      deliberate line and archers aim for the center of the target.
      Legs are awkward ranged targets.

    The design-doc sketch listed only MELEE/THROWN/RANGED (omitting
    REACH). We populate ``Reach.REACH`` explicitly at 1.0 to match
    MELEE so that every reach has an unambiguous value and the plugin
    never falls through to a default.

Debuffs
    - ``MINOR: DODGE -1`` -- a bruised leg slows footwork slightly.
      ATTACK is untouched at this level (you can still throw a solid
      kick on a lightly-hurt leg).
    - ``MODERATE: DODGE -3, ATTACK -1`` -- a limping leg hurts both
      evasion and the ability to brace or kick. The ATTACK penalty
      starts here, small.
    - ``SEVERE: DODGE -5, ATTACK -2`` -- continues the linear scaling.
    - ``USELESS: DODGE -10, ATTACK -4`` -- a destroyed leg is
      catastrophic for DODGE (jumping past the linear scaling: a
      useless leg is strictly worse than a merely severe one, to the
      point of making the creature near-undodgeable). ATTACK doubles
      off SEVERE to -4; kicks are gone entirely and bracing is
      impossible.

    DODGE is the headline and appears on every row. ATTACK is the
    secondary and skips MINOR. DEFENSE is never touched by leg
    debuffs -- that's the arm's SEVERE niche (parry loss).

    The -10 USELESS DODGE intentionally exceeds any reasonable base
    dodge value; the ``Creature.get_dodge()`` getter applies a
    ``max(0, ...)`` clamp (item 1.10) so the modifier bottoms out the
    effective dodge at 0 without going negative.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.mixins import Equippable, Mobility
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach, Stat


_KICK_TEMPLATES = [
    "@1D kicks @2 in the @2p_target.",
    "@1D lashes out with a boot at @2np @2p_target.",
    "@1D snaps a kick into @2np @2p_target.",
    "@1D whirls and kicks @2np @2p_target.",
    "@1D drives a heel into @2np @2p_target.",
    "@1D plants a solid kick across @2np @2p_target.",
]

_STOMP_TEMPLATES = [
    "@1D stomps down on @2np @2p_target.",
    "@1D brings @1a full weight down on @2np @2p_target.",
    "@1D raises a foot and slams it onto @2np @2p_target.",
    "@1D crushes @2np @2p_target underfoot.",
    "@1D grinds a heavy stomp into @2np @2p_target.",
    "@1D pounds @2np @2p_target into the ground.",
]


class LegPlugin(BodyPartPlugin, Mobility, Equippable):
    """Generic leg. Non-critical. Primary DODGE contributor, secondary ATTACK.

    Legs drive both mobility (DODGE -- footwork, repositioning) and
    kicking attacks. A hobbled leg cripples evasion more than anything
    else, with a secondary impact on ATTACK from the loss of kicks and
    the inability to brace for a swing. Exposure is uniform in melee
    (you can't NOT hit a leg with a sword) but drops at range -- legs
    are awkward targets for bows and thrown weapons, which naturally
    land higher on the body.
    """

    # Phase D placement keys: armor slots layered on the leg
    # via dotted sub-keys (``worn.upper`` holds a greave,
    # ``worn.lower`` a shin piece). Boot moved to the new
    # :class:`FootPlugin` at the next depth.
    PLACEMENT_KEYS = ["worn.upper", "worn.lower"]

    name = "leg"
    health_max = "2d10"
    is_critical = False
    bleed_rate = 0.3
    # No defense_bonus override — inherits default (0). Greaves
    # / shin-pieces contribute via local armor under ``worn.*``.
    exposure = {
        Reach.MELEE:  1.0,
        Reach.REACH:  1.0,
        Reach.THROWN: 0.7,
        Reach.RANGED: 0.7,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.DODGE: -1},
        InjuryLevels.MODERATE: {Stat.DODGE: -3, Stat.ATTACK: -1},
        InjuryLevels.SEVERE:   {Stat.DODGE: -5, Stat.ATTACK: -2},
        InjuryLevels.USELESS:  {Stat.DODGE: -10, Stat.ATTACK: -4},
    }
    DEFAULT_ACTIONS = {
        "kick": {
            "cost": 1,
            "weight": 2,
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.MELEE,
            "label": "kick",
            "narrative": _KICK_TEMPLATES,
        },
        "stomp": {
            "cost": 1,
            "weight": 1,
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.MELEE,
            "label": "stomp",
            "narrative": _STOMP_TEMPLATES,
        },
    }

