"""Q.7 trial: per-hit absorption rolls ``1d{defense}`` instead of
flat-subtracting the defense pool.

Pre-Q.7: ``damage = max(1, sub_dmg - defense)`` — an attack against
defense 7 deterministically had 7 absorbed off the top.

Q.7: ``absorbed = min(1d{defense}, sub_dmg)``, ``damage = max(0,
sub_dmg - absorbed)``. The rolled absorption replaces the flat
subtract; the hit-floor of 1 is gone (a max-roll absorber on a low
hit can now reduce damage to 0 — full block, like a 40k save).

These tests pin:

- The roll happens once per hit (``Dice.quick_roll("1d{defense}")``).
- The roll is bounded above by ``sub_dmg`` (can't absorb more than
  the hit landed).
- ``defense == 0`` skips the roll entirely (no ``1d0``).
- ``defense == 1`` shortcuts past ``Dice.from_ndn`` (which rejects
  ``sides < 2``) and absorbs at most 1.
- The ``absorbed`` field is recorded on :class:`AttackResult` so the
  renderer can show ``-{absorbed}(d{defense})`` without recomputing.
"""

from unittest.mock import patch

import pytest

from caldanai.lib.rpg.combat.attack_result import AttackResult
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures import Creature, _roll_absorption
from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll


def _force_hit_rolls(dmg_value: int):
    """Force deterministic atk + dmg rolls so resolve_attack lands a
    non-crit, non-fumble hit with ``combined.result == dmg_value``."""
    atk = AttackRoll(skill_bonus=0)
    atk.rolls = (19,)
    atk.result = 19
    atk.isCritical = False
    atk.isFumble = False
    dmg = DamageRoll.__new__(DamageRoll)
    dmg.dice = None
    dmg.weapon_bonus = 0
    dmg.skill_bonus = 0
    dmg.result = dmg_value
    return atk, dmg


def _make_target(defense: int = 0, dodge: int = 0):
    """Body-less target so the partless ``resolve_attack`` branch runs
    (creature-wide ``get_defense`` / ``get_dodge``, no walk)."""
    return Creature(
        name="dummy", atk="1d4", defense=defense, dodge=dodge,
        health_max=100, health=100,
    )


def _make_attacker():
    return Creature(
        name="atk", atk="1d4", defense=0, dodge=0,
        health_max=50, health=50,
    )


# ---------------------------------------------------------------------------
# _roll_absorption — the helper itself
# ---------------------------------------------------------------------------


class TestRollAbsorptionHelper:
    def test_zero_defense_skips_roll(self):
        """Defense 0 produces no absorption — no ``1d0``. ``Dice.quick_roll``
        is never called."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            assert _roll_absorption(0, 10) == 0
            mock_roll.assert_not_called()

    def test_negative_defense_treated_as_zero(self):
        """Defensive: a negative defense pool (shouldn't happen but
        could surface from a buggy debuff) skips the roll."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            assert _roll_absorption(-3, 10) == 0
            mock_roll.assert_not_called()

    def test_zero_raw_skips_roll(self):
        """No incoming damage to absorb against — skip the roll."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            assert _roll_absorption(7, 0) == 0
            mock_roll.assert_not_called()

    def test_defense_one_shortcuts_to_one(self):
        """``Dice.from_ndn`` rejects ``sides < 2`` — ``1d1`` would
        return None and crash combat. The helper shortcuts to the
        deterministic 1, bounded by ``raw``."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            assert _roll_absorption(1, 10) == 1
            mock_roll.assert_not_called()

    def test_defense_one_bounded_by_raw(self):
        """Even at defense 1, the helper can't absorb more than the
        hit. Raw 0 already short-circuited; raw < 1 is impossible
        with positive ints — pin the min(1, raw) shape anyway."""
        assert _roll_absorption(1, 1) == 1

    def test_roll_bounded_above_by_raw(self):
        """Rolled absorption is bounded by ``raw`` — a d7 rolling 5
        against a 3-damage hit absorbs 3, not 5."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=5,
        ):
            assert _roll_absorption(7, 3) == 3

    def test_roll_passthrough_under_raw(self):
        """When the roll is under ``raw``, the rolled value is the
        absorbed amount."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=4,
        ):
            assert _roll_absorption(7, 100) == 4

    def test_max_roll_matches_full_pool(self):
        """A max roll on the d{N} absorbs N — matches the pre-Q.7
        flat-subtract behaviour at the top end of the distribution."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=7,
        ):
            assert _roll_absorption(7, 100) == 7

    def test_min_roll_is_breach(self):
        """A roll of 1 absorbs 1 — full breach moment."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=1,
        ):
            assert _roll_absorption(7, 100) == 1

    def test_uses_quick_roll_with_correct_spec(self):
        """The helper builds the dice spec ``1d{defense}`` and hands
        it to ``Dice.quick_roll`` — pin the call shape so a future
        refactor can't silently switch to ``Ndefense`` / ``2dN/2`` /
        any other distribution."""
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=4,
        ) as mock_roll:
            _roll_absorption(7, 100)
            mock_roll.assert_called_once_with("1d7")


# ---------------------------------------------------------------------------
# Creature.resolve_attack — end-to-end through the resolver
# ---------------------------------------------------------------------------


class TestResolveAttackUsesDiceAbsorption:
    """The dice absorption fires inside ``Creature.resolve_attack``
    and lands on ``result.absorbed`` + ``result.damage``."""

    def test_low_roll_passes_more_damage(self):
        """defense 7, raw 10. Mocked d7=1 → absorbed 1, final 9.
        The "breach" moment — defender's armor barely caught it."""
        target = _make_target(defense=7)
        attacker = _make_attacker()
        atk, dmg = _force_hit_rolls(10)
        source = NaturalAttackSource(atk="1d4", label="test")

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll", return_value=1,
        ):
            result = target.resolve_attack(attacker, source, atk, dmg)

        assert result.absorbed == 1
        assert result.damage == 9
        assert result.defense == 7

    def test_mid_roll_partial_block(self):
        """defense 7, raw 10. Mocked d7=4 → absorbed 4, final 6.
        Middle-of-the-road absorption, the common case."""
        target = _make_target(defense=7)
        attacker = _make_attacker()
        atk, dmg = _force_hit_rolls(10)
        source = NaturalAttackSource(atk="1d4", label="test")

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll", return_value=4,
        ):
            result = target.resolve_attack(attacker, source, atk, dmg)

        assert result.absorbed == 4
        assert result.damage == 6

    def test_max_roll_full_block(self):
        """defense 7, raw 10. Mocked d7=7 → absorbed 7, final 3.
        Matches the pre-Q.7 flat-subtract behaviour at the max-roll
        end of the distribution."""
        target = _make_target(defense=7)
        attacker = _make_attacker()
        atk, dmg = _force_hit_rolls(10)
        source = NaturalAttackSource(atk="1d4", label="test")

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll", return_value=7,
        ):
            result = target.resolve_attack(attacker, source, atk, dmg)

        assert result.absorbed == 7
        assert result.damage == 3

    def test_overabsorb_clamps_to_raw(self):
        """defense 7, raw 3. Mocked d7=5 → absorbed min(5, 3) = 3,
        final 0. Armor can't absorb more than the hit landed."""
        target = _make_target(defense=7)
        attacker = _make_attacker()
        atk, dmg = _force_hit_rolls(3)
        source = NaturalAttackSource(atk="1d4", label="test")

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll", return_value=5,
        ):
            result = target.resolve_attack(attacker, source, atk, dmg)

        assert result.absorbed == 3
        assert result.damage == 0

    def test_zero_defense_no_roll_no_absorption(self):
        """defense 0, raw 10. No roll fires; absorbed=0, damage=10.
        The d0 case the helper guards against — pin that the resolver
        respects the guard end-to-end. ``Creature.__init__`` treats
        falsy defense as 1 (legacy default), so override on the
        instance after construction."""
        target = _make_target(defense=1)
        target.defense = 0  # force-zero past the __init__ default
        attacker = _make_attacker()
        atk, dmg = _force_hit_rolls(10)
        source = NaturalAttackSource(atk="1d4", label="test")

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            result = target.resolve_attack(attacker, source, atk, dmg)
            mock_roll.assert_not_called()

        assert result.absorbed == 0
        assert result.damage == 10
        assert result.defense == 0

    def test_miss_skips_absorption_entirely(self):
        """A miss never reaches the absorption branch — ``damage`` is
        0 and ``absorbed`` stays at the default 0. The d{N} doesn't
        burn dice on a swing that didn't connect."""
        target = _make_target(defense=7, dodge=99)  # dodge can't be beat
        attacker = _make_attacker()
        atk = AttackRoll(skill_bonus=0)
        atk.rolls = (1,)
        atk.result = 1
        atk.isCritical = False
        atk.isFumble = False
        dmg = DamageRoll.__new__(DamageRoll)
        dmg.dice = None
        dmg.weapon_bonus = 0
        dmg.skill_bonus = 0
        dmg.result = 10
        source = NaturalAttackSource(atk="1d4", label="test")

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            result = target.resolve_attack(attacker, source, atk, dmg)
            mock_roll.assert_not_called()

        assert result.combined.isMiss is True
        assert result.damage == 0
        assert result.absorbed == 0

    def test_full_immunity_skips_absorption(self):
        """``multiplier == 0`` (full immunity) zeroes damage before
        the absorption branch — no roll fires. Pin so a future
        refactor can't silently spend a d{N} on damage that was
        already neutralized."""
        target = _make_target(defense=7)
        target.traits = {DamageTypes.FIRE: 0.0}
        attacker = _make_attacker()
        atk, dmg = _force_hit_rolls(10)
        source = NaturalAttackSource(
            atk="1d4", dmg_type=DamageTypes.FIRE, label="test",
        )

        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
        ) as mock_roll:
            result = target.resolve_attack(attacker, source, atk, dmg)
            mock_roll.assert_not_called()

        assert result.damage == 0
        assert result.absorbed == 0


# ---------------------------------------------------------------------------
# AttackResult.absorbed field
# ---------------------------------------------------------------------------


class TestAttackResultAbsorbedField:
    """The ``absorbed`` field carries the rolled absorption so the
    renderer can show both the rolled value AND the underlying d{N}
    pool without re-deriving from ``sub_damage - damage``."""

    def test_default_absorbed_zero(self):
        """Unset ``absorbed`` defaults to 0 — covers the partless
        miss path and any caller that hand-builds an AttackResult."""
        from caldanai.lib.rpg.helpers.roll_data import CombinedRoll
        atk = AttackRoll(skill_bonus=0)
        atk.rolls = (15,)
        atk.result = 15
        atk.isCritical = False
        atk.isFumble = False
        dmg = DamageRoll.__new__(DamageRoll)
        dmg.dice = None
        dmg.weapon_bonus = 0
        dmg.skill_bonus = 0
        dmg.result = 5
        dmg.rolls = (5,)
        dmg.diceModifier = 0
        dmg.skillBonus = 0
        dmg.weaponBonus = 0
        combined = CombinedRoll(atk, dmg, dodge=10)
        source = NaturalAttackSource(atk="1d4", label="test")
        result = AttackResult(
            source=source, combined=combined, damage=5,
            multiplier=1.0, defense=0, dodge=10,
        )
        assert result.absorbed == 0

    def test_to_display_parts_exposes_absorbed(self):
        """``to_display_parts`` is the renderer's input contract;
        the absorbed value must surface there for the Def column."""
        from caldanai.lib.rpg.helpers.roll_data import CombinedRoll
        atk = AttackRoll(skill_bonus=0)
        atk.rolls = (15,)
        atk.result = 15
        atk.isCritical = False
        atk.isFumble = False
        dmg = DamageRoll.__new__(DamageRoll)
        dmg.dice = None
        dmg.weapon_bonus = 0
        dmg.skill_bonus = 0
        dmg.result = 10
        dmg.rolls = (10,)
        dmg.diceModifier = 0
        dmg.skillBonus = 0
        dmg.weaponBonus = 0
        combined = CombinedRoll(atk, dmg, dodge=10)
        source = NaturalAttackSource(atk="1d4", label="test")
        result = AttackResult(
            source=source, combined=combined, damage=6,
            multiplier=1.0, defense=7, absorbed=4, dodge=10,
        )
        parts = result.to_display_parts()
        assert parts["absorbed"] == 4
        assert parts["defense"] == 7


# ---------------------------------------------------------------------------
# Renderer — Def column shows -{absorbed}(d{defense})
# ---------------------------------------------------------------------------


class TestDefColumnFormat:
    """Q.7 trial: the Def column shows the rolled absorption plus the
    underlying d{N} pool so the player sees both the dice outcome AND
    the pool that produced it."""

    def _seq(self, results):
        from unittest.mock import MagicMock
        from caldanai.lib.rpg.combat.attack_result import AttackSequence
        attacker = MagicMock()
        attacker.name = "bandit"
        attacker.member = None
        target = MagicMock()
        target.name = "Caels"
        return AttackSequence(
            attacker=attacker, target=target, results=results,
        )

    def _result(self, *, damage, defense, absorbed, is_miss=False,
                multiplier=1.0):
        from caldanai.lib.rpg.helpers.roll_data import CombinedRoll
        atk = AttackRoll(skill_bonus=0)
        atk.rolls = (1 if is_miss else 15,)
        atk.result = 1 if is_miss else 15
        atk.isCritical = False
        atk.isFumble = False
        dmg = DamageRoll.__new__(DamageRoll)
        dmg.dice = None
        dmg.weapon_bonus = 0
        dmg.skill_bonus = 0
        dmg.result = damage + absorbed
        dmg.rolls = (damage + absorbed,)
        dmg.diceModifier = 0
        dmg.skillBonus = 0
        dmg.weaponBonus = 0
        combined = CombinedRoll(atk, dmg, dodge=10)
        source = NaturalAttackSource(atk="1d4", label="Left")
        return AttackResult(
            source=source, combined=combined, damage=damage,
            multiplier=multiplier, defense=defense, absorbed=absorbed,
            dodge=10,
        )

    def test_def_column_shows_absorbed_and_pool(self):
        """A hit absorbing 4 against a d7 pool renders ``-4(d7)``."""
        seq = self._seq([
            self._result(damage=6, defense=7, absorbed=4),
        ])
        md = seq.to_markdown()
        assert "-4(d7)" in md

    def test_def_column_shows_zero_for_zero_defense(self):
        """``defense == 0`` collapses to a bare ``0`` — no roll fired,
        no pool to show."""
        seq = self._seq([
            self._result(damage=10, defense=0, absorbed=0),
        ])
        md = seq.to_markdown()
        # The Def cell on this row is just "0".
        assert "(d0)" not in md  # no degenerate d0 in the output

    def test_def_column_shows_dash_on_miss(self):
        """Misses render ``-`` in the Def column — no contact, no
        absorption math at all."""
        seq = self._seq([
            self._result(damage=0, defense=7, absorbed=0, is_miss=True),
        ])
        md = seq.to_markdown()
        assert "(d7)" not in md  # no roll on a miss

    def test_def_column_full_block_renders_pool(self):
        """A max-roll absorption (d7=7 against a 7-raw hit) renders
        ``-7(d7)`` — the rare full-block case."""
        seq = self._seq([
            self._result(damage=0, defense=7, absorbed=7),
        ])
        md = seq.to_markdown()
        assert "-7(d7)" in md
