"""Generic ``TailPlugin`` -- Phase 1.B item 2.6.

The sixth base body-part plugin and a non-critical part used by
quadrupeds, reptiles, some monkeys, and many monsters. Tails provide
balance and occasionally serve as a secondary attack appendage (tail
whip, sting, spine throw), but the *base* ``TailPlugin`` only models
the balance contribution -- the primary combat contribution is
**DODGE**. Losing tail control throws a creature off-balance and makes
them slower to react.

Severed tails are classic Monster Hunter loot and feed directly into
Phase 2 crafting, so getting the base plugin in place now (even for a
non-critical part) is important downstream.

Design rationale
================

``health_max = "1d10"``
    Tails are smaller and more fragile than limbs (arms are 2d8, legs
    are 2d10). They're easier to sever, which matches both the
    biological reality and the Monster Hunter loot convention where
    tails are a notably high-yield severable part. Post-Q.5 rebalance:
    ~5 avg at MEDIUM, ~22 on HUGE.

``is_critical = False``
    You can live without your tail. Destroying a tail drops it to
    ``InjuryLevels.USELESS`` but does *not* kill the creature. In the
    current ``Creature.apply_damage`` routing this means the body only
    takes ``BODY_DAMAGE_FRACTION`` (0.5) of the final damage and the
    ``is_critical`` death short-circuit does not fire. The USELESS
    debuff row is therefore reachable and needs to be a real row.

Exposure (uniformly lower than other parts)
    - ``MELEE: 0.5`` -- a tail is a mobile, off-center target that
      creatures naturally tuck or swish out of the way. Harder to hit
      up close than an arm or leg.
    - ``REACH: 0.6`` -- reach weapons (polearms, spears) gain a slight
      angle advantage over short weapons against a flicking tail, but
      it's still a low-priority target versus center-mass.
    - ``THROWN: 0.6`` -- thrown weapons are less likely to land on a
      tail than on the torso; throwers naturally aim center-mass.
    - ``RANGED: 0.6`` -- arrows and bolts travel a flatter, more
      deliberate line and archers aim for the center of the target. A
      tail silhouette is still visible at distance even if harder to
      hit up close, which is why ranged matches thrown/reach rather
      than dropping below melee.

    All four reach keys are populated explicitly so the plugin never
    falls through to a default.

Debuffs (DODGE-only, by design)
    - ``MINOR: DODGE -1`` -- a bruised tail throws off balance slightly.
    - ``MODERATE: DODGE -2`` -- a damaged tail lashes erratically and
      the creature's footwork suffers.
    - ``SEVERE: DODGE -3`` -- a shattered tail cripples balance.
    - ``USELESS: DODGE -5`` -- a severed or destroyed tail. The
      creature is permanently off-balance; dodge is significantly
      reduced but not as catastrophically as a useless leg (-10),
      because the creature still has its limbs for footwork.

    **Contract pin**: DODGE is the *only* stat the base tail touches.

    - **No ATTACK debuff.** A base tail does not swing weapons or
      deliver blows as part of normal attacks. Specialty tails that
      *do* deal damage should subclass ``TailPlugin`` and declare their
      own ATTACK debuff. Keeping the base class neutral lets it compose
      cleanly on any creature that has a tail, and prevents
      accidentally penalizing attack rolls on creatures whose tails
      aren't combat appendages.

    - **No DEFENSE debuff.** Defense debuffs are the arm's SEVERE
      niche (parry loss). A tail has nothing to do with blocking or
      parrying.

    The -5 USELESS DODGE can exceed a low base dodge value; the
    ``Creature.get_dodge()`` getter applies a ``max(0, ...)`` clamp
    (item 1.10) so the modifier bottoms out the effective dodge at 0
    without going negative.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach, Stat


_TAIL_SWIPE_TEMPLATES = [
    "@1D lashes @1a tail across @2np @2p_target.",
    "@1D whips @1a tail into @2np @2p_target.",
    "@1D sweeps @1a tail through @2np @2p_target.",
    "@1D snaps @1a tail at @2np @2p_target.",
    "@1D cracks @1a tail against @2np @2p_target.",
    "@1D lashes sideways, @1a tail catching @2np @2p_target.",
]

_TAIL_SLAM_TEMPLATES = [
    "@1D slams @1a tail down on @2np @2p_target.",
    "@1D arcs @1a tail overhead and crashes it onto @2np @2p_target.",
    "@1D swings @1a tail like a club into @2np @2p_target.",
    "@1D drives @1a heavy tail into @2np @2p_target.",
    "@1D brings @1a tail down with full force on @2np @2p_target.",
    "@1D hammers @2np @2p_target with the bulk of @1a tail.",
]


class TailPlugin(BodyPartPlugin):
    """Generic tail. Non-critical. DODGE-only debuffs (balance organ).

    Tails provide balance and, for some creatures, a secondary attack
    appendage. The base ``TailPlugin`` only models the balance
    contribution: losing tail control debuffs DODGE and nothing else.
    Specialty tails that deliver attacks should subclass and declare
    their own ATTACK debuff -- keeping the base class DODGE-only lets
    it compose cleanly on any creature with a tail.

    Severed tails are classic Monster Hunter loot and feed directly
    into Phase 2 crafting.
    """

    name = "tail"
    health_max = "1d10"
    is_critical = False
    bleed_rate = 0.2
    # No defense_bonus override — inherits default (0). Tail
    # carries full base defense for non-specialized creatures.
    exposure = {
        Reach.MELEE:  0.5,
        Reach.REACH:  0.6,
        Reach.THROWN: 0.6,
        Reach.RANGED: 0.6,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.DODGE: -1},
        InjuryLevels.MODERATE: {Stat.DODGE: -2},
        InjuryLevels.SEVERE:   {Stat.DODGE: -3},
        InjuryLevels.USELESS:  {Stat.DODGE: -5},
    }
    DEFAULT_ACTIONS = {
        "tail_swipe": {
            "cost": 1,
            "weight": 2,
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.REACH,
            "label": "tail swipe",
            "narrative": _TAIL_SWIPE_TEMPLATES,
        },
        "tail_slam": {
            "cost": 1,
            "weight": 1,
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.REACH,
            "label": "tail slam",
            "narrative": _TAIL_SLAM_TEMPLATES,
        },
    }

