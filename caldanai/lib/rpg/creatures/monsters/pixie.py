"""``Pixie`` monster plugin — TINY winged fae prankster.

Design notes
============

The pixie leans hard into the ``Size.TINY`` column: ``hp_scale=0.25``
and ``dodge_mod=1.5`` mean it's very hard to pin down but folds the
moment you connect. Wings add a mobility source parallel to legs
(with the ``"flying"`` flag; see ``Creature.get_dodge``) so destroying
a wing has the same cascading effect it does on dragons and bearowls
— ground the pixie and its dodge collapses.

Target preference: ``eye`` (~30%). Mischievous pokes. The exposure
tax on eyes is severe (0.1 MELEE → effective dodge ×10), so in
practice most pixie swings whiff the eye attempt entirely and the
bias is more flavor than pressure — unless the pixie gets a nat 20.

Trait profile: weak to FIRE (butterfly-wings) and LIGHT (fae can't
abide true daylight), resistant to MAGICAL (they *are* magic).

No new item plugin dependencies — loot is small_gem (pixie trinkets)
and candy (sweets they've pilfered).
"""

from random import choice

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.foot import FootPlugin
from caldanai.lib.rpg.creatures.body_parts.hand import HandPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, DamageTypes, Size, TimePartitions, WeatherPatterns,
)


class Pixie(MonsterPlugin):
    # Phase D segmented humanoid + wings. Still no eye parts —
    # pixie perception is fae-sensing, HIT emergence uses the
    # head as a Sensory fallback. The ``"flying"`` flag (set in
    # __init__) makes dodge emerge from wings while airborne.
    BODY_TREE = node(TorsoPlugin, name="torso", children=[
        node(NeckPlugin, name="neck", children=[
            node(HeadPlugin, name="head"),  # no eyes
        ]),
        *paired(
            ArmPlugin, "arm",
            children_builder=lambda side: [
                node(HandPlugin, name=f"hand.{side}"),
            ],
        ),
        *paired(
            LegPlugin, "leg",
            children_builder=lambda side: [
                node(FootPlugin, name=f"foot.{side}"),
            ],
        ),
        *paired(WingPlugin, "wing"),
    ])

    # Mischief bias: ~30% chance to poke at an eye. Under the linear
    # exposure-tax dodge formula (EXPOSURE_TAX_COEF=1.0, TINY-vs-
    # MEDIUM size ratio 0.5), the pixie's effective eye-shot dodge
    # against a MEDIUM player is ``base × 0.5 × 1.9 ≈ base × 0.95``
    # — roughly base dodge. She actually *lands* most eye-pokes; the
    # joke is the underwhelming 1d4 damage that follows. Sting, not
    # slay.
    TARGET_PREFERENCES = {"eye": 0.3}

    # Per-hit narration: pixies ARE magic, so arcane force barely
    # touches them. Bludgeoning struggles to land cleanly on a
    # tiny darting target. Piercing is unforgiving when it lands.
    # Fire and Light burn fae fiercely (folklore reaches across
    # the table on this one).
    HIT_NARRATIONS = {
        DamageTypes.FIRE:        "Iron-cold @1d shrieks; flame is anathema to fae and @1a wings curl in distress.",
        DamageTypes.LIGHT:       "Pure radiance strikes @1d harder than mortal light has any right to.",
        DamageTypes.MAGICAL:     "Arcane force passes around @1d like wind around a leaf; @1s laughs.",
        DamageTypes.BLUDGEONING: "The blow lands awkwardly — @1s's smaller than the swing, and most of it goes wide.",
        DamageTypes.PIERCING:    "The point finds @1d square; for something so small, @1s feels every bit of it.",
    }

    def __init__(self):
        super().__init__(
            name="pixie",
            atk="1d4",           # tiny sting / dart / thrown pebble
            defense="1d2",
            dodge="3d8",         # very agile before size_mod (which buffs it)
            health_max="2d4",    # glass cannon
        )

        self.time_partition = (
            TimePartitions.CREPUSCULAR | TimePartitions.NOCTURNAL
        )
        # Pixies are stained-glass-wing creatures — they stay
        # hidden in rough weather. Clear / cloudy / foggy conditions
        # are fair game; rain and strong wind keep them tucked away.
        self.weather_partition = (
            WeatherPatterns.CLEAR
            | WeatherPatterns.CLOUDY
            | WeatherPatterns.FOG
        )
        self.image = None
        self.aggression = AggressionLevels.SURVIVE

        self.arrival = choice([
            "A shimmer of impossible colors resolves into @1i, hovering "
            "mid-air with a smirk that ought to worry someone.",
            "A faint tinkling like a tiny bell announces @1i. "
            "@1ic is already rifling through @2's pocket by the time "
            "you notice.",
            "@1ic flits into view on wings of stained glass, giggling at "
            "a joke no one else was told.",
        ])

        self.flavor = choice([
            "No taller than a hand, no heavier than a thought, and "
            "twice as irritating as a swarm of gnats.",
            "This @1 glitters when @1s moves. The glitter appears to "
            "follow @1o indefinitely. That will be hard to wash out.",
            "@1dc's smile has entirely too many teeth for something so "
            "small.",
        ])

        self.escape = (
            "@1dc yawns theatrically, blows a kiss at @2 that smells "
            "faintly of petrichor, and winks out of existence."
        )

        self.death = choice([
            "@1dc's wings catch one last gust and crumple; @1a tiny body "
            "drifts down like a pressed flower.",
            "With a sound like a wineglass breaking in another room, "
            "@1d is gone — leaving only a drift of shimmer behind.",
        ])

        # Fae vulnerabilities. Flammable, hates true light, laughs at
        # most magic (they are magic).
        self.traits[DamageTypes.FIRE] = 2.00
        self.traits[DamageTypes.LIGHT] = 2.00
        self.traits[DamageTypes.MAGICAL] = 0.25
        # Blunt weapons have a hard time finding anything to hit;
        # anything sharp that does land tends to be conclusive.
        self.traits[DamageTypes.BLUDGEONING] = 0.50
        self.traits[DamageTypes.PIERCING] = 1.50

        self.loot["small_gem"] = 0.6
        self.loot["candy"] = 0.4
        self.loot["wallet"] = 0.2  # almost certainly someone else's

        # Anatomy declared at class level via ``BODY_TREE``; the
        # ``"flying"`` flag makes dodge emerge from wings while
        # airborne (mirrors dragon / bearowl).
        self.flags.add("flying")

        self.size = Size.TINY
        self._scale_part_hp()

    def get_attack_sources(self):
        """Tiny sting carrying ``DamageTypes.MAGICAL`` — pixie touch
        is faerie magic, not physical. Lets her bypass armor that
        only guards against mundane weapons, and interacts cleanly
        with the trait system on monsters that have magical
        resistances or weaknesses."""
        return [
            NaturalAttackSource(
                atk=self.attack,
                dmg_type=DamageTypes.MAGICAL,
                label=self.name.title(),
                skill="natural",
            ),
        ]

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice([
            f"@1dc dodges @2's {invocation} at the last second and "
            "leaves a raspberry hanging in the air where @1s was.",
            f"@1dc accepts the {invocation}, then bites @2's earlobe "
            "and vanishes into a puff of glitter.",
            f"@1dc pretends to be moved by the {invocation}, then "
            "picks @2's pocket on the way out.",
        ])
