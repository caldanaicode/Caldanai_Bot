from random import choice

from caldanai.lib.rpg import get_random_direction
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Size)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import quadruped_winged_tree


class Bearowl(MonsterPlugin):
    BODY_TREE = quadruped_winged_tree()

    # Apex-predator bias: ~40% of attacks go for the head (killing
    # bite). Otherwise falls back to exposure-weighted random — even
    # a predator misreads prey sometimes.
    TARGET_PREFERENCES = {"head": 0.4}

    # Per-hit narration: thick fur and feather padding cushions
    # blunt blows; sharp edges and pierce-points slip through to
    # the muscle and bone beneath. Ranged shots have the angle to
    # find the gaps that melee can't reach.
    HIT_NARRATIONS = {
        DamageTypes.MAGICAL:     "Arcane force finds purchase in @1a strange hide; bear and owl both feel it, neither quite sure where the touch lands.",
        DamageTypes.SLASHING:    "The blade opens @1a hide cleanly; clumps of fur and down drift loose.",
        DamageTypes.PIERCING:    "The point parts feather and pelt and finds the muscle beneath without resistance.",
        DamageTypes.BLUDGEONING: "The blow sinks into thick fur and dense down; @1s barely feels it.",
    }
    # Bow finds the gap between the airborne layers — wand attacks
    # carry MAGICAL not PIERCING, so they fall through to base
    # HIT_NARRATIONS[MAGICAL] above (the bear-and-owl-both-feel-it
    # arcane line).
    RANGED_NARRATIONS = {
        DamageTypes.PIERCING:    "The shot threads between @1a feathers and lodges deep — distance was the friend @1s lacked.",
    }

    # Crafting materials. Bearowl is the first source-creature for
    # the leather chain (per the source-creature-shape split locked
    # 2026-04-26: quadrupeds drop materials, humanoids drop finished
    # armor). Each entry is one ``leather`` stackable; multiple
    # entries roll independently so a torso can yield 0-3 leathers,
    # a leg 0-2. Quality range ``(45, 60)`` skews ORDINARY-mode
    # (~62%) with a FINE upper tail (~31%) and a thin JUNK tail
    # (~6%) — well above the scrap-tier (50, 95) band.
    #
    # Keys must match ``_part_base_name(part)`` which returns the
    # plugin's class-level ``name`` attribute. ``LegPlugin.name``
    # is ``"leg"`` regardless of whether the instance is a foreleg
    # or hindleg, so a single ``"leg"`` entry covers all four leg
    # parts on a quadruped. (Initial v1 used ``"foreleg"`` /
    # ``"hindleg"`` keys — never matched, surfaced 2026-04-26 in
    # playtest after two destroyed legs in a row dropped nothing.)
    SALVAGE_DROPS = {
        "torso": [
            ("leather", 0.7, (45, 60)),
            ("leather", 0.5, (45, 60)),
            ("leather", 0.3, (45, 60)),
        ],
        "leg": [
            ("leather", 0.5, (45, 60)),
            ("leather", 0.3, (45, 60)),
        ],
    }

    def __init__(self):
        super().__init__(
            name="bearowl",
            atk="2d7",
            defense="3d8",
            dodge="1d10",
            health_max="22d10"
        )

        self.time_partition = TimePartitions.NOCTURNAL | TimePartitions.CREPUSCULAR
        self.image = "owl128.png"
        # SURVIVE (was VENGEFUL): VENGEFUL fled after one hit, which
        # made the bearowl unviable as the leather-source — players
        # couldn't drive parts to USELESS before it bolted. SURVIVE
        # sticks until ~10% HP, mirroring the same fix applied to
        # bandits when scrap salvage shipped.
        self.aggression = AggressionLevels.SURVIVE
        self.arrival = (
            "A genetically improbable creature "
            f"{choice('lurches|trudges|charges|walks|wanders'.split('|'))} "
            f"in from the {get_random_direction()}."
        )

        self.flavor = choice(
            [
                "Legally distinct from any similarly-named creatures.",
                "Hoo. Hoo. A frickin' @1, that's who.",
                "Trust me, you don't want to know.",
            ]
        )

        self.escape = "@1dc, silent as a jackhammer, slips away."
        self.death = choice(
            [
                "@1dc gives a final howl of pain and terror before crumpling to the ground.",
                "After a last-ditch effort to escape your fury, @1d collapses into lifelessness.",
                "The abomination of nature will no more threaten your sense of reason.",
            ]
        )

        # Ranged-vulnerable across the board: airborne attack pattern
        # exposes the soft parts, regardless of whether the projectile
        # is an arrow shaft or an arcane bolt. Vael observed *1.5 on
        # wand attacks 2026-05-12 confirming the shape.
        self.ranged_traits[DamageTypes.ANY] = 1.50
        self.traits[DamageTypes.PIERCING | DamageTypes.SLASHING] = 1.25
        self.traits[DamageTypes.BLUDGEONING] = 0.5

        # Bearowls fly (owl half). The ``WingPlugin.on_injury_change``
        # hook from item 2.5 discards this flag when a wing is driven
        # to ``InjuryLevels.USELESS``, grounding the creature. This
        # pins the full wing -> grounded interaction on a real
        # creature, not just the hydra test fixture.
        self.flags = {"flying"}

        self.size = Size.LARGE
        self._scale_part_hp()
        # Thick pelt + layered muscle — torso-targeting absorbs a
        # flat +3 on top of base defense.
        for part in self.body_parts:
            if part.name == "torso":
                part.defense_bonus = 3

    # Reacts to hugs.
    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                "Are you really sure you want to do that, @2?",
                f"@1dc looks at @2 suspiciously before accepting the {invocation}.",
                f"{invocation.capitalize()}s do not work on @1, @2.",
            ]
        )
