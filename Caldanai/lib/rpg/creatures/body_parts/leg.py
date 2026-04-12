"""Generic ``LegPlugin`` -- Phase 1.B item 2.4.

The fourth base body-part plugin and the second *non-critical* base
part (after the arm). Where the arm (2.3) carries the primary ATTACK
debuff, the leg carries the primary DODGE debuff -- legs are the
mobility and footwork limb, and a hobbled leg cripples evasion more
than anything else. A secondary ATTACK penalty accounts for the loss
of kicks and the inability to brace for a swing.

Design rationale
================

``health_max = "1d10"``
    Legs are slightly larger than arms (1d8) and are the sturdiest
    limb. The design doc's leg example uses 1d10 and we match it.

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

Doppelganger pain cries
    One flavor string per injury level, escalating from a phantom ache
    in the thigh to a twisted, limp leg dragging uselessly behind.
    The design doc explicitly wants per-part doppelganger cries on
    every base part.
"""

from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class LegPlugin(BodyPartPlugin):
    """Generic leg. Non-critical. Primary DODGE contributor, secondary ATTACK.

    Legs drive both mobility (DODGE -- footwork, repositioning) and
    kicking attacks. A hobbled leg cripples evasion more than anything
    else, with a secondary impact on ATTACK from the loss of kicks and
    the inability to brace for a swing. Exposure is uniform in melee
    (you can't NOT hit a leg with a sword) but drops at range -- legs
    are awkward targets for bows and thrown weapons, which naturally
    land higher on the body.
    """

    name = "leg"
    health_max = "1d10"
    is_critical = False
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

    def get_doppelganger_pain_cry(self, level: InjuryLevels) -> str:
        return {
            InjuryLevels.MINOR: (
                "@1 favors one leg as a phantom ache shoots up @1a "
                "thigh."
            ),
            InjuryLevels.MODERATE: (
                "@1 staggers slightly, knee buckling beneath @1a own "
                "weight."
            ),
            InjuryLevels.SEVERE: (
                "@1 cries out as @1a leg twists at an impossible "
                "angle, bone pressing through the skin."
            ),
            InjuryLevels.USELESS: (
                "@1's leg goes limp, dragging uselessly behind as the "
                "imitation's crippling finishes."
            ),
        }.get(level, "")
