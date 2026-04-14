"""Generic ``HeadPlugin`` — Phase 1.B item 2.1.

The first real body-part plugin, exercising the full Phase 1.A
foundation end-to-end: plugin discovery via
``BodyPartPlugin.load_plugins``, the ``BodyPart.make("head")`` factory
lookup, per-instance composition, ``is_critical`` death routing in
``Creature.apply_damage``, exposure-weighted targeting, injury-level
debuffs aggregated by ``Creature.get_stat_modifier_total``, and the
doppelganger per-part pain cry hook.

Design rationale
================

``health_max = "3d10"``
    Heads are critical parts — destruction kills the creature — so
    their HP needs to reflect the stakes. Post-Q.5-rebalance baseline
    gives heads ~17 avg HP at MEDIUM, scaling up to ~66 avg on HUGE
    creatures via size.hp_scale. This makes head-targeting a real
    tactical commitment rather than an instakill exploit.

Exposure values
    The four reaches fan out from 0.7 → 1.0 across melee → ranged
    because a head is *awkward* to target in melee (you have to swing
    up past the torso) but a perfectly fine target for an archer who
    is deliberately aiming. Thrown weapons sit between the two, and
    reach weapons (polearms, whips) get a small bonus over melee
    because extended weapons have an easier line on the head.

Debuffs
    Head injuries impair attack (brain fog, concussion) and hit chance
    (vision / spatial reasoning). Dodge is unaffected — dodging is a
    body / leg concern.

``InjuryLevels.USELESS`` row
    Unreachable for a critical part in the current damage-routing
    model, because ``Creature.apply_damage`` sets ``self.health = 0``
    (killing the creature) the moment a critical part is destroyed, so
    the debuff table never consults the USELESS row for a head. We
    still list it for symmetry with non-critical parts, and so that a
    future design change allowing non-lethal head destruction (stunned
    creatures, knocked-out-but-alive captures) inherits a sensible
    fallback.

Doppelganger pain cries
    One flavor string per injury level, escalating in visceral
    intensity. The doppelganger detail is one of the standout features
    of Phase 1 and the design doc explicitly wants per-part cries on
    every base part.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class HeadPlugin(BodyPartPlugin):
    """Generic head. Critical — losing it kills the creature.

    Monsters override exposure via factory kwargs for narrower
    targeting profiles (e.g. dragon heads).
    """

    name = "head"
    health_max = "3d10"
    is_critical = True
    exposure = {
        Reach.MELEE:  0.7,
        Reach.REACH:  0.8,
        Reach.THROWN: 0.9,
        Reach.RANGED: 1.0,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.ATTACK: -1},
        InjuryLevels.MODERATE: {Stat.ATTACK: -2, Stat.HIT: -1},
        InjuryLevels.SEVERE:   {Stat.ATTACK: -3, Stat.HIT: -2},
        # USELESS is unreachable for a head because ``is_critical=True``
        # kills the creature the moment the part is destroyed, before
        # the debuff table is consulted. Listed for symmetry and as a
        # safety net for any future design change that allows non-lethal
        # head destruction.
        InjuryLevels.USELESS:  {Stat.ATTACK: -5, Stat.HIT: -4},
    }

