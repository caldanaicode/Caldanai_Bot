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
  use the ``amulet`` key on this part via the
  ``EquipmentSlots.NECK`` → ``("neck", "amulet")`` routing in
  ``equipment_routing``.

Design rationale
================

``health_max = "1d8"``
    Small, fragile target — closer to an arm (``2d8``) than a
    head (``3d10``) or a torso (``6d10``). A single decent
    blow should be enough to seriously injure the neck.

``is_critical = False``
    A damaged neck should hurt — eventually reaching that
    throat-bite kill path — but the base plugin doesn't fire
    a critical-part death short-circuit on its own. Creatures
    like werewolf can override to inflict neck-specific finish
    moves without the base plugin presuming them.

Exposure
    Uniformly low (0.2 across every reach). The neck sits
    between head and torso and is shielded by both; attacks
    landing on it are rarer than on the head or arms. Roughly
    the eye-tier exposure (0.1–0.3) is the right neighborhood.

Debuffs
    Empty for now. When the werewolf throat-bite / choking
    mechanics land, they'll likely add a ``Stat.DODGE`` or
    ``Stat.HEALTH_REGEN`` penalty — but the base plugin stays
    contract-minimal so overrides are clean.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.helpers.enums import Reach


class NeckPlugin(BodyPartPlugin):
    """Minimal neck. Non-critical, low exposure, no debuffs yet.

    Exists primarily as a mounting point for amulet / jewelry
    equipment once ``EquipmentSlots.NECK`` routes to
    ``("neck", "amulet")``. Ships with no mechanical effects so
    future overrides (werewolf throat-bite, choking, talismans)
    don't collide with an opinionated default.
    """

    name = "neck"
    health_max = "1d8"
    is_critical = False
    bleed_rate = 0.3
    exposure = {
        Reach.MELEE:  0.2,
        Reach.REACH:  0.2,
        Reach.THROWN: 0.2,
        Reach.RANGED: 0.2,
    }
    debuffs = {}
