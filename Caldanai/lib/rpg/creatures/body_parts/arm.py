"""Generic ``ArmPlugin`` -- Phase 1.B item 2.3.

The third base body-part plugin. Where ``HeadPlugin`` (2.1) and
``TorsoPlugin`` (2.2) are the two critical parts -- destroying them
kills the creature outright -- the arm is the first *non-critical*
base part. You can lose an arm and live.

Arms are the primary attack-enabling limbs, so their debuff profile is
heavy on ATTACK with a secondary DEFENSE impact once the injury is bad
enough that the arm can't parry anymore.

Design rationale
================

``health_max = "1d8"``
    Arms are smaller than the torso (2d10) but comparable in size to
    the head (1d8). The leg example in the design doc uses 1d10 and
    the wing example uses 1d8; arms sit naturally at 1d8 alongside
    wings and heads.

``is_critical = False``
    You can lose an arm and live. Destroying an arm drops it to
    ``InjuryLevels.USELESS`` but does *not* kill the creature. In the
    current ``Creature.apply_damage`` routing, this means the body
    still only takes ``BODY_DAMAGE_FRACTION`` (0.5) of the final
    damage, and the ``is_critical`` death short-circuit doesn't fire.
    The USELESS debuff row is therefore *reachable* for arms (unlike
    head/torso, where the creature dies before the row is ever
    consulted) and needs to be a real, balanced row.

Exposure (non-uniform, slightly reduced from torso)
    - ``MELEE: 0.8`` and ``REACH: 0.8`` -- arms tend to swing into
      swords, axes, and polearms as you attack or parry. Nearly as
      exposed as the torso, but not quite: some swings miss the arms
      entirely and land on the chest or shoulder proper.
    - ``THROWN: 0.7`` -- a thrown knife or javelin in flight is
      slightly less likely to hit an arm than a torso (the torso is
      the center of mass and the natural target), but arms still
      catch a fair share.
    - ``RANGED: 0.6`` -- arrows and bolts travel a flatter, more
      deliberate line. An archer aims center-mass; arms are the
      least-exposed reach for ranged weapons, but still hittable when
      the torso is blocked.

Debuffs
    - ``MINOR: ATTACK -1`` -- a bruised or cut arm still swings, but
      you pull your strikes slightly.
    - ``MODERATE: ATTACK -2`` -- ATTACK continues to scale linearly.
    - ``SEVERE: ATTACK -3, DEFENSE -1`` -- a broken arm can no longer
      parry reliably, so DEFENSE picks up a -1 penalty on top of the
      ATTACK scaling. This is the one place in the table where
      DEFENSE appears.
    - ``USELESS: ATTACK -5`` (plus ``"disable_slot": True``) -- a
      destroyed arm is effectively a dead weight. ATTACK jumps past
      the linear scaling (a useless arm is strictly worse than a
      merely severe one). DEFENSE is NOT listed in the USELESS row:
      once the arm is dead, it's no longer actively interfering with
      your parries, it's just absent -- so the parry penalty doesn't
      stack on top of the total absence.

The ``"disable_slot": True`` marker (forward-facing)
    The USELESS row mixes a ``Stat`` enum key (``Stat.ATTACK``) with a
    *string* key (``"disable_slot"``). This is deliberate.

    - Python lets you mix key types in a single dict.
    - The current stat-aggregation code in
      ``BodyPart.get_stat_modifier`` does
      ``self.debuffs.get(level, {}).get(stat, 0)`` with ``stat`` being
      a ``Stat`` enum member. String keys are never consulted and
      never contribute to any aggregation. The marker is *inert*
      under the current implementation.
    - A future equipment-integration item in a later phase will add
      logic roughly like
      ``if part.debuffs.get(level, {}).get("disable_slot"):
      disable_weapon_slot(part)`` so that a creature with a useless
      arm can no longer wield a weapon in the corresponding slot.
    - Until that item lands, the marker is forward-facing design
      that compiles and runs harmlessly. **Do not delete it as dead
      code** -- ``test_useless_row_has_disable_slot_marker`` pins it
      so any accidental deletion will trip the test suite.

    This pattern (mixed ``Stat``-enum + string keys in a debuff row)
    is expected to generalize to future non-stat side effects
    (``"blind"``, ``"grounded"``, ``"knockdown"``, etc.) without
    requiring a new data structure. Aggregation stays safe because it
    keys by enum; the side-effect consumers key by string.

Doppelganger pain cries
    One flavor string per injury level, escalating from a mysterious
    ache to a visibly twisted and limp arm. The design doc explicitly
    wants per-part doppelganger cries on every base part.
"""

from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class ArmPlugin(BodyPartPlugin):
    """Generic arm. Non-critical but load-bearing for combat.

    Arms are the primary attack-enabling limbs, so their debuff
    profile is heavy on ATTACK with a secondary DEFENSE impact at
    severe injury levels (a broken arm can't parry). The USELESS
    entry carries a ``"disable_slot": True`` marker that a future
    equipment-integration item will consume to disable the
    corresponding weapon slot; for now the marker is inert (the
    stat-aggregation code ignores non-Stat keys in debuff rows, so
    its presence is forward-compatible but has no current effect).
    """

    name = "arm"
    health_max = "1d8"
    is_critical = False
    exposure = {
        Reach.MELEE:  0.8,
        Reach.REACH:  0.8,
        Reach.THROWN: 0.7,
        Reach.RANGED: 0.6,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.ATTACK: -1},
        InjuryLevels.MODERATE: {Stat.ATTACK: -2},
        InjuryLevels.SEVERE:   {Stat.ATTACK: -3, Stat.DEFENSE: -1},
        # "disable_slot" is a forward-facing marker consumed by a
        # future equipment-integration item. It is a *string* key in
        # a dict that otherwise holds ``Stat`` enum keys; the current
        # stat-aggregation code ignores non-Stat keys, so the marker
        # is inert under today's implementation but pinned by
        # ``test_useless_row_has_disable_slot_marker``.
        InjuryLevels.USELESS:  {Stat.ATTACK: -5, "disable_slot": True},
    }

    def get_doppelganger_pain_cry(self, level: InjuryLevels) -> str:
        return {
            InjuryLevels.MINOR: (
                "@1 flexes @1a arm and winces at an ache that wasn't "
                "there moments ago."
            ),
            InjuryLevels.MODERATE: (
                "@1's arm twists at an unnatural angle as sinews pop "
                "beneath @1a skin."
            ),
            InjuryLevels.SEVERE: (
                "@1 howls as @1a arm hangs limp, bone pressing visibly "
                "against skin."
            ),
            InjuryLevels.USELESS: (
                "@1's arm crumples grotesquely, fingers curling into a "
                "useless claw as the imitation completes."
            ),
        }.get(level, "")
