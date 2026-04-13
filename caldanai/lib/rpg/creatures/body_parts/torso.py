"""Generic ``TorsoPlugin`` — Phase 1.B item 2.2.

The second base body-part plugin. Where ``HeadPlugin`` is the "awkward
to hit but deadly if you do" critical part, the torso is the *other*
critical part: the bulk of the body, where the vital organs live.
Destroying it kills the creature the same way a head loss would.

Design rationale
================

``health_max = "2d10"``
    Torsos are the largest body part on any creature and should be
    substantially tougher than the extremities. Heads are ``1d8`` (item
    2.1); limbs will be around ``1d10``; the torso sits above both as
    the last thing standing when a creature has been whittled down.
    ``2d10`` ranges from 2 to 20 with a strong central tendency around
    11, which leaves room for high-dice-string monsters (dragons,
    giants) to still scale linearly above the baseline.

Exposure uniformly 1.0
    The torso is the easiest thing to hit from any angle. Unlike the
    head (which you have to swing up past a torso to reach in melee) or
    a leg (which is low-profile at range), the full body is one giant
    torso-shaped target. All four reach types therefore sit at the
    ceiling of 1.0.

Debuffs touching ATTACK, DEFENSE, and DODGE
    The torso is the only base part so far that debuffs all three core
    combat stats simultaneously. Rationale: breathing, balance, and
    twist/dodge motion all come from the core. A bruised or punctured
    torso compromises every major combat action at once — you can't
    swing hard, you can't set your feet to block, you can't rotate out
    of an incoming strike. Numbers are placeholders per the design
    doc's balance-is-a-playtest-question note, but the *shape* (all
    three stats degrading together) is the architectural claim this
    plugin makes.

``InjuryLevels.USELESS`` row
    Unreachable for a critical part in the current damage-routing
    model — ``Creature.apply_damage`` sets ``self.health = 0`` the
    moment a critical part is destroyed, so the debuff table never
    consults the USELESS row for a torso. Listed anyway for symmetry
    with non-critical parts and as a safety net for any future design
    change (non-lethal torso destruction, downed-but-alive captures)
    that makes the row reachable.

Doppelganger pain cries
    One flavor string per injury level, escalating from ribs to
    visible chest bruising to actively-seeping wounds to a full chest
    cavity collapse. The design doc explicitly wants per-part
    doppelganger cries on every base part.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import InjuryLevels, Reach, Stat


class TorsoPlugin(BodyPartPlugin):
    """Generic torso. Critical — losing it kills the creature.

    The torso houses the vital organs; destroying it means the creature
    dies the same way a head loss would. Unlike the head, the torso is
    the largest, most-exposed part of any creature and has the highest
    exposure across all reach types.
    """

    name = "torso"
    health_max = "2d10"
    is_critical = True
    exposure = {
        Reach.MELEE:  1.0,
        Reach.REACH:  1.0,
        Reach.THROWN: 1.0,
        Reach.RANGED: 1.0,
    }
    debuffs = {
        InjuryLevels.MINOR:    {Stat.ATTACK: -1},
        InjuryLevels.MODERATE: {
            Stat.ATTACK: -2,
            Stat.DEFENSE: -1,
            Stat.DODGE: -1,
        },
        InjuryLevels.SEVERE:   {
            Stat.ATTACK: -3,
            Stat.DEFENSE: -2,
            Stat.DODGE: -2,
        },
        # USELESS is unreachable for a torso because ``is_critical=True``
        # kills the creature the moment the part is destroyed, before
        # the debuff table is consulted. Listed for symmetry and as a
        # safety net for any future design change that allows non-lethal
        # torso destruction.
        InjuryLevels.USELESS:  {
            Stat.ATTACK: -5,
            Stat.DEFENSE: -4,
            Stat.DODGE: -4,
        },
    }

