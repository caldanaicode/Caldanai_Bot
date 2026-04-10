"""Tests for the MathTeacher monster plugin."""

from unittest.mock import MagicMock, patch

from Caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
from Caldanai.lib.rpg.helpers.enums import DamageTypes


class TestIsPrime:
    def test_primes(self):
        for p in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 97]:
            assert MathTeacher.is_prime(p) is True, f"{p} should be prime"

    def test_non_primes(self):
        for c in [-7, 0, 1, 4, 6, 8, 9, 10, 15, 25, 100]:
            assert MathTeacher.is_prime(c) is False, f"{c} should not be prime"


class TestDoAttack:
    def test_uses_mathemagical_damage_type(self):
        teacher = MathTeacher()
        target = MagicMock()
        target.on_attacked.return_value = ("attack msg```\n", 8)

        teacher.do_attack(target)

        args = target.on_attacked.call_args[0]
        assert args[3] == DamageTypes.MATHEMAGICAL

    def test_prime_damage_doubled(self):
        teacher = MathTeacher()
        target = MagicMock()
        target.on_attacked.return_value = ("attack msg```\n", 7)

        msg, dmg = teacher.do_attack(target)

        assert dmg == 14
        assert "LORD OF PRIMES" in msg

    def test_non_prime_damage_unchanged(self):
        teacher = MathTeacher()
        target = MagicMock()
        target.on_attacked.return_value = ("attack msg```\n", 8)

        msg, dmg = teacher.do_attack(target)

        assert dmg == 8
        assert "LORD OF PRIMES" not in msg


class TestOnAttacked:
    def test_prime_damage_halved_as_int(self):
        teacher = MathTeacher()

        with patch.object(type(teacher).__mro__[1], "on_attacked", return_value=("defense msg```\n", 7)):
            msg, dmg = teacher.on_attacked(MagicMock(), MagicMock(), MagicMock())

        assert dmg == 3
        assert isinstance(dmg, int)
        assert "LORD OF PRIMES" in msg

    def test_non_prime_damage_unchanged(self):
        teacher = MathTeacher()

        with patch.object(type(teacher).__mro__[1], "on_attacked", return_value=("defense msg```\n", 8)):
            msg, dmg = teacher.on_attacked(MagicMock(), MagicMock(), MagicMock())

        assert dmg == 8
        assert "LORD OF PRIMES" not in msg


class TestMathemagicalDamageType:
    def test_mathemagical_in_any_and_distinct_from_magical(self):
        assert DamageTypes.MATHEMAGICAL & DamageTypes.ANY
        assert DamageTypes.MATHEMAGICAL & DamageTypes.MAGICAL == 0
