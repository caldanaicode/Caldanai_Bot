"""``Golem`` monster plugin — LARGE stone construct.

Design notes
============

Golems are the embodiment of "high defense, low dodge": a walking
wall that players hit almost every time, but their weapons bounce
off. Per-part injury progression eventually cracks it apart, but
only after sustained punishment.

Trait profile drives most of the flavor:

- ``PIERCING * 0.25`` — arrows chip off without penetrating.
- ``SLASHING * 0.5`` — blades bite shallowly.
- ``BLUDGEONING * 1.00`` — hammers actually work on stone.
- ``FIRE * 0.5`` — stone laughs at heat.
- ``WATER * 1.25`` — slow erosion, effective at scale.
- ``MAGICAL * 1.5`` — the binding enchantment is its vulnerability.
- ``EARTH * 0.25`` — mostly what it's made of.

No eye parts — a golem's face is graven stone, no organic sense
organs. HIT emergence falls back to heads, which is fine (damaging
the carved head still degrades its accuracy).

No preference override — golems don't aim, they swing. Exposure-
weighted random targeting makes the most sense for a brute of
mindless mass.

Unlike most creatures, golems do NOT flee or die from time — they
are animated stone, they don't care about day/night cycles.

Aggression: ``RAMPAGE`` — the golem swings until it's shattered.
The ``self.escape`` string ("glyphs dim, subsides into standing
stone") is retained for a future dungeon use-case: persistent
deactivated golems that can re-activate when players pass through
the room again. In the current single-monster-per-channel world,
a RAMPAGE golem doesn't hit the escape path under normal combat
flow, so the flavor text is effectively reserved.
"""

from random import choice

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)


class Golem(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="golem",
            atk="2d6",        # heavy slam, nothing fancy
            defense="3d6",    # heavy stone armor; Q.6.3 tank +4 on torso/head does the rest
            dodge="1d4",      # almost never dodges anything
            health_max="25d12",
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE  # keeps swinging until destroyed

        self.arrival = choice([
            "Grinding stone on stone, @1i lurches into the clearing; dust "
            "sheds from its seams with every step.",
            "The earth shudders as @1i takes a step, then another. @1ac "
            "pace is implacable.",
            "A rough-hewn figure carved from living rock advances with "
            "terrible patience; faint runes glow between the cracks.",
        ])

        self.flavor = choice([
            "A rough humanoid shape, chiseled from a single slab. Faint "
            "glyphs pulse along @1a joints whenever @1s moves.",
            "Time weathers stone. Whoever bound this @1 did not bind it "
            "quickly — @1s looks old in the way mountains are old.",
            "No face to speak of — just a carved brow and a slash for a "
            "mouth. @1sc appears to navigate the world anyway.",
        ])

        self.escape = (
            "The glyphs along @1d's seams dim, and @1s subsides into a "
            "rough standing stone, waiting for someone to wake @1o again."
        )

        self.death = choice([
            "The binding glyphs flare white and then shatter; @1d "
            "collapses into an avalanche of stone fragments.",
            "@1dc's stone body cracks from core outward with a sound like "
            "the world grinding its teeth, then sloughs into rubble.",
        ])

        # Elemental-physical trait profile — the core of the golem's
        # identity lives in this table.
        self.traits[DamageTypes.PIERCING] = 0.25
        self.traits[DamageTypes.SLASHING] = 0.50
        self.traits[DamageTypes.BLUDGEONING] = 1.00
        self.traits[DamageTypes.FIRE] = 0.50
        self.traits[DamageTypes.WATER] = 1.25
        self.traits[DamageTypes.EARTH] = 0.25
        self.traits[DamageTypes.AIR] = 0.75
        self.traits[DamageTypes.MAGICAL] = 1.50  # binding unravels
        self.traits[DamageTypes.LIGHT] = 1.00
        self.traits[DamageTypes.DARK] = 1.00

        # Loot — the valuable bits are in the stone itself.
        self.loot["rock"] = 1.0
        self.loot["small_gem"] = 0.4
        self.loot["sledgehammer"] = 0.1   # weapon of its creator, maybe

        # No eyes — carved stone face, but still a "head" for HIT
        # emergence purposes (per ``Creature.get_hit_modifier``).
        self.body_parts = BodyPart.humanoid()

        self.size = Size.LARGE
        self._scale_part_hp()
        # Stone construct — torso and head are solid rock, not just
        # armored flesh. Add a flat +4 defense_bonus on top of the
        # already-high base defense so critical-destroy takes real
        # effort.
        for part in self.body_parts:
            if part.name in ("torso", "head"):
                part.defense_bonus = 4

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@1dc registers the {invocation} approximately the way a "
            "standing stone registers a hand placed upon it.",
            "@1dc's stone arms do not return the embrace. They do, however, "
            "continue swinging.",
            f"Trying to {invocation} @1d is like {invocation}ging a kiln. "
            "@2 notes this for future reference.",
        ])
