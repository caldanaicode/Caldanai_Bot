"""Tests for the MathTeacher monster plugin."""

from unittest.mock import MagicMock, patch

from Caldanai.lib.rpg.combat.attack_result import AttackResult
from Caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from Caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
from Caldanai.lib.rpg.helpers.enums import DamageTypes
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, CombinedRoll, DamageRoll
from Caldanai.lib.rpg.helpers.dice import Dice


class TestIsPrime:
    def test_primes(self):
        for p in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 97]:
            assert MathTeacher.is_prime(p) is True, f"{p} should be prime"

    def test_non_primes(self):
        for c in [-7, 0, 1, 4, 6, 8, 9, 10, 15, 25, 100]:
            assert MathTeacher.is_prime(c) is False, f"{c} should not be prime"


class TestAttackSources:
    def test_uses_mathemagical_damage_type(self):
        teacher = MathTeacher()
        sources = teacher.get_attack_sources()
        assert len(sources) == 1
        assert sources[0].damage_type == DamageTypes.MATHEMAGICAL


def _make_result_with_damage(damage: int, dmg_type=DamageTypes.MATHEMAGICAL):
    """Build a minimal AttackResult with a specific damage value."""
    atk = AttackRoll(skill_bonus=0)
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    combined = CombinedRoll(atk, dmg, 0)
    source = NaturalAttackSource(atk="1d4", dmg_type=dmg_type)
    return AttackResult(
        source=source,
        combined=combined,
        damage=damage,
        multiplier=1.0,
        defense=0,
        dodge=0,
        dmg_type=dmg_type,
    )


class TestOutgoingPrimeDoubling:
    def test_prime_damage_is_doubled_on_resolve(self):
        """When math teacher attacks, prime damage results should be doubled."""
        teacher = MathTeacher()
        source = teacher.get_attack_sources()[0]
        result = _make_result_with_damage(7)

        teacher._on_attack_resolved(source, result)

        assert result.damage == 14
        assert "LORD OF PRIMES" in result.extra_text

    def test_non_prime_damage_unchanged(self):
        teacher = MathTeacher()
        source = teacher.get_attack_sources()[0]
        result = _make_result_with_damage(8)

        teacher._on_attack_resolved(source, result)

        assert result.damage == 8
        assert result.extra_text == ""


class TestIncomingPrimeHalving:
    def test_prime_damage_halved_as_int(self):
        """When math teacher is attacked, prime damage is halved via resolve_attack."""
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0

        attacker = MagicMock()
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        # Force atk/dmg rolls that produce prime damage (7)
        atk = AttackRoll(skill_bonus=20)  # auto hit
        dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
        dmg.result = 7  # force prime damage

        with patch.object(
            MathTeacher.__mro__[1], "resolve_attack",
            return_value=_make_result_with_damage(7, dmg_type=DamageTypes.SLASHING)
        ):
            result = teacher.resolve_attack(attacker, source, atk, dmg)

        assert result.damage == 3  # 7 // 2
        assert isinstance(result.damage, int)
        assert "LORD OF PRIMES" in result.extra_text

    def test_non_prime_damage_unchanged(self):
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0
        attacker = MagicMock()
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        atk = AttackRoll(skill_bonus=20)
        dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)

        with patch.object(
            MathTeacher.__mro__[1], "resolve_attack",
            return_value=_make_result_with_damage(8, dmg_type=DamageTypes.SLASHING)
        ):
            result = teacher.resolve_attack(attacker, source, atk, dmg)

        assert result.damage == 8
        assert result.extra_text == ""


class TestMathemagicalDamageType:
    def test_mathemagical_in_any_and_distinct_from_magical(self):
        assert DamageTypes.MATHEMAGICAL & DamageTypes.ANY
        assert DamageTypes.MATHEMAGICAL & DamageTypes.MAGICAL == 0
