from random import choice

from caldanai.lib.rpg import get_random_direction
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.foot import FootPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Size)


class Toad(MonsterPlugin):
    # Tailless quadruped — Phase D segmented limbs ending in
    # forepaws / hindpaws. Toads have vestigial tails at best;
    # declaring a quadruped-minus-tail anatomy here keeps the
    # per-part HP pool honest (no phantom tail to scale).
    BODY_TREE = node(TorsoPlugin, name="torso", children=[
        node(NeckPlugin, name="neck", children=[
            node(HeadPlugin, name="head", children=[
                *paired(EyePlugin, "eye"),
            ]),
        ]),
        *paired(
            LegPlugin, "foreleg",
            children_builder=lambda side: [
                node(FootPlugin, name=f"forepaw.{side}"),
            ],
        ),
        *paired(
            LegPlugin, "hindleg",
            children_builder=lambda side: [
                node(FootPlugin, name=f"hindpaw.{side}"),
            ],
        ),
    ])

    # Per-hit narration: damp slick hide shrugs off blunt blows and
    # diffuses arcane force; pointed shafts find the soft body
    # cleanly. Fire is devastating against amphibian flesh.
    HIT_NARRATIONS = {
        DamageTypes.FIRE:        "Flame meets damp hide; @1d's flesh blisters audibly, hissing as it cooks.",
        DamageTypes.MAGICAL:     "Arcane force sluices over @1a damp hide and runs off the way water does; the magic finds less purchase here than it expects.",
        DamageTypes.PIERCING:    "The point slides through @1a slick hide cleanly.",
        DamageTypes.BLUDGEONING: "The blow lands flat against rubbery hide; @1s gives a wet, dismissive croak.",
    }
    # Bow-specific overlay (Reach.RANGED + PIERCING). Wand attacks
    # carry MAGICAL not PIERCING, so they fall through to base
    # HIT_NARRATIONS[MAGICAL]; only bow shafts trigger this line.
    RANGED_NARRATIONS = {
        DamageTypes.PIERCING:    "The shaft punches clean through @1a slick hide and finds the soft body beneath.",
    }

    def __init__(self):
        super().__init__(
            name="toad",
            atk="1d8",
            defense="1d4",
            dodge="2d8",
            health_max="4d8"
        )

        if choice([1, 2]) == 2:
            self.size = Size.SMALL
            self.arrival = "An odd humanoid mushroom waddles into the area muttering something about castles and princesses."
            self.flavor = "It remains unclear whether this _toadstool_ is just a remnant of a bad trip."
            self.escape = "The funny little toadstool zips around in a rapid circle before jumping down a large green pipe -- wait, where did that come from?"
            self.death = "The mushroom waves @1a arms frantically, shrieking in terror. Then, @1s suddenly stops and falls backwards, rocking slightly before going still."
        else:
            self.size = Size.MEDIUM
            size = self.size.name.lower()
            self.arrival = (
                f"A {size} @1 {choice('hops|leaps|bounds'.split('|'))} in from the {get_random_direction()}, "
                f"with a hungry gaze."
            )
            self.flavor = "This @1 is abnormally large, its diet primarily consisting of cute, small animals."
            self.escape = "@1dc barks out a loud croaking noise before leaping off into the distance."
            self.death = "@1dc struggles to leap away, but the effort is futile, as @1s collapses onto @1a belly."

        self.time_partition = TimePartitions.CREPUSCULAR | TimePartitions.NOCTURNAL
        self.image = None
        self.aggression = AggressionLevels.VENGEFUL

        # Bow finds the soft body beneath the slick hide cleanly —
        # piercing-from-distance gets the bonus, melee piercing
        # (spear) just gets baseline below.
        self.ranged_traits[DamageTypes.PIERCING] = 1.50
        self.traits[DamageTypes.FIRE] = 2.00
        self.traits[DamageTypes.BLUDGEONING] = 0.75
        self.traits[DamageTypes.PIERCING] = 1.00
        self.traits[
            DamageTypes.ANY - (DamageTypes.PIERCING | DamageTypes.FIRE | DamageTypes.BLUDGEONING)
        ] = 0.5

        self.loot["toad_slime"] = 0.9
        self.loot["mushroom_hat"] = 0.3

        self._scale_part_hp()
