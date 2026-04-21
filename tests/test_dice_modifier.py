"""Tests for ``Dice.from_ndn`` + ``Dice.__str__`` with the Q.6.3
signed-constant modifier extension (``"NdM+C"`` / ``"NdM-C"``)
and for the ``DamageRoll.__str__`` changes that render the
modifier as a distinct term.

The extension's contract:

- Parser accepts ``"NdM"``, ``"NdM+C"``, ``"NdM-C"``, ``"dM"``
  (count defaults to 1), and tolerates whitespace around the sign.
- ``Dice.value`` is the sum of rolls PLUS the modifier — downstream
  callers that add further bonuses on top get the correct total
  without a separate modifier pipe.
- ``Dice.__str__`` renders ``"NdM+C (r1, r2) + C"`` so the
  breakdown remains visible (per-die rolls + the constant term
  + the grand total).
- ``DamageRoll.__str__`` shows the dice modifier as its own term,
  after the parenthesized roll sum and before skill / weapon
  bonuses, matching the ``(6 + 5) + 2`` shape the design locked
  in.
"""

from unittest.mock import patch

from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.roll_data import DamageRoll


class TestFromNdnParsing:
    def test_plain_ndn_has_zero_modifier(self):
        d = Dice.from_ndn("2d6")
        assert d is not None
        assert d.count == 2
        assert d.sides == 6
        assert d.modifier == 0

    def test_positive_modifier(self):
        d = Dice.from_ndn("4d4+6")
        assert d.count == 4
        assert d.sides == 4
        assert d.modifier == 6

    def test_negative_modifier(self):
        d = Dice.from_ndn("3d10-2")
        assert d.count == 3
        assert d.sides == 10
        assert d.modifier == -2

    def test_whitespace_tolerated_around_sign(self):
        """Parser accepts ``"2d6 + 2"`` and ``"2d6  -  2"`` same as
        the unpadded forms."""
        assert Dice.from_ndn("2d6 + 2").modifier == 2
        assert Dice.from_ndn("2d6  -  2").modifier == -2
        assert Dice.from_ndn("  2d6+2  ").modifier == 2

    def test_implicit_count_of_one(self):
        """``"d20"`` is shorthand for ``"1d20"``; legacy behavior
        preserved under the extended parser."""
        d = Dice.from_ndn("d20")
        assert d.count == 1
        assert d.sides == 20

    def test_implicit_count_with_modifier(self):
        d = Dice.from_ndn("d8+3")
        assert d.count == 1
        assert d.sides == 8
        assert d.modifier == 3

    def test_garbage_returns_none(self):
        assert Dice.from_ndn("not a spec") is None
        assert Dice.from_ndn("2d") is None
        assert Dice.from_ndn("") is None
        assert Dice.from_ndn(None) is None

    def test_case_insensitive_d(self):
        """Legacy accepted both ``"2d6"`` and ``"2D6"`` — extended
        parser keeps that."""
        assert Dice.from_ndn("2D6").sides == 6
        assert Dice.from_ndn("2D6+2").modifier == 2


class TestValueIncludesModifier:
    def test_positive_modifier_adds_to_value(self):
        """``dice.value`` must equal ``sum(rolls) + modifier`` so
        downstream consumers don't need to track the modifier
        separately."""
        d = Dice.from_ndn("2d6+100")
        # Rolls are 1–6 each, so sum ∈ [2, 12]; modifier adds 100.
        assert 102 <= d.value <= 112

    def test_negative_modifier_subtracts_from_value(self):
        d = Dice.from_ndn("2d6-100")
        # value can go negative — no implicit clamp; callers decide.
        assert -98 <= d.value <= -88

    def test_rolls_tuple_unchanged_by_modifier(self):
        """Per-die rolls stay raw (pre-modifier) so a renderer can
        show ``(r1 + r2) + C`` rather than a pre-combined total."""
        d = Dice.from_ndn("2d6+5")
        for r in d.rolls:
            assert 1 <= r <= 6
        assert len(d.rolls) == 2


class TestGetNdnRoundtrip:
    def test_plain_roundtrips(self):
        assert Dice.from_ndn("2d6").get_ndn() == "2d6"

    def test_positive_roundtrips(self):
        assert Dice.from_ndn("4d4+6").get_ndn() == "4d4+6"

    def test_negative_roundtrips(self):
        assert Dice.from_ndn("3d10-2").get_ndn() == "3d10-2"

    def test_whitespace_normalized_out(self):
        """Input tolerates whitespace; canonical form has none."""
        assert Dice.from_ndn("2d6 + 2").get_ndn() == "2d6+2"


class TestStrBreakdown:
    def test_no_modifier_no_plus_zero(self):
        """"2d6" renders as ``"2d6 (r1, r2) = sum"`` — no ``+0``."""
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            d = Dice.from_ndn("2d6")
        s = str(d)
        assert "+ 0" not in s
        assert "- 0" not in s

    def test_positive_modifier_shown_as_plus(self):
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            d = Dice.from_ndn("2d6+2")
        s = str(d)
        assert "+ 2" in s

    def test_negative_modifier_shown_as_minus(self):
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            d = Dice.from_ndn("2d6-2")
        s = str(d)
        assert "- 2" in s


class TestDamageRollRendersModifier:
    """``DamageRoll.__str__`` must surface the dice-spec modifier
    as its own term — the shape design locked in is
    ``(r1 + r2) + modifier + skill + weapon = total``."""

    def test_shape_with_modifier_only(self):
        """"2d6+2" rolled (6, 5) → ``"(6 + 5) + 2 = 13"``."""
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            dice = Dice.from_ndn("2d6+2")
        roll = DamageRoll(dice=dice, skill_bonus=0, weapon_bonus=0)
        s = str(roll)
        assert "(6 + 5)" in s
        assert "+ 2" in s
        assert "= 13" in s

    def test_no_modifier_no_bonus_shows_bare_sum(self):
        """2d6 with no bonuses: ``"(6 + 5)"`` — no ``+0`` terms,
        no trailing ``= 11``."""
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            dice = Dice.from_ndn("2d6")
        roll = DamageRoll(dice=dice, skill_bonus=0, weapon_bonus=0)
        s = str(roll)
        assert s == "(6 + 5)"

    def test_modifier_coexists_with_weapon_bonus(self):
        """Both the in-spec modifier and the runtime weapon_bonus are
        surfaced as distinct terms — callers using both pipes get
        the full breakdown."""
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            dice = Dice.from_ndn("2d6+2")
        roll = DamageRoll(dice=dice, skill_bonus=0, weapon_bonus=3)
        s = str(roll)
        assert "(6 + 5)" in s
        assert "+ 2" in s   # dice modifier
        assert "+ 3" in s   # weapon bonus
        # All three terms plus dice sum = 16
        assert "= 16" in s

    def test_negative_modifier_renders_as_minus(self):
        with patch(
            "caldanai.lib.rpg.helpers.dice.randint",
            side_effect=[6, 5],
        ):
            dice = Dice.from_ndn("2d6-3")
        roll = DamageRoll(dice=dice, skill_bonus=0, weapon_bonus=0)
        s = str(roll)
        assert "- 3" in s
        assert "= 8" in s  # 11 - 3
