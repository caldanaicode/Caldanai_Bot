"""``Werewolf`` monster plugin — LARGE cursed predator.

Design notes
============

The werewolf encountered is already in its lupine form — the curse
binds transformation to moonlight. This is modeled structurally
rather than with a status-effect transform:

- ``time_partition = NOCTURNAL`` — werewolves only spawn at night.
- ``flees_from_time = True`` + ``time_flee`` message — dawn forces
  the creature to retreat, presumably to resume human form
  somewhere out of sight.

Target preference: ~30% throat (`head`). Predatory but less
obsessive than the bearowl's 40% — werewolves are cursed humans,
not pure apex predators, so they're slightly less disciplined.

Trait profile: the traditional werewolf weakness is silver, but the
game doesn't model silver as a damage type. ``LIGHT * 2.0`` stands
in for holy/blessed vulnerability; otherwise standard physical.
"""

from random import choice, random
from typing import Optional

from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions,
)


class Werewolf(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="werewolf",
            atk="2d8",       # bite + claw
            defense="1d6",
            dodge="2d8",
            health_max="8d10",
        )

        self.time_partition = TimePartitions.NOCTURNAL
        self.flees_from_time = True
        self.time_flee = (
            "@1dc throws back @1a head and howls as the first grey light of "
            "dawn creeps across the sky. Before the second breath, @1s has "
            "bounded into the treeline and is gone."
        )
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE

        self.arrival = choice([
            "A low, unhurried growl drifts from the shadows; @1i pads into "
            "view, eyes reflecting moonlight like two pale coins.",
            "Claws click against stone as @1i rounds the corner, hackles "
            "raised and lips already peeled back from yellowed teeth.",
            "@1ic bursts from the underbrush in a coiled rush, too large "
            "for a wolf and too canny for an animal.",
        ])

        self.flavor = choice([
            "Too big. Too deliberate. This is no ordinary wolf — "
            "something human stares out from behind those eyes.",
            "@1dc moves with a terrible patience, the way something "
            "hungry does when it is not yet desperate.",
            "The pelt is matted in patches, as if @1s was caught "
            "between shapes once and the seams never quite took.",
        ])

        self.escape = (
            "@1dc circles once, gauging the odds, then melts back into "
            "the forest with a final snarl."
        )

        self.death = choice([
            "@1dc collapses with a rattling whine; as the last breath "
            "leaves @1o, the body seems almost to flicker, then is still.",
            "@1dc sags onto @1a side, fur going slack. @1a dying gaze "
            "looks oddly human in the moonlight.",
        ])

        # Weakness to holy (silver-stand-in via LIGHT).
        self.traits[DamageTypes.LIGHT] = 2.00
        self.traits[DamageTypes.FIRE] = 1.50
        self.traits[DamageTypes.BLUDGEONING] = 0.75  # muscle under pelt
        self.traits[DamageTypes.PIERCING] = 1.25

        self.loot["leather"] = 0.6
        self.loot["shortsword"] = 0.1  # presumably human's gear
        self.loot["wallet"] = 0.2

        # Quadruped shape for the wolf form (head, torso, 4 legs, tail).
        self.body_parts = BodyPart.quadruped()

        self.size = Size.LARGE
        self._scale_part_hp()

    def get_target_part_preference(
        self, target: Creature, source: AttackSource,
    ) -> Optional[str]:
        """Throat-bite bias: ~30% of attacks target the head. Less
        obsessive than the bearowl (40%) because the werewolf is a
        cursed human, not a pure predator — still instinctual but a
        little more scattered."""
        if random() < 0.3:
            return "head"
        return None

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@1dc tolerates the {invocation} for precisely one second, "
            "then @1a lips peel back in a warning snarl.",
            f"@1dc leans into the {invocation} for a bewildered moment "
            "before remembering what @1s is.",
            f"A deep growl rolls up through @1a chest as @2 attempts a "
            f"{invocation}. @2 decides perhaps later is better.",
        ])
