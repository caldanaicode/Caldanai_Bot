"""``Minotaur`` monster plugin — LARGE bull-headed bruiser.

Design notes
============

The signature feature is the **horn-gore** preference: the minotaur
aims for the head about 50% of the time, attempting to run people
through with its horns. This uses the ``get_target_part_preference``
hook shipped with the per-part dodge system — when the preference is
honored, the attack pays the dodge exposure tax on heads (0.7 MELEE
exposure → effective dodge ~1.43×), so the gore is scarier *and* more
avoidable than a random swing.

Standard humanoid anatomy (the bull head is still a "head" part —
the body-part system doesn't model horns separately). Trait profile
leans into "muscle and momentum": bludgeoning weapons don't do great
against a half-ton of meat, piercing weapons find the soft spots
between slabs of muscle.
"""

from random import choice

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)


class Minotaur(MonsterPlugin):
    BODY_TREE = humanoid_tree()

    # Gore bias: ~50% of attacks aim for the head. The preference pays
    # the dodge exposure tax (heads are ~0.7 MELEE exposure → effective
    # dodge ~1.43×), so horn strikes are distinctive but not free
    # accuracy.
    TARGET_PREFERENCES = {"head": 0.5}

    # Per-hit narration: dense slabs of muscle absorb blunt blows;
    # piercing finds the seams between corded muscle. Coarse coat
    # catches fire surprisingly well.
    HIT_NARRATIONS = {
        DamageTypes.FIRE:        "Flame catches in @1a coarse coat and spreads with the smell of burning hair.",
        DamageTypes.MAGICAL:     "Arcane force ripples through @1a heavy frame; @1s rolls a horn against the touch and does not slow.",
        DamageTypes.PIERCING:    "The point parts @1a hide and slips between thick cords of muscle.",
        DamageTypes.BLUDGEONING: "The blow sinks into dense muscle; @1s rocks back but holds the line.",
        DamageTypes.SLASHING:    "The blade scores @1a hide; sweat-darkened fur splits and reveals raw skin beneath.",
    }

    def __init__(self):
        super().__init__(
            name="minotaur",
            atk="2d8",
            defense="5d3",
            dodge="5d3",
            health_max="14d12",
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE

        self.arrival = choice([
            "The earth thunders under cloven hooves as @1i charges into "
            "view, head lowered and horns gleaming.",
            "A bellowing roar echoes through the area; @1i emerges from "
            "a swirl of kicked-up dust, nostrils flaring.",
            "@1ic paws at the ground, a line of breath steaming from its "
            "bull-like nose. It has decided @2 look like a problem.",
        ])

        self.flavor = choice([
            "A massive humanoid from the shoulders down, and unmistakably "
            "bull from the shoulders up. @1A horns look very, very sharp.",
            "Corded muscle and a head full of hostile intent. "
            "@1S appears to take personal offense at being looked at.",
            "This @1 smells of hot sweat and hay, but nothing about @1o "
            "suggests domestication.",
        ])

        self.escape = (
            "@1dc snorts one last time, shakes @1a great horned head, and "
            "trots off with the deliberate calm of something that will be back."
        )

        self.death = choice([
            "@1dc collapses onto @1a side with a final, thunderous snort.",
            "The light leaves @1d's dark eyes; @1s sags to @1a knees, then "
            "topples like a fallen pillar.",
        ])

        # Trait profile: muscle mass laughs at bludgeoning, soft spots
        # give way to piercing.
        self.traits[DamageTypes.BLUDGEONING] = 0.75
        self.traits[DamageTypes.PIERCING] = 1.25
        self.traits[DamageTypes.FIRE] = 1.25   # flammable coat

        # Loot: weapons and maybe a hunk of what-was-it.
        self.loot["warhammer"] = 0.3
        self.loot["sledgehammer"] = 0.2
        self.loot["spear"] = 0.3
        self.loot["leather"] = 0.5
        self.loot["cheese_sandwich"] = 0.1  # took it from someone else

        # Standard humanoid shape; the bull head is still just a "head"
        # part from the body-parts system's perspective.

        self.size = Size.LARGE
        self._scale_part_hp()

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@1dc pauses mid-{invocation}, confused by the sudden "
            "absence of stabbing. @1S snorts hot breath down @2's neck.",
            "@1dc's tail lashes once, then twice, then @1s shoves @2 "
            "away with the flat of a calloused palm.",
            "A low, threatening rumble vibrates through @1a chest as @2 "
            f"{invocation}s @1o. The {invocation} does not continue long.",
        ])
