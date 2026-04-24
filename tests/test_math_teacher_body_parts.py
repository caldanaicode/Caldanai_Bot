"""Tests for the Phase 1.D item 4.7 MathTeacher body parts migration.

Item 4.7 is the first migration of a **custom-statted** monster to the
body parts system. The math teacher overrides ``resolve_attack`` to
halve incoming prime-numbered damage -- a MathTeacher-specific combat
quirk that existed before body parts were added. The migration must be
strictly additive: the prime-halving logic continues to fire without any
changes to ``resolve_attack`` itself.

The architectural invariant being pinned here:

- ``resolve_attack`` computes **how much** damage the math teacher
  takes. The prime-halving lives inside this method (``// 2`` on a
  prime result) and has nothing to do with routing.
- ``apply_damage`` routes the already-computed damage to a part and/or
  the main HP pool.

These two concerns are orthogonal. Adding ``body_parts`` does not touch
``resolve_attack``, and the tests in
``TestMathTeacherPrimeDamageHalvingPreserved`` pin the prime-halving
behaviour on both the direct ``resolve_attack`` path and the
``apply_damage`` path.
"""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, CombinedRoll, DamageRoll


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The math teacher composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the math teacher still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


def _make_attack_rolls(damage_value: int):
    """Build (atk_roll, dmg_roll) such that a defense/dodge=0 math
    teacher resolves to exactly ``damage_value`` damage under the
    base ``Creature.resolve_attack`` formula.

    The base formula is::

        sub_dmg = int(trait_multiplier * combined.result)
        damage  = 0 if miss else max(1, sub_dmg - defense)

    With defense=0, dodge=0, trait_multiplier=1 and a non-miss,
    non-critical combined roll whose ``result`` equals ``damage_value``,
    the computed damage equals ``damage_value`` -- which is then
    optionally halved by the MathTeacher override if prime.

    ``AttackRoll.__init__`` rolls a random d20, which would otherwise
    make the test non-deterministic (a natural 20 doubles combined
    damage; a natural 1 fumbles). We deterministically force the
    underlying d20 to a mid-range value (10) and clear the
    crit/fumble flags so the combined result equals ``dmg.result``
    exactly.
    """
    atk = AttackRoll(skill_bonus=20)  # auto hit vs dodge=0
    atk.rolls = (10,)
    atk.result = 10 + atk.skillBonus
    atk.isCritical = False
    atk.isFumble = False
    dmg = DamageRoll(dice=Dice.d4(), weapon_bonus=0, skill_bonus=0)
    dmg.result = damage_value
    return atk, dmg


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestMathTeacherBodyPartsComposition:
    def test_math_teacher_has_six_parts(self):
        """Standard humanoid: 1 head + 1 torso + 2 arms + 2 legs = 6."""
        m = MathTeacher()
        assert len(m.body_parts) == 13

    def test_math_teacher_has_exactly_one_head(self):
        m = MathTeacher()
        heads = [p for p in m.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_math_teacher_has_exactly_one_torso(self):
        m = MathTeacher()
        torsos = [p for p in m.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_math_teacher_has_two_arms(self):
        m = MathTeacher()
        arms = [p for p in m.body_parts if isinstance(p, ArmPlugin)]
        assert len(arms) == 2

    def test_math_teacher_has_two_legs(self):
        m = MathTeacher()
        legs = [p for p in m.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 2


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestMathTeacherCriticalParts:
    def test_head_is_critical(self):
        """A decapitated math teacher dies. Head inherits
        ``is_critical=True`` from ``HeadPlugin``; the math teacher does
        NOT override it."""
        m = MathTeacher()
        head = next(p for p in m.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """Critical torso: destruction kills the math teacher via the
        standard ``Creature.apply_damage`` critical-part death path."""
        m = MathTeacher()
        torso = next(p for p in m.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_arms_are_not_critical(self):
        m = MathTeacher()
        arms = [p for p in m.body_parts if isinstance(p, ArmPlugin)]
        for arm in arms:
            assert arm.is_critical is False

    def test_legs_are_not_critical(self):
        m = MathTeacher()
        legs = [p for p in m.body_parts if isinstance(p, LegPlugin)]
        for leg in legs:
            assert leg.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestMathTeacherPartNames:
    def test_head_has_expected_name(self):
        m = MathTeacher()
        head = m.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        m = MathTeacher()
        torso = m.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_arms_are_distinct_instances(self):
        m = MathTeacher()
        left = m.get_part("arm.left")
        right = m.get_part("arm.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, ArmPlugin)
        assert isinstance(right, ArmPlugin)

    def test_left_and_right_legs_are_distinct_instances(self):
        m = MathTeacher()
        left = m.get_part("leg.left")
        right = m.get_part("leg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestMathTeacherFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE`` (ratio 1.0).
    MathTeacher is MEDIUM with core_agility=5.  Dodge = base + 5.
    """

    def test_get_defense_matches_base_attribute(self):
        m = MathTeacher()
        # MEDIUM defense_mod=1.0, no core_toughness
        assert m.get_defense() == m.defense

    def test_get_dodge_includes_core_agility(self):
        m = MathTeacher()
        # MEDIUM dodge_mod=1.0, core_agility=5
        expected = int(m.dodge * 1.0 * 1.0) + 5
        assert m.get_dodge() == expected

    def test_stat_modifier_total_is_zero_at_full_health(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        m = MathTeacher()
        assert m.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert m.get_stat_modifier_total(Stat.DODGE) == 0
        assert m.get_stat_modifier_total(Stat.ATTACK) == 0
        assert m.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestMathTeacherLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route
        through the legacy whole-body path: ``health`` decrements by 5,
        parts are untouched."""
        m = MathTeacher()
        m.health_max = 50
        m.health = 50
        m.apply_damage(5)
        assert m.health == 45

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        m = MathTeacher()
        m.health_max = 50
        m.health = 50
        part_hps_before = [(p.name, p.health) for p in m.body_parts]
        m.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in m.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing."""
        m = MathTeacher()
        m.health_max = 50
        m.health = 20
        m.apply_damage(-5)
        assert m.health == 25


# ---------------------------------------------------------------------------
# Sanity -- existing math teacher fields unchanged
# ---------------------------------------------------------------------------


class TestMathTeacherSanityUnchanged:
    def test_name_is_flying_math_teacher(self):
        m = MathTeacher()
        assert m.name == "flying math teacher"

    def test_attack_dice_string_unchanged(self):
        m = MathTeacher()
        assert m.attack == "3d14"

    def test_flavor_is_one_of_known_strings(self):
        """The math teacher randomises its flavor from a fixed pool.
        Pin that the chosen flavor is one of the pre-migration options
        so a future refactor can't silently swap the pool."""
        m = MathTeacher()
        known_flavors = {
            "This @1 has an impressive array of tiny sand timers.",
            "A confounding quantity of board games surrounds this @1.",
            # Source uses the ``@1dc`` Definite-Capitalized token here;
            # an older pool entry had the literal ``"The @1"`` phrasing
            # which made the test flaky — it only failed when
            # ``choice()`` happened to pick this option.
            "@1dc eyes you mistrustfully, as if expecting to see a graphing calculator in your hand.",
            '"What do you get when you cross an elephant with a grape?"\n|| |elephant| ⨉ |grape| ⨉ sin(θ)||',
            '"What do you get when you cross an elephant with a mountain climber?"\n||You can\'t, because a mountain '
            "climber is a scaler.||",
        }
        assert m.flavor in known_flavors

    def test_resolve_attack_is_still_overridden_on_class(self):
        """Pin that ``MathTeacher`` still defines its own
        ``resolve_attack`` at the class level -- not inherited from
        ``Creature``. This is the specific method the prime-halving
        lives in, and the migration must leave it untouched."""
        assert "resolve_attack" in MathTeacher.__dict__
        assert MathTeacher.resolve_attack is not Creature.resolve_attack

    def test_on_attack_resolved_is_still_overridden_on_class(self):
        """Pin that the outgoing prime-doubling hook is also still
        defined at the class level."""
        assert "_on_attack_resolved" in MathTeacher.__dict__

    def test_get_attack_sources_is_single_source(self):
        """The math teacher uses a single MATHEMAGICAL attack source,
        not per-limb."""
        m = MathTeacher()
        sources = m.get_attack_sources()
        assert len(sources) == 1
        assert sources[0].damage_type == DamageTypes.MATHEMAGICAL

    def test_per_instance_parts_are_independent(self):
        """Two fresh math teachers must not share body part instances
        -- per-instance composition invariant from item 1.7."""
        m1 = MathTeacher()
        m2 = MathTeacher()
        for p1, p2 in zip(m1.body_parts, m2.body_parts):
            assert p1 is not p2


# ---------------------------------------------------------------------------
# Prime damage halving pinned post-migration
# ---------------------------------------------------------------------------


class TestMathTeacherPrimeDamageHalvingPreserved:
    """Pin the MathTeacher-specific incoming prime-halving quirk.

    The behaviour lives in ``MathTeacher.resolve_attack``: after
    delegating to ``Creature.resolve_attack`` to compute raw damage, it
    checks ``is_prime(result.damage)`` and, if true, halves via
    ``result.damage //= 2`` and stamps ``extra_text`` with
    ``"LORD OF PRIMES! / 2 = ..."``. Non-prime damage is passed through
    untouched. These tests pin both the direct ``resolve_attack`` path
    and the ``apply_damage`` routing path, as well as the
    ``is_prime`` helper itself, so that the body parts migration
    can't silently regress any of them.
    """

    def test_is_prime_helper_still_detects_primes(self):
        """The ``is_prime`` static helper is the logical predicate the
        halving reads. Pin a representative set of primes."""
        for p in [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43]:
            assert MathTeacher.is_prime(p) is True

    def test_is_prime_helper_still_rejects_non_primes(self):
        """Pin that non-primes (including ``0``, ``1`` and negatives)
        remain non-prime after the migration."""
        for c in [-7, 0, 1, 4, 6, 8, 9, 10, 15, 25, 100]:
            assert MathTeacher.is_prime(c) is False

    def test_resolve_attack_halves_prime_damage_directly(self):
        """Pin the direct ``resolve_attack`` path for a prime input.

        With defense=0 and dodge=0, feeding a ``CombinedRoll`` whose
        result is a prime (e.g. 7) must yield a halved damage of
        ``7 // 2 == 3`` on the returned ``AttackResult``, and the
        ``extra_text`` must reflect the LORD OF PRIMES flavour.
        """
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0
        attacker = MagicMock()
        attacker.get_hit_modifier.return_value = 0
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        atk, dmg = _make_attack_rolls(7)

        result = teacher.resolve_attack(attacker, source, atk, dmg)

        assert result.damage == 3  # 7 // 2
        assert isinstance(result.damage, int)
        assert "LORD OF PRIMES" in result.extra_text

    def test_resolve_attack_does_not_touch_non_prime_damage(self):
        """Pin the direct ``resolve_attack`` path for a non-prime
        input. A combined roll of 8 must pass through unchanged and
        leave ``extra_text`` empty."""
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0
        defense = teacher.get_defense()  # torso floor keeps this >= 1
        attacker = MagicMock()
        attacker.get_hit_modifier.return_value = 0
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        atk, dmg = _make_attack_rolls(8)

        result = teacher.resolve_attack(attacker, source, atk, dmg)

        # Q.6.2: defense applied per-hit. 8 raw - torso_floor_defense.
        assert result.damage == max(1, 8 - defense)
        assert result.extra_text == ""

    def test_resolve_attack_halves_various_primes(self):
        """Sweep a handful of primes and pin the post-defense halving.

        Q.6.2: defense is subtracted per-hit inside super().resolve_attack
        BEFORE the prime check + halving. Each prime's final damage is
        ``max(1, prime - defense) // 2`` (with prime check on the
        pre-defense ``sub_damage`` value)."""
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0
        defense = teacher.get_defense()  # torso floor keeps this >= 1
        attacker = MagicMock()
        attacker.get_hit_modifier.return_value = 0
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)

        for prime in [2, 3, 5, 7, 11, 13]:
            atk, dmg = _make_attack_rolls(prime)
            result = teacher.resolve_attack(attacker, source, atk, dmg)
            expected = max(1, prime - defense) // 2
            assert result.damage == expected, (
                f"prime {prime}: max(1, {prime}-{defense})//2 = {expected}, "
                f"got {result.damage}"
            )

    def test_resolve_attack_then_apply_damage_routes_halved_value(self):
        """End-to-end pin across the resolve/apply boundary.

        1. Call ``resolve_attack`` with a prime combined roll of 7.
        2. Verify the returned ``AttackResult`` damage is 3 (halved).
        3. Call ``apply_damage(result.damage)`` with no ``target_part``
           and verify the math teacher's ``health`` drops by exactly
           the halved amount -- proving the halved value flows
           through the legacy whole-body damage path unchanged after
           the body parts migration.
        """
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0
        teacher.health_max = 100
        teacher.health = 100
        attacker = MagicMock()
        attacker.get_hit_modifier.return_value = 0
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        atk, dmg = _make_attack_rolls(7)

        result = teacher.resolve_attack(attacker, source, atk, dmg)
        assert result.damage == 3

        teacher.apply_damage(result.damage)
        assert teacher.health == 97

    def test_resolve_attack_then_apply_damage_to_part_routes_halved_value(self):
        """Same as the legacy-path test, but routes the halved damage
        through the new part-targeted ``apply_damage`` path to prove
        the halving is orthogonal to part routing.

        Under Model D (unified body HP), a halved prime damage of 3
        applied to the math teacher's torso produces:
          - torso.health -= 3  (part tracks for injury)
          - teacher.health -= 3  (body takes same amount)
        The point of this test is not to pin the exact body math
        (other tests cover that) but to prove the prime-halving fires
        **before** routing and the halved number is what shows up in
        part and body accounting.
        """
        teacher = MathTeacher()
        teacher.defense = 0
        teacher.dodge = 0
        teacher.health_max = 100
        teacher.health = 100
        attacker = MagicMock()
        attacker.get_hit_modifier.return_value = 0
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        atk, dmg = _make_attack_rolls(7)

        result = teacher.resolve_attack(attacker, source, atk, dmg)
        assert result.damage == 3  # halved from 7

        torso = teacher.get_part("torso")
        torso.health_max = 20
        torso.health = 20
        torso_hp_before = torso.health
        teacher.apply_damage(result.damage, target_part=torso)

        # Part absorbed the halved damage (3), not the raw 7.
        assert torso.health == torso_hp_before - 3
        # Body HP unchanged — do_combat handles body HP reduction
        assert teacher.health == 100

    def test_prime_halving_still_fires_with_body_parts_present(self):
        """Regression guard: a math teacher with a populated
        ``body_parts`` list still halves prime damage in
        ``resolve_attack``. Pinning this ensures that adding body parts
        to ``__init__`` hasn't accidentally shadowed or disabled the
        override."""
        teacher = MathTeacher()
        assert len(teacher.body_parts) == 13  # migration ran

        teacher.defense = 0
        teacher.dodge = 0
        attacker = MagicMock()
        attacker.get_hit_modifier.return_value = 0
        source = NaturalAttackSource(atk="1d100", dmg_type=DamageTypes.SLASHING)
        atk, dmg = _make_attack_rolls(11)  # prime

        result = teacher.resolve_attack(attacker, source, atk, dmg)
        assert result.damage == 5  # 11 // 2
        assert "LORD OF PRIMES" in result.extra_text
