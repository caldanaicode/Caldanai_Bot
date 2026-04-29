from random import choice, random
from typing import Optional

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.foot import FootPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Reach, Size)
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, CombinedRoll, DamageRoll
from caldanai.lib.rpg.creatures import Creature, _roll_absorption


class Dragon(MonsterPlugin):
    """Huge winged quadruped with breath attacks and a 62-toe variant.

    **Body part design note:** the toed variant reads the ``"flying"``
    flag managed by :class:`WingPlugin` to decide whether its 62 toes
    contribute their DODGE penalty. While the dragon is flying the
    toes are out of reach and contribute nothing; grounding it (most
    often via destroying a wing, since ``WingPlugin.on_injury_change``
    discards ``"flying"`` on the transition into USELESS) cascades
    into the full -62 DODGE penalty in :meth:`get_dodge`. The head
    exposure table is also overridden at construction time to a
    narrow low-melee, high-ranged profile — a dragon's head is far
    above the melee fray but a prime target for archers.
    """

    # Winged quadruped anatomy with a narrow-exposure head profile:
    # a dragon's head rides far above the melee fray, so MELEE/REACH
    # exposure collapses to almost nothing while RANGED stays at 1.0
    # (archers have a clear shot). Torso's ``is_critical=True``
    # inherits from ``TorsoPlugin`` — no override needed.
    #
    # Phase D anatomy: head-with-eyes behind a neck; segmented
    # legs end in paws. Narrow head exposure still lives on the
    # head node via the ``exposure`` kwarg passed through.
    BODY_TREE = node(TorsoPlugin, name="torso", children=[
        node(NeckPlugin, name="neck", children=[
            node(HeadPlugin, name="head", exposure={
                Reach.MELEE: 0.05,
                Reach.REACH: 0.10,
                Reach.THROWN: 0.50,
                Reach.RANGED: 1.0,
            }, children=[
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
        node(TailPlugin, name="tail"),
        *paired(WingPlugin, "wing"),
    ])

    # Age-variant size pool. Picked uniformly at spawn so any given
    # dragon could be a young (LARGE), mature (HUGE), or ancient
    # (COLOSSAL) specimen. Size cascades through the Size enum's
    # ``dodge_mod`` / ``defense_mod`` / ``hp_scale`` baked into base
    # stats at construction.
    SIZE_VARIANTS = [Size.LARGE, Size.HUGE, Size.COLOSSAL]

    VARIANTS = [
        {
            "flavor": "A {size} red @1, smelling faintly of cinnamon and charcoal.",
            "has_toes": False,
        },
        {
            "flavor": (
                "Unconfirmed reports suggest that this @1 may, in fact, have 62 toes. "
                "However, no one can get close enough to actually count."
            ),
            "has_toes": True,
        },
    ]

    # Per-hit narration: dragon scales shrug off most physical hits
    # at 0.5×; piercing finds the seams better but still chips at
    # 0.75×; ranged piercing combos (arrows) thread the gaps cleanly
    # at 1.5×. Flavor signals the matchup so players learn which
    # angle of attack is rewarded.
    HIT_NARRATIONS = {
        DamageTypes.SLASHING:    "The blade glances off @1a interlocking scales, biting only between the seams.",
        DamageTypes.BLUDGEONING: "The blow lands flat against @1a armored hide; @1s barely registers it.",
        DamageTypes.PIERCING:    "The point seeks the seam between @1a scales and finds purchase.",
        DamageTypes.RANGED:      "The shaft slips between @1a scales clean as breath, finding the soft tissue beneath.",
        DamageTypes.MAGICAL:     "Arcane force ripples across @1a hide, slowed by the deep magic that runs through every scale.",
    }

    def __init__(self):
        # Defense rolls 4d4 + 6 (range 10-22) — we want a meaningful
        # floor on dragon defense so low rolls don't trivialize the
        # apex boss. Expressed via the Q.6.3 ``NdM+C`` dice spec
        # support so the constant lives at the declaration site
        # rather than in a post-init patch.
        super().__init__(
            name="dragon",
            atk="3d10",
            defense="4d4+6",
            dodge="3d10",
            health_max="25d12"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE
        self.arrival = "A piercing roar rocks the heavens, as @1i swoops down out of the sky searching for prey."

        # Age-variant size pick: a young dragon is LARGE, a mature one
        # HUGE, an ancient one COLOSSAL. Set BEFORE flavor format so
        # the "{size} red dragon" substitution lands the actual size
        # (the prior-bug shape always rendered "medium" because
        # ``self.size`` defaulted to MEDIUM until ``self.size = ...``
        # later in __init__).
        self.size = choice(self.SIZE_VARIANTS)

        variant = choice(self.VARIANTS)
        self._has_toes = variant["has_toes"]
        self.flavor = variant["flavor"].format(size=self.size.name.lower())

        self.escape = "@1dc circles the area lazily before taking to the clouds, disappearing from sight."
        self.death = (
            "@1dc gives a final bellow of rage and disbelief as @1s falls to the ground. @1ac thrashing "
            "lasts but a moment, then all is still."
        )

        self.traits[DamageTypes.RANGED] = 1.00
        self.traits[DamageTypes.PIERCING] = 0.75
        self.traits[DamageTypes.PIERCING | DamageTypes.RANGED | DamageTypes.COMBINED] = 1.50
        self.traits[DamageTypes.ANY - (DamageTypes.RANGED | DamageTypes.PIERCING)] = 0.5

        self.loot["small_gem"] = 0.7
        self.loot["tee_shirt"] = 0.2
        self.loot["candy"] = 0.3
        self.loot["heavy_stringed_instrument"] = 0.2
        self.loot["mace"] = 0.3
        self.loot["wand"] = 0.1

        self.flags = {"flying"}

        # ``self.size`` was set above (before flavor format). Now that
        # body parts are composed by ``super().__init__``, scale per-
        # part HP against that size.
        self._scale_part_hp()

        # Enrage state: breath chance ramps each round since the last
        # breath (reset to 0 on fire). Any body part destroyed on the
        # dragon -- including a wing, which also grounds it -- forces a
        # breath on the dragon's next turn, accompanied by a rage intro.
        self._rounds_since_breath = 0
        self._known_destroyed_parts: set[str] = set()

    BREATH_BASE_CHANCE = 0.20
    BREATH_RAMP_PER_ROUND = 0.10

    def get_dodge(self):
        """Dragon dodge on top of the base Creature emergence.

        Base ``Creature.get_dodge`` already picks the right mobility
        source (wings while flying, legs once grounded) so a dragon
        with all four legs intact retains real dodge even after a
        wing destruction drops it out of the sky. The adjustments
        here are dragon-specific flavor:

        - **Flying bonus** (``×1.5``): a dragon on the wing is
          genuinely harder to hit than a ground-based creature of
          the same stats. The HUGE ``dodge_mod`` (``0.5``) scales
          dodge by mass; a flying dragon undoes half of that
          because mass in the air is still mobile.
        - **Toed-variant grounded penalty** (``-62``): if this is
          the 62-toe variant and it's been grounded, the ludicrous
          toe count tanks footwork. Pre-existing; preserved here.
        """
        base = super().get_dodge()
        flying = self.is_flying()
        if flying:
            base = int(base * 1.5)
        if self._has_toes and not flying:
            base -= 62
        return max(0, base)

    # Reacts to hugs.
    def on_hugged(self, actor: Creature, invocation: str) -> str:
        # TODO: Perhaps attack the hugger in some way.
        return "@1dc glowers hungrily at @2 and sends a wisp of flame in @2a direction."

    def breath_attack(self, combatants, rage_intro: str = "") -> str:
        flavor = parse(
            "@1dc's throat glows brightly, @1a head drawing back slightly as @1s breathes in deeply. With a "
            "deafening roar, @1s looses a mighty column of liquid flame, blanketing the entire area.",
            self,
        )
        if rage_intro:
            flavor = f"{parse(rage_intro, self)}\n{flavor}"

        # Build an AttackSequence with one result per victim. Breath
        # auto-hits (no dodge roll), applies the victim's FIRE trait
        # multiplier, then rolls 1d{defense} for absorbed damage per
        # victim (Q.7 trial — same dice-absorption regime as the
        # generic ``Creature.resolve_attack`` path).
        # Q.6.2: ``AttackResult.damage`` stores the post-defense value
        # (matching the shared resolve_attack convention); the compact
        # table's footer surfaces the raw → post-defense divergence.
        results = []
        post = ""
        for victim in combatants:
            raw_dice = Dice.from_ndn("6d6")
            raw = raw_dice.value
            df = victim.get_defense()
            multiplier = victim.get_trait_multiplier(DamageTypes.FIRE)
            sub_dmg = max(0, int(raw * multiplier))
            absorbed = _roll_absorption(df, sub_dmg)
            # Min-1 floor on landed breath: a hit that connects to a
            # non-immune target always registers at least 1, even on
            # max-roll absorption. Damage-type immunity (multiplier 0
            # → sub_dmg 0) is the only path to a true 0; the floor
            # only kicks in when sub_dmg > 0. Mirrors the
            # ``Creature.resolve_attack`` policy.
            dmg = max(1, sub_dmg - absorbed) if sub_dmg > 0 else 0

            # Construct a no-miss CombinedRoll using the actual damage dice.
            # The attack roll is a dummy — auto_hit=True will hide it.
            atk = AttackRoll(skill_bonus=0)
            atk.isCritical = False  # breath attacks don't crit
            atk.isFumble = False
            dmg_roll = DamageRoll(dice=raw_dice, weapon_bonus=0, skill_bonus=0)
            combined = CombinedRoll(atk, dmg_roll, dodge=0, is_miss=False)

            victim_name = getattr(victim, "name", "target")
            source = NaturalAttackSource(
                atk="6d6",
                dmg_type=DamageTypes.FIRE,
                label=victim_name,
            )
            results.append(
                AttackResult(
                    source=source,
                    combined=combined,
                    damage=dmg,
                    multiplier=multiplier,
                    defense=df,
                    absorbed=absorbed,
                    dodge=0,
                    dmg_type=DamageTypes.FIRE,
                    auto_hit=True,
                    # Q.6.3-followup: populate victim so the multi-
                    # target per-victim footer groups correctly
                    # without relying on the label string.
                    victim=victim,
                )
            )

            if p := victim.apply_damage(dmg):
                post += f"{p}\n"

        # Breath is always AOE: mark multi_target so the shared
        # compact-table footer breaks out per-victim totals instead
        # of rendering a single aggregate (which misleads readers
        # into thinking every victim took the combined damage).
        sequence = AttackSequence(
            attacker=self,
            target=combatants[0] if combatants else self,
            results=results,
            multi_target=len(combatants) > 1,
        )
        return f"{flavor}\n{sequence.to_markdown()}{post}"

    def _breath_chance(self) -> float:
        return min(
            1.0,
            self.BREATH_BASE_CHANCE
            + self._rounds_since_breath * self.BREATH_RAMP_PER_ROUND,
        )

    def _newly_destroyed_parts(self) -> set[str]:
        """Part names destroyed since the last time this was checked.

        Mutates ``self._known_destroyed_parts`` on every call, so each
        new destruction is reported exactly once. Single-caller by
        design (``attack_random``); a hypothetical peek-without-consume
        caller would silently swallow the force-fire signal.
        """
        current = {p.name for p in self.body_parts if p.is_destroyed()}
        new = current - self._known_destroyed_parts
        self._known_destroyed_parts = current
        return new

    def _rage_intro_for(self, newly_destroyed: set[str]) -> str:
        if any("wing" in n for n in newly_destroyed):
            return (
                "@1dc lets out a screeching roar, wings crumpling beneath "
                "it as it crashes to earth in a fury."
            )
        if newly_destroyed:
            return "@1dc bellows in pain and rage, eyes blazing red."
        return ""

    def attack_random(self, combatants: list, count=1) -> Optional[str]:
        """Thin override on the Phase 6b pipeline-driven base.

        Pre-empts the pipeline with a full-AOE breath weapon when the
        enrage RNG trips or a body part was destroyed since the last
        check; otherwise delegates to :meth:`MonsterPlugin.attack_random`
        so non-breath turns flow through ``pick_actions`` / ``resolve``
        / ``narrate_*`` stages like any other monster.

        Breath stays as a pre-empting branch (mirrors vampire's feed
        pattern) rather than landing as a creature-level action entry
        because it's AOE, auto-hits, subtracts defense once per victim,
        and runs through the shared FIRE trait multiplier — none of
        which fit the per-assignment shape the pipeline's ``resolve``
        stage is built around.

        Phase 6a compliance: :meth:`breath_attack` applies body HP
        directly via ``victim.apply_damage(dmg)`` for each victim, so
        the phase-6a removal of body-HP application from
        :meth:`Creature.resolve` has no impact here.
        """
        if combatants and 0 < count <= len(combatants):
            newly_destroyed = self._newly_destroyed_parts()

            if newly_destroyed or random() < self._breath_chance():
                self._rounds_since_breath = 0
                return self.breath_attack(
                    combatants,
                    rage_intro=self._rage_intro_for(newly_destroyed),
                )

            self._rounds_since_breath += 1
            return super().attack_random(combatants, count)

        return None
