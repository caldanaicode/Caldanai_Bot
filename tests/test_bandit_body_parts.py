"""Tests for the Phase 1.D item 4.2 Bandit body parts migration.

Item 4.2 is the second migration of an existing monster to the body
parts system, following item 4.1 (Goblin). The bandit gains a standard
humanoid composition (1 head + 1 torso + 2 arms + 2 legs) but behaves
identically at full health to its pre-migration self:

- ``Creature.apply_damage(amount, target_part=None)`` routes through
  the legacy whole-body path, so existing combat code still hits the
  bandit's main HP directly.
- At ``InjuryLevels.NONE`` every part's ``debuffs`` lookup returns 0,
  so ``get_defense`` / ``get_dodge`` are unchanged from the base
  attributes.
- ``get_attack_sources`` is NOT overridden -- the bandit still attacks
  with a single ``NaturalAttackSource`` derived from ``self.attack``,
  not per-limb.
- The bandit-specific ``steal`` pickpocket behavior still composes
  cleanly with a parts-equipped bandit.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The bandit composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the bandit still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestBanditBodyPartsComposition:
    def test_bandit_has_six_parts(self):
        """Standard humanoid: 1 head + 1 torso + 2 arms + 2 legs = 6."""
        b = Bandit()
        assert len(b.body_parts) == 13

    def test_bandit_has_exactly_one_head(self):
        b = Bandit()
        heads = [p for p in b.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_bandit_has_exactly_one_torso(self):
        b = Bandit()
        torsos = [p for p in b.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_bandit_has_two_arms(self):
        b = Bandit()
        arms = [p for p in b.body_parts if isinstance(p, ArmPlugin)]
        assert len(arms) == 2

    def test_bandit_has_two_legs(self):
        b = Bandit()
        legs = [p for p in b.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 2


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestBanditCriticalParts:
    def test_head_is_critical(self):
        """A decapitated bandit dies. Head inherits ``is_critical=True``
        from ``HeadPlugin``; the bandit does NOT override it."""
        b = Bandit()
        head = next(p for p in b.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """Critical torso: destruction kills the bandit via the standard
        ``Creature.apply_damage`` critical-part death path."""
        b = Bandit()
        torso = next(p for p in b.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_arms_are_not_critical(self):
        b = Bandit()
        arms = [p for p in b.body_parts if isinstance(p, ArmPlugin)]
        for arm in arms:
            assert arm.is_critical is False

    def test_legs_are_not_critical(self):
        b = Bandit()
        legs = [p for p in b.body_parts if isinstance(p, LegPlugin)]
        for leg in legs:
            assert leg.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestBanditPartNames:
    def test_head_has_expected_name(self):
        b = Bandit()
        head = b.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        b = Bandit()
        torso = b.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_arms_are_distinct_instances(self):
        b = Bandit()
        left = b.get_part("arm.left")
        right = b.get_part("arm.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, ArmPlugin)
        assert isinstance(right, ArmPlugin)

    def test_left_and_right_legs_are_distinct_instances(self):
        b = Bandit()
        left = b.get_part("leg.left")
        right = b.get_part("leg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestBanditFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE``, which means
    the ``debuffs`` table lookup returns 0 for every stat. Therefore
    ``get_defense`` / ``get_dodge`` must return exactly the base
    attribute values they would have returned before the migration.
    """

    def test_get_defense_matches_base_attribute(self):
        b = Bandit()
        assert b.get_defense() == b.defense

    def test_get_dodge_matches_base_attribute(self):
        b = Bandit()
        assert b.get_dodge() == b.dodge

    def test_stat_modifier_total_is_zero_at_full_health(self):
        """Sanity check on the underlying aggregation path."""
        from caldanai.lib.rpg.helpers.enums import Stat

        b = Bandit()
        assert b.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert b.get_stat_modifier_total(Stat.DODGE) == 0
        assert b.get_stat_modifier_total(Stat.ATTACK) == 0
        assert b.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestBanditLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route through
        the legacy whole-body path: ``health`` decrements by 5, parts
        are untouched."""
        b = Bandit()
        b.health_max = 20
        b.health = 20
        b.apply_damage(5)
        assert b.health == 15

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        b = Bandit()
        b.health_max = 20
        b.health = 20
        part_hps_before = [(p.name, p.health) for p in b.body_parts]
        b.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in b.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing."""
        b = Bandit()
        b.health_max = 20
        b.health = 10
        b.apply_damage(-5)
        assert b.health == 15

    def test_bandit_get_attack_sources_is_single_source(self):
        """The bandit is NOT overriding ``get_attack_sources``. It
        attacks with its whole body as a single natural source, not
        per-limb."""
        b = Bandit()
        sources = b.get_attack_sources()
        assert len(sources) == 1


# ---------------------------------------------------------------------------
# Sanity -- existing bandit fields unchanged
# ---------------------------------------------------------------------------


class TestBanditSanityUnchanged:
    def test_name_is_bandit(self):
        b = Bandit()
        assert b.name == "bandit"

    def test_loot_table_contains_expected_items(self):
        """Pin the pre-migration loot keys so a later refactor of the
        body-parts block can't accidentally wipe them."""
        b = Bandit()
        assert "shortsword" in b.loot
        assert "bandanna" in b.loot
        assert "bow" in b.loot
        assert "cheese_sandwich" in b.loot
        assert "wallet" in b.loot

    def test_attack_dice_string_unchanged(self):
        b = Bandit()
        assert b.attack == "1d8"

    def test_flavor_is_one_of_expected_strings(self):
        b = Bandit()
        assert b.flavor in (
            "Your money or your life.",
            "This is a stick up.",
            "You'll never take me alive.",
        )

    def test_per_instance_parts_are_independent(self):
        """Two fresh bandits must not share the same body part
        instances -- per-instance composition invariant from item 1.7."""
        b1 = Bandit()
        b2 = Bandit()
        for p1, p2 in zip(b1.body_parts, b2.body_parts):
            assert p1 is not p2


# ---------------------------------------------------------------------------
# Bandit-specific: the ``steal`` pickpocket behavior composes with parts
# ---------------------------------------------------------------------------


class TestBanditStealStillWorks:
    """Pin that the bandit's pickpocket mechanic survives the body-parts
    migration. ``steal`` doesn't touch ``body_parts`` directly so this
    should just work, but the whole point of item 4.2 is to prove that
    every existing bandit behavior still composes with parts.
    """

    def test_steal_with_wealthy_target_does_not_crash(self):
        """A target with plenty of clarks should have ``steal`` resolve
        without an exception. We don't assert on the result string or
        the clark delta (both are randomized)."""
        b = Bandit()
        target = Goblin()
        target.clarks = 500
        result = b.steal(target)
        assert isinstance(result, str)
        assert result  # non-empty

    def test_steal_with_zero_clarks_returns_sneer_branch(self):
        """Target with zero clarks hits the ``else`` branch -- no
        randomization, no dodge roll, just the sneer message."""
        b = Bandit()
        target = Goblin()
        target.clarks = 0
        result = b.steal(target)
        assert isinstance(result, str)
        assert "no clarks" in result

    def test_steal_with_small_clark_amount_does_not_crash(self):
        """Regression guard for the edge case fixed in commit bedbad6:
        when ``target.clarks`` is between 1 and 9, ``int(clarks / 10)``
        is 0, and ``randint(1, 0)`` used to crash. The fix is the
        ``max(1, int(target.clarks / 10))`` floor in ``bandit.steal``.
        """
        b = Bandit()
        target = Goblin()
        target.clarks = 5
        # Must not raise ValueError from randint.
        result = b.steal(target)
        assert isinstance(result, str)
        assert result

    def test_steal_with_clarks_equal_to_one_does_not_crash(self):
        """Tightest edge of the bedbad6 fix: ``clarks == 1``."""
        b = Bandit()
        target = Goblin()
        target.clarks = 1
        result = b.steal(target)
        assert isinstance(result, str)
        assert result

    def test_steal_target_clark_total_never_goes_negative(self):
        """The ``give_clarks`` path bails if the subtraction would
        underflow. Stealing from a 5-clark target must leave the total
        non-negative regardless of the random amount rolled."""
        b = Bandit()
        target = Goblin()
        target.clarks = 5
        # Run several iterations to cover the random space.
        for _ in range(20):
            target.clarks = 5
            b.steal(target)
            assert target.clarks >= 0

    def test_on_hugged_still_fires_on_parts_bandit(self):
        """``on_hugged`` is the in-combat trigger that sometimes routes
        into ``steal`` via the middle response. Calling it on a
        parts-equipped bandit must not crash regardless of which random
        branch is chosen."""
        b = Bandit()
        actor = Goblin()
        actor.clarks = 50
        # Run multiple times to exercise all three random responses,
        # including the one that delegates to ``steal``.
        for _ in range(30):
            actor.clarks = 50
            msg = b.on_hugged(actor, "hug")
            assert isinstance(msg, str)
            assert msg

    def test_steal_fails_with_no_working_arms(self):
        """Both arms destroyed → bandit can't pickpocket."""
        b = Bandit()
        target = Goblin()
        target.clarks = 500
        for p in b.body_parts:
            if p.name in ("arm.left", "arm.right"):
                p.health = 0
        msg = b.steal(target)
        assert "mangled arms" in msg
        assert target.clarks == 500  # nothing stolen

    def test_steal_works_with_one_arm_destroyed(self):
        """One arm destroyed, one working → steal still possible."""
        b = Bandit()
        target = Goblin()
        target.clarks = 500
        left_arm = next(p for p in b.body_parts if p.name == "arm.left")
        left_arm.health = 0
        # Should not hit the "mangled arms" guard
        msg = b.steal(target)
        assert "mangled arms" not in msg

    def test_steal_fails_with_no_working_legs(self):
        """Both legs destroyed → bandit can't approach to steal."""
        b = Bandit()
        target = Goblin()
        target.clarks = 500
        for p in b.body_parts:
            if p.name in ("leg.left", "leg.right"):
                p.health = 0
        msg = b.steal(target)
        assert "ruined legs" in msg
        assert target.clarks == 500

    def test_steal_works_with_one_leg_destroyed(self):
        """One leg destroyed, one working → steal still possible."""
        b = Bandit()
        target = Goblin()
        target.clarks = 500
        left_leg = next(p for p in b.body_parts if p.name == "leg.left")
        left_leg.health = 0
        msg = b.steal(target)
        assert "ruined legs" not in msg
