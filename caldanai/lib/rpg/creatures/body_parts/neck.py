"""Minimal ``NeckPlugin`` -- added 2026-04-21 with the equipment-
on-parts migration.

The neck is a vestigial body part right now: every equipped
creature needs a ``neck`` to land amulets / jewelry on, but no
content in the bestiary drives neck-specific mechanics yet. This
plugin is the minimum viable neck — small, soft, non-critical —
so the anatomy is consistent across creatures and the migration
has somewhere to put future jewelry.

Future work (noted in ``project_more_body_parts`` backlog):

- Werewolf throat-bite mechanic: an arm → neck critical strike
  path that takes a player out in one hit. The neck becomes the
  anchor for that attack source.
- Talismans / chokers / collars once jewelry items ship. They'll
  use the ``accent`` key on this part via the
  ``EquipmentSlots.NECK`` → ``("neck", "accent")`` routing in
  ``equipment_routing``.

Design rationale
================

``health_max = "1d8"``
    Small, fragile target — closer to an arm (``2d8``) than a
    head (``3d10``) or a torso (``6d10``). A single decent
    blow should be enough to seriously injure the neck.

``is_critical = True``
    The neck holds the head atop the body — destroying it is
    structurally fatal for humanoid anatomy. Updated 2026-05-01
    after live playtest revealed humanoid-neck destruction was
    only fatal via the head-cascade path (head dangling off a
    destroyed neck → ``head.is_destroyed`` returns True via
    ancestor walk → death). Marking neck critical makes the kill
    direct rather than detoured, and gives ``divine_rescue``
    a top-level part to lift back to 1 HP rather than relying
    on its ancestor-of-critical fallback.

    Multi-neck creatures (hydra) override this to ``False`` so
    losing one neck doesn't end the fight — only the last
    remaining neck should be critical, and that's enforced via
    ``check_part_driven_death`` (todo: same shape as the
    last-head detection).

Exposure
    Slightly-shielded-head profile (MELEE 0.6, REACH 0.7,
    THROWN 0.8, RANGED 0.9). Exposure feeds both random-hit
    weighting AND per-part dodge scaling (``base / exposure``)
    — an "eye-tier" 0.1-0.3 would correctly flag the neck as
    a rare accidental target but would also amplify neck dodge
    to 3.3× base under Phase C, which reads as absurd at the
    combat surface. Neck is a realistic melee target (throat
    grabs, uppercuts, bow shots) so exposure sits one notch
    under head rather than near the eye.

Debuffs
    Empty for now. When the werewolf throat-bite / choking
    mechanics land, they'll likely add a ``Stat.DODGE`` or
    ``Stat.HEALTH_REGEN`` penalty — but the base plugin stays
    contract-minimal so overrides are clean.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.mixins import Equippable
from caldanai.lib.rpg.helpers.enums import Reach


class NeckPlugin(BodyPartPlugin, Equippable):
    """Minimal neck. Non-critical, low exposure, no debuffs yet.

    Exists primarily as a mounting point for amulet / jewelry
    equipment once ``EquipmentSlots.NECK`` routes to
    ``("neck", "accent")``. Ships with no mechanical effects so
    future overrides (werewolf throat-bite, choking, talismans)
    don't collide with an opinionated default.
    """

    # Phase D placement key: ``accent`` holds amulets, chokers,
    # collars — any neck-worn jewelry/accessory. Generic-key
    # vocabulary: the item's own name carries the flavor detail.
    PLACEMENT_KEYS = ["accent"]

    name = "neck"
    health_max = "1d8"
    is_critical = True
    bleed_rate = 0.3
    exposure = {
        Reach.MELEE:  0.6,
        Reach.REACH:  0.7,
        Reach.THROWN: 0.8,
        Reach.RANGED: 0.9,
    }
    debuffs = {}
