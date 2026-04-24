"""Generic ``HeadPlugin`` — Phase 1.B item 2.1.

The first real body-part plugin, exercising the full Phase 1.A
foundation end-to-end: plugin discovery via
``BodyPartPlugin.load_plugins``, the ``BodyPart.make("head")`` factory
lookup, per-instance composition, ``is_critical`` death routing in
``Creature.apply_damage``, exposure-weighted targeting, and
injury-level debuffs aggregated by
``Creature.get_stat_modifier_total``.

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
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.mixins import Equippable, Offensive, Sensory
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach, Stat


_BITE_TEMPLATES = [
    "@1D bites @2np @2p_target.",
    "@1D sinks @1a teeth into @2np @2p_target.",
    "@1D snaps at @2, jaws closing on @2a @2p_target.",
    "@1D lunges, jaws wide, and catches @2np @2p_target.",
    "@1D clamps down on @2np @2p_target.",
    "@1D darts forward and tears at @2np @2p_target.",
    "@1D bares @1a teeth and bites into @2np @2p_target.",
]

_HEADBUTT_TEMPLATES = [
    "@1D drives @1a skull into @2np @2p_target.",
    "@1D slams @1a head against @2np @2p_target.",
    "@1D throws @1a weight forward and headbutts @2np @2p_target.",
    "@1D cracks @1a forehead into @2np @2p_target.",
    "@1D lowers @1a head and rams @2np @2p_target.",
    "@1D pitches forward, skull-first, into @2np @2p_target.",
]


class HeadPlugin(BodyPartPlugin, Offensive, Sensory, Equippable):
    """Generic head. Critical — losing it kills the creature.

    Monsters override exposure via factory kwargs for narrower
    targeting profiles (see individual monster classes).

    Mixins: ``Offensive`` (bite / headbutt actions), ``Sensory``
    (fallback HIT source when no eyes — ``IS_PRIMARY_SENSE=False``),
    ``Equippable`` (worn / outer / earring placements).
    """

    # Sensory: head is the FALLBACK perception source. When a
    # creature has eye parts, those are primary and heads
    # contribute nothing to HIT. Only eye-less humanoids (goblin,
    # skeleton, vampire, etc.) use the head for HIT emergence.
    IS_PRIMARY_SENSE = False

    # Phase D placement keys. Under the generic-key scheme:
    # ``worn`` is the main head armor (helm / cowl); ``outer``
    # is an overlay (bandanna / mask / hood); per-side earrings
    # land on ``earring.left`` / ``earring.right`` (dotted keys
    # carry the side without needing ear parts in the tree);
    # ``accent`` holds circlets / crowns / tiaras.
    PLACEMENT_KEYS = ["worn", "outer", "earring.left", "earring.right", "accent"]

    name = "head"
    health_max = "3d10"
    is_critical = True
    bleed_rate = 0.6
    # No defense_bonus override — inherits default (0). Helms go
    # in the ``worn`` placement and contribute via local armor.
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
    DEFAULT_ACTIONS = {
        "bite": {
            "cost": 1,
            "weight": 2,
            "dmg_type": DamageTypes.PIERCING,
            "reach": Reach.MELEE,
            "label": "bite",
            "narrative": _BITE_TEMPLATES,
        },
        "headbutt": {
            "cost": 1,
            "weight": 1,
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.MELEE,
            "label": "headbutt",
            "narrative": _HEADBUTT_TEMPLATES,
        },
    }

