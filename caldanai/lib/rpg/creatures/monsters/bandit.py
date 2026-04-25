from random import choice, randint

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import AggressionLevels, TimePartitions, DamageTypes, Size
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.helpers.dice import Dice


class Bandit(MonsterPlugin):
    BODY_TREE = humanoid_tree()

    # Bandit instinct: ~30% of attacks go for a leg — cripple the
    # mark so they can't run off with the loot. Otherwise falls back
    # to exposure-weighted random.
    TARGET_PREFERENCES = {"leg": 0.3}

    # Per-hit narration: layered leather + stolen padding cushions
    # most blows at 0.75×; magical attacks find the gaps in the
    # patchwork at 1.5×.
    HIT_NARRATIONS = {
        DamageTypes.MAGICAL:     "Arcane force slips past @1a patchwork armor as if @1s weren't wearing any.",
        DamageTypes.BLUDGEONING: "The blow thuds against layered leather; @1s grunts but stays standing.",
        DamageTypes.SLASHING:    "The blade scores @1d through cobbled-together straps and stolen padding.",
        DamageTypes.PIERCING:    "The point catches on a buckle, then slides past into the gap behind it.",
    }

    # Salvage drops — destroying a bandit's body part yields scrap-
    # tier armor harvested from the corpse. Quality range biases
    # toward the JUNK/ORDINARY end of the curve via the inverted
    # ``Qualities.from_scale`` mapping (higher randint -> lower
    # quality). Bandit armor IS scrap; the occasional FINE roll is
    # the lucky-break exception.
    SALVAGE_DROPS = {
        "arm":   [("patchwork_bracer", 0.6, (50, 95))],
        "foot":  [("worn_boot",        0.5, (50, 95))],
        "hand":  [("ratty_glove",      0.4, (50, 95))],
        "torso": [("bandits_sash",     0.3, (50, 95))],
    }

    def __init__(self):
        super().__init__(
            name="bandit",
            atk="1d8",
            defense="1d12",
            dodge="1d12",
            health_max="4d12"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = "bandit128.png"
        self.aggression = AggressionLevels.VENGEFUL
        self.arrival = (
            f"A masked @1 {choice('stealthily|clumsily|quickly|slowly'.split('|'))} "
            f"{choice('walks|saunters|sashays|sneaks'.split('|'))} out of the "
            f"{choice('bushes|rocks|distance|shadows'.split('|'))}."
        )

        self.flavor = choice(["Your money or your life.", "This is a stick up.", "You'll never take me alive."])

        self.escape = choice([
            "@1dc spits a curse and bolts for the treeline.",
            "Other horizons call @1d away.",
        ])

        self.death = choice(
            [
                "@1dc dies, and shall no longer steal from the rich and give to the poor.",
                "@1dc coughs blood before collapsing to the ground.",
                '"In another life, you could have been me," @1d gasps with @1a dying breath.',
            ]
        )

        self.traits[DamageTypes.RANGED] = 1.00
        self.traits[DamageTypes.MAGICAL] = 1.50
        self.traits[DamageTypes.ANY - (DamageTypes.RANGED | DamageTypes.MAGICAL)] = 0.75

        self.loot["shortsword"] = 0.2
        self.loot["bandanna"] = 0.2
        self.loot["bow"] = 0.15
        self.loot["cheese_sandwich"] = 0.2
        self.loot["wallet"] = 0.25

        self.size = Size.MEDIUM
        self._scale_part_hp()

    def steal(self, target: Creature) -> str:
        """
        Attempts to steal a creature's wealth.

        Requires at least one working arm (to reach into the target's
        pockets) and at least one working leg (to close the distance).

        :param target: The creature being targeted.
        :return: A string indicating the results of the theft.
        """
        from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
        from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin

        working_arms = [p for p in self.body_parts if isinstance(p, ArmPlugin) and not p.is_destroyed()]
        if not working_arms:
            return "\n@1dc reaches for @2's coin purse, but @1a mangled arms fail to grasp anything."

        working_legs = [p for p in self.body_parts if isinstance(p, LegPlugin) and not p.is_destroyed()]
        if not working_legs:
            return "\n@1dc tries to approach @2's wallet, but can't close the distance on @1a ruined legs."

        if target.clarks > 0:
            amount = randint(1, max(1, int(target.clarks / 10)))
            attempt = Dice.quick_roll("1d20")
            if attempt >= target.get_dodge():
                target.give_clarks(-amount)
                return f"\n@2's wallet suddenly feels lighter... {amount} clarks were lost!"
            return "\n@2 easily avoids @1np groping fingers."
        else:
            return "\n@1dc sneers in disgust, realizing that @2 has no clarks to steal."

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        responses = [
            f"*@2 pulls @1d into a {invocation}. @1sc breaks down crying at the first affection @1s has ever known, clinging on like a lost child.*",
            f"*@2 wraps @1d in a {invocation}. @1sc accepts graciously — while @1a free hand drifts toward @2np wallet...*",
            f"*@2 leans in for a {invocation}. @1dc twists aside with a sneer and will not be touched.*",
        ]

        response = choice(responses)
        if response == responses[1]:
            response += f"\n{self.steal(actor)}"

        return response

    def on_social(self, cmd: str, actor: Creature, invocation: str) -> str:
        """Bandit-specific reactions for non-hug social commands.
        Hug still flows through :meth:`on_hugged` via the default
        ``Creature.on_social`` delegation."""
        from caldanai.lib.rpg.helpers.parser import parse

        if cmd == "high_five":
            # Serena's idea (community ideas channel, 2026-04-19):
            # bandit should have a thematic response to ``$high_five``.
            # Same 1-in-3 steal chance as the hug path, re-flavored
            # around the raised-palm gesture — slapping the palm with
            # one hand while the other dips toward the pocket.
            responses = [
                "*@2 throws up a palm for a high five. @1dc eyes it suspiciously and keeps @1a distance.*",
                "*@2 throws up a palm for a high five. @1dc slaps it enthusiastically — and dips into @2np pocket with the other hand...*",
                "*@2 throws up a palm for a high five. @1dc raises @1a own to meet it, then pulls away at the last instant with a smirk.*",
            ]
            response = choice(responses)
            if response == responses[1]:
                response += f"\n{self.steal(actor)}"
            return parse(response, self, actor)
        return super().on_social(cmd, actor, invocation)
