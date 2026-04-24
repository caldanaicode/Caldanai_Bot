"""``Skeleton`` monster plugin — a reanimated bonewalker.

Design notes
============

Thematic vulnerabilities drive the trait table:

- ``BLUDGEONING * 2.0`` — hammers and clubs shatter bones. The most
  dramatic way to deal with a skeleton.
- ``LIGHT * 2.0`` — holy damage (the game's LIGHT damage type plays
  the role of holy/radiant here). Undead should recoil from it.
- ``SLASHING * 0.5`` / ``PIERCING * 0.25`` — no flesh to cut, few
  vital organs to pierce. Arrows whistle through empty ribcages.
- ``DARK * 0.0`` — immune to dark magic; it's their element.

No eye parts: empty sockets. The HIT-modifier emergence falls back to
heads as the perception source (see ``Creature.get_hit_modifier``),
which is fine — damaging the skull still blinds it.
"""

from random import choice

from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.creatures.classifications import Undead
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)


class Skeleton(Undead, MonsterPlugin):
    # Empty sockets — skeletons have no eye parts under Phase D.
    # The head still contributes as a Sensory fallback, matching
    # pre-D behavior where ``has_eyes`` returned False.
    BODY_TREE = humanoid_tree(eyes=False)

    # Skeleton-specific narration. ``Undead`` mixin already provides
    # LIGHT and DARK entries; we override LIGHT here for a more
    # bone-themed flavor (and inherit DARK as-is). The MRO-walking
    # merge in ``Creature.get_hit_narration`` composes both layers
    # automatically — no ``{**Undead.HIT_NARRATIONS, ...}`` boilerplate
    # needed.
    HIT_NARRATIONS = {
        DamageTypes.LIGHT: "Holy radiance scorches the bone-walker's frame, leaving glowing scars.",
        DamageTypes.BLUDGEONING: "Bones crack and splinter under the blow.",
        DamageTypes.PIERCING: "The shaft whistles cleanly between brittle ribs.",
        DamageTypes.SLASHING: "The blade bites only shallowly into ancient bone.",
        DamageTypes.FIRE: "Flame chars old bone black.",
        DamageTypes.WATER: "Cold seeps through @1d's loose joints.",
    }

    def __init__(self):
        super().__init__(
            name="skeleton",
            atk="1d8",
            defense="1d4",   # brittle — not much armor between the bones
            dodge="1d10",
            health_max="3d10",
        )

        self.time_partition = TimePartitions.NOCTURNAL | TimePartitions.CREPUSCULAR
        self.image = None
        self.aggression = AggressionLevels.SURVIVE

        self.arrival = choice([
            "The dry clatter of bone on bone announces @1i, rising jerkily "
            "from the earth.",
            "@1ic shambles into view, its jaw hanging loose on a single "
            "strand of sinew.",
            "A cold wind whistles through empty ribs as @1i advances.",
        ])

        self.flavor = choice([
            "A hollow-eyed thing of bleached bone, moving in defiance of "
            "its own anatomy.",
            "Something animates @1. Whatever it is, it doesn't belong.",
            "@1dc's jaw hangs crooked, teeth chattering to a rhythm only it "
            "can hear.",
        ])

        self.escape = (
            "@1dc's reanimating force flickers; @1s crumples into a loose "
            "pile of bones and is still."
        )

        self.death = choice([
            "With a final, dry rattle, @1d collapses into a clattering heap.",
            "@1dc's skull rolls free of its neck as the rest of @1o topples.",
            "The light in @1d's sockets guts, and @1s falls apart at every "
            "joint.",
        ])

        # ``Undead`` mixin (see classifications/undead.py) provides
        # the standard undead profile via setdefault: LIGHT 2.0,
        # FIRE 1.5, DARK 0.0, WATER 0.5. We only declare the
        # skeleton-specific deltas here.
        self.traits[DamageTypes.BLUDGEONING] = 2.00   # brittle bones shatter
        self.traits[DamageTypes.SLASHING] = 0.50      # nothing to cut
        self.traits[DamageTypes.PIERCING] = 0.25      # arrows whistle through
        # Override Undead's default FIRE (1.5 → 1.25): the bones are
        # already dry but not as flammable as flesh.
        self.traits[DamageTypes.FIRE] = 1.25

        # Grave goods: a skeleton may have been something before it was
        # reanimated. Common: a weapon or a scrap.
        self.loot["rock"] = 0.4
        self.loot["stick"] = 0.3
        self.loot["shortsword"] = 0.15
        self.loot["mace"] = 0.1
        self.loot["small_gem"] = 0.05
        self.loot["bone_dust"] = 0.6  # always at least *some* dust left behind

        # Standard humanoid anatomy — no eyes (empty sockets).

        self.size = Size.MEDIUM
        self._scale_part_hp()

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            "@1dc rattles alarmingly as @2 {inv}s @1o, bone grinding on "
            "bone.".replace("{inv}", invocation),
            "@1dc's arm comes loose in @2's embrace. Awkward.",
            "@1d's jaw clacks open and shut as if trying to return the "
            "{inv}.".replace("{inv}", invocation),
        ])
