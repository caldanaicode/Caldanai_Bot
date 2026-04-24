from random import choice
from typing import List, Optional

from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.combat.attack_source import AttackSource, NaturalAttackSource
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes, Size)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll


class MathTeacher(MonsterPlugin):
    BODY_TREE = humanoid_tree()

    # In-fiction display name ("flying math teacher") diverges from
    # the filename stem ("math_teacher"); register both so players
    # who type either in ``$spawn monster`` can resolve the plugin.
    ALIASES = ["flying math teacher"]

    def __init__(self):
        super().__init__(
            name="flying math teacher",
            atk="3d14",
            defense="3d6",
            dodge="3d6",
            health_max="6d14"
        )

        self.time_partition = TimePartitions.CREPUSCULAR | TimePartitions.NOCTURNAL
        self.image = None
        self.aggression = AggressionLevels.SURVIVE
        self.arrival = choice(
            [
                "The smell of whiteboard dust and stress wafts into the area.",
                "Wax wings make an odd sound as they pummel the air.",
            ]
        )

        self.flavor = choice(
            [
                "This @1 has an impressive array of tiny sand timers.",
                "A confounding quantity of board games surrounds this @1.",
                "@1dc eyes you mistrustfully, as if expecting to see a graphing calculator in your hand.",
                '"What do you get when you cross an elephant with a grape?"\n|| |elephant| ⨉ |grape| ⨉ sin(θ)||',
                '"What do you get when you cross an elephant with a mountain climber?"\n||You can\'t, because a mountain '
                "climber is a scaler.||",
            ]
        )

        self.escape = choice(
            [
                "@1dc issues homework assignments before vanishing back into the 9th dimension.",
                "Exhausted from a long day of dealing with idiots, @1d takes to the skies.",
                '@1dc boldly declares, "Time\'s up! Pencils down!" @1s then stuffs @1a papers and board games into a '
                "dimensional pocket and flutters away.",
            ]
        )
        self.death = choice(
            [
                "@1dc haltingly begins listing off the digits of π to the 900th decimal, trailing off after only a few.",
                "The students have surpassed the teacher, who can finally rest in peace.",
            ]
        )

        self.traits[DamageTypes.BLUDGEONING] = 1.25
        self.traits[DamageTypes.ANY - DamageTypes.BLUDGEONING] = 1

        self.size = Size.MEDIUM
        self.core_agility = 5
        self._scale_part_hp()

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                f"@1dc waves a dissuading finger in the face of @2.",
                f"@1dc arches a cynical eyebrow and sidesteps @2.",
            ]
        )

    @staticmethod
    def is_prime(number: int) -> bool:
        if number < 2:
            return False
        i = 2
        while i * i <= number:
            if number % i == 0:
                return False
            i += 1
        return True

    def get_attack_sources(self) -> List[AttackSource]:
        """MATHEMAGICAL attacks from the flying math teacher."""
        return [
            NaturalAttackSource(
                atk=self.attack,
                dmg_type=DamageTypes.MATHEMAGICAL,
                label=self.name.title(),
                skill="natural",
            )
        ]

    def _on_attack_resolved(self, source: AttackSource, result: AttackResult) -> None:
        """Doubles prime damage dealt by the math teacher and sets LORD OF PRIMES flavor."""
        if result.damage > 0 and self.is_prime(result.damage):
            result.damage *= 2
            result.extra_text = f"LORD OF PRIMES! * 2 = {result.damage}"

    def resolve_attack(
        self,
        attacker: Creature,
        source: AttackSource,
        atk_roll: AttackRoll,
        dmg_roll: DamageRoll,
        target_part=None,
    ) -> AttackResult:
        """Halves incoming prime damage and sets LORD OF PRIMES flavor.

        Q.6.2: check primality on ``sub_damage`` (the pre-defense,
        post-multiplier value) rather than ``damage`` (post-defense) —
        the trait is "the roll itself was prime," not "the post-armor
        damage was prime." Halving is still applied to the
        defense-adjusted ``damage`` so the lord-of-primes effect
        compounds with the per-hit defense subtract."""
        result = super().resolve_attack(
            attacker, source, atk_roll, dmg_roll,
            target_part=target_part,
        )
        # Guard on ``result.damage > 0`` so a pre-defense prime roll
        # that was fully absorbed by armor doesn't emit noisy "/ 2 = 0"
        # narration — nothing to halve.
        if result.damage > 0 and self.is_prime(result.sub_damage):
            result.damage //= 2
            result.extra_text = f"LORD OF PRIMES! / 2 = {result.damage}"
        return result
