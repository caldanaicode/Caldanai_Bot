from random import choice, random

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Reach, Size)
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, CombinedRoll, DamageRoll
from caldanai.lib.rpg.creatures import Creature


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

    def __init__(self):
        super().__init__(
            name="dragon",
            atk="3d10",
            defense="3d8",
            dodge="3d10",
            health_max="25d12"
        )

        self.time_partition = TimePartitions.CATHEMERAL
        self.image = None
        self.aggression = AggressionLevels.RAMPAGE
        self.arrival = "A piercing roar rocks the heavens, as @1i swoops down out of the sky searching for prey."

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
        self.body_parts = BodyPart.quadruped_winged()
        # Swap the generic head for dragon-specific low-melee-exposure head
        self.body_parts = [p for p in self.body_parts if p.name != "head"]
        self.body_parts.append(BodyPart.make("head", name="head",
            exposure={Reach.MELEE: 0.05, Reach.REACH: 0.10, Reach.THROWN: 0.50, Reach.RANGED: 1.0}))
        # Mark the torso as critical (dragon dies when torso is destroyed)
        for p in self.body_parts:
            if p.name == "torso":
                p.is_critical = True
                break

        self.size = Size.HUGE
        self._scale_part_hp()

    def get_dodge(self):
        base = super().get_dodge()
        if self._has_toes and not self.is_flying():
            base -= 62
        return max(0, base)

    # Reacts to hugs.
    def on_hugged(self, actor: Creature, invocation: str) -> str:
        # TODO: Perhaps attack the hugger in some way.
        return "@1dc glowers hungrily at @2 and sends a wisp of flame in @2a direction."

    def breath_attack(self, combatants) -> str:
        flavor = parse(
            "@1dc's throat glows brightly, @1a head drawing back slightly as @1s breathes in deeply. With a "
            "deafening roar, @1s looses a mighty column of liquid flame, blanketing the entire area.",
            self,
        )

        # Build an AttackSequence with one result per victim. Breath bypasses
        # the normal dodge/defense flow — every victim is auto-hit and we
        # compute damage as raw - defense directly.
        results = []
        post = ""
        for victim in combatants:
            raw_dice = Dice.from_ndn("6d6")
            raw = raw_dice.value
            df = victim.get_defense()
            dmg = max(0, raw - df)

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
                    multiplier=1.0,
                    defense=df,
                    dodge=0,
                    dmg_type=DamageTypes.FIRE,
                    auto_hit=True,
                )
            )

            if p := victim.apply_damage(dmg):
                post += f"{p}\n"

        sequence = AttackSequence(attacker=self, target=combatants[0] if combatants else self, results=results)
        return f"{flavor}\n{sequence.to_markdown()}{post}"

    def attack_random(self, combatants: list, count=1) -> str:
        if combatants and 0 < count <= len(combatants):
            if random() < 0.2:
                return self.breath_attack(combatants)

            return super().attack_random(combatants, count)

        return None
