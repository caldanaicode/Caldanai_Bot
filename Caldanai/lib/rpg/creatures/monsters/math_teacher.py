from random import choice
from typing import List

from Caldanai.lib.rpg.combat.attack_result import AttackResult
from Caldanai.lib.rpg.combat.attack_source import AttackSource, NaturalAttackSource
from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from Caldanai.lib.rpg.helpers.enums import (
    AggressionLevels, TimePartitions, DamageTypes)
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll


class MathTeacher(MonsterPlugin):
    def __init__(self):
        super().__init__(
            name="flying math teacher",
            atk="3d14",
            defense="3d6",
            dodge="3d6",
            health_max="3d14"
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
                "The @1 eyes you mistrustfully, as if expecting to see a graphing calculator in your hand.",
                '"What do you get when you cross an elephant with a grape?"\n|| |elephant| ⨉ |grape| ⨉ sin(θ)||',
                '"What do you get when you cross an elephant with a mountain climber?"\n||You can\'t, because a mountain '
                "climber is a scaler.||",
            ]
        )

        self.escape = choice(
            [
                "The @1 issues homework assignments before vanishing back into the 9th dimension.",
                "Exhausted from a long day of dealing with idiots, the @1 takes to the skies.",
                'The @1 boldly declares, "Time\'s up! Pencils down!" @1s then stuffs @1a papers and board games into a '
                "dimensional pocket and flutters away.",
            ]
        )
        self.death = choice(
            [
                "The @1 haltingly begins listing off the digits of π to the 900th decimal, trailing off after only a few.",
                "The students have surpassed the teacher, who can finally rest in peace.",
            ]
        )

        self.traits[DamageTypes.BLUDGEONING] = 1.25
        self.traits[DamageTypes.ANY - DamageTypes.BLUDGEONING] = 1

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        return choice(
            [
                f"The @1 waves a dissuading finger in the face of @2.",
                f"The @1 arches a cynical eyebrow and sidesteps @2.",
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
        if self.is_prime(result.damage):
            result.damage *= 2
            result.extra_text = f"__LORD OF PRIMES!__ * 2 = {result.damage}"

    def resolve_attack(
        self,
        attacker: Creature,
        source: AttackSource,
        atk_roll: AttackRoll,
        dmg_roll: DamageRoll,
    ) -> AttackResult:
        """Halves incoming prime damage and sets LORD OF PRIMES flavor."""
        result = super().resolve_attack(attacker, source, atk_roll, dmg_roll)
        if self.is_prime(result.damage):
            result.damage //= 2
            result.extra_text = f"__LORD OF PRIMES!__ / 2 = {result.damage}"
        return result
