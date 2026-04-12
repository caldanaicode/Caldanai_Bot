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

``health_max = "1d6"``
    Tails are smaller and more fragile than limbs (arms are 1d8, legs
    are 1d10). They're easier to sever, which matches both the
    biological reality and the Monster Hunter loot convention where
    tails are a notably high-yield severable part.

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
      *do* deal damage -- a scorpion's sting, a dragon's tail slap, a
      manticore's spine throw -- should subclass ``TailPlugin`` and
      declare their own ATTACK debuff. Keeping the base class neutral
      lets it compose cleanly on any creature that has a tail, and
      prevents accidentally penalizing attack rolls on creatures whose
      tails aren't combat appendages.

    - **No DEFENSE debuff.** Defense debuffs are the arm's SEVERE
      niche (parry loss). A tail has nothing to do with blocking or
      parrying.

    The -5 USELESS DODGE can exceed a low base dodge value; the
    ``Creature.get_dodge()`` getter applies a ``max(0, ...)`` clamp
    (item 1.10) so the modifier bottoms out the effective dodge at 0
    without going negative.

Doppelganger pain cries
    One flavor string per injury level, escalating from a twinge to a
    limp, unresponsive tail. The design doc wants per-part
    doppelganger cries on every base part.
"""

from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class TailPlugin(BodyPartPlugin):
    """Generic tail. Non-critical. DODGE-only debuffs (balance organ).

    Tails provide balance and, for some creatures, a secondary attack
    appendage. The base ``TailPlugin`` only models the balance
    contribution: losing tail control debuffs DODGE and nothing else.
    Specialty tails that deliver attacks (scorpion sting, dragon tail
    slap, manticore spine throw) should subclass and declare their own
    ATTACK debuff -- keeping the base class DODGE-only lets it compose
    cleanly on any creature with a tail.

    Severed tails are classic Monster Hunter loot and feed directly
    into Phase 2 crafting.
    """

    name = "tail"
    health_max = "1d6"
    is_critical = False
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

    def get_doppelganger_pain_cry(self, level: InjuryLevels) -> str:
        return {
            InjuryLevels.MINOR: (
                "@1 flicks @1a tail and winces at an unexpected twinge."
            ),
            InjuryLevels.MODERATE: (
                "@1's tail lashes erratically as unseen damage works "
                "its way down the vertebrae."
            ),
            InjuryLevels.SEVERE: (
                "@1 yelps as @1a tail bends at a sickening angle, "
                "blood matting the fur."
            ),
            InjuryLevels.USELESS: (
                "@1's tail drops limp and still, a final twitch "
                "betraying its uselessness as the imitation sets."
            ),
        }.get(level, "")
