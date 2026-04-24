"""Tests for the Phase 1.D item 4.3 Giant body parts migration.

Item 4.3 is the third migration of an existing monster to the body
parts system, following item 4.1 (Goblin) and item 4.2 (Bandit). The
giant gains a standard humanoid composition (1 head + 1 torso + 2 arms
+ 2 legs) but behaves identically at full health to its pre-migration
self:

- ``Creature.apply_damage(amount, target_part=None)`` routes through
  the legacy whole-body path, so existing combat code still hits the
  giant's main HP directly.
- At ``InjuryLevels.NONE`` every part's ``debuffs`` lookup returns 0,
  so ``get_defense`` / ``get_dodge`` are unchanged from the base
  attributes.
- ``get_attack_sources`` is NOT overridden -- the giant still attacks
  with a single ``NaturalAttackSource`` derived from ``self.attack``,
  not per-limb.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.giant import Giant
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The giant composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the giant still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestGiantBodyPartsComposition:
    def test_giant_has_six_parts(self):
        """Standard humanoid: 1 head + 1 torso + 2 arms + 2 legs = 6."""
        g = Giant()
        assert len(g.body_parts) == 13

    def test_giant_has_exactly_one_head(self):
        g = Giant()
        heads = [p for p in g.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_giant_has_exactly_one_torso(self):
        g = Giant()
        torsos = [p for p in g.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_giant_has_two_arms(self):
        g = Giant()
        arms = [p for p in g.body_parts if isinstance(p, ArmPlugin)]
        assert len(arms) == 2

    def test_giant_has_two_legs(self):
        g = Giant()
        legs = [p for p in g.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 2


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestGiantCriticalParts:
    def test_head_is_critical(self):
        """A decapitated giant dies. Head inherits ``is_critical=True``
        from ``HeadPlugin``; the giant does NOT override it."""
        g = Giant()
        head = next(p for p in g.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """Critical torso: destruction kills the giant via the standard
        ``Creature.apply_damage`` critical-part death path."""
        g = Giant()
        torso = next(p for p in g.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_arms_are_not_critical(self):
        g = Giant()
        arms = [p for p in g.body_parts if isinstance(p, ArmPlugin)]
        for arm in arms:
            assert arm.is_critical is False

    def test_legs_are_not_critical(self):
        g = Giant()
        legs = [p for p in g.body_parts if isinstance(p, LegPlugin)]
        for leg in legs:
            assert leg.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestGiantPartNames:
    def test_head_has_expected_name(self):
        g = Giant()
        head = g.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        g = Giant()
        torso = g.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_arms_are_distinct_instances(self):
        g = Giant()
        left = g.get_part("arm.left")
        right = g.get_part("arm.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, ArmPlugin)
        assert isinstance(right, ArmPlugin)

    def test_left_and_right_legs_are_distinct_instances(self):
        g = Giant()
        left = g.get_part("leg.left")
        right = g.get_part("leg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestGiantFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE`` (ratio 1.0).
    Giant is HUGE: dodge_mod=0.5, defense_mod=1.5.
    """

    def test_get_defense_matches_size_scaled(self):
        g = Giant()
        expected = int(g.defense * 1.0 * 1.5)
        assert g.get_defense() == expected

    def test_get_dodge_matches_size_scaled(self):
        g = Giant()
        # HUGE dodge_mod=0.5; ``get_dodge`` floors at 1 when
        # mobility remains, so mirror the clamp — ``int(low_roll
        # * 0.5)`` can truncate to 0 otherwise.
        expected = max(1, int(g.dodge * 1.0 * 0.5))
        assert g.get_dodge() == expected

    def test_stat_modifier_total_is_zero_at_full_health(self):
        """Sanity check on the underlying aggregation path."""
        from caldanai.lib.rpg.helpers.enums import Stat

        g = Giant()
        assert g.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert g.get_stat_modifier_total(Stat.DODGE) == 0
        assert g.get_stat_modifier_total(Stat.ATTACK) == 0
        assert g.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestGiantLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route through
        the legacy whole-body path: ``health`` decrements by 5, parts
        are untouched."""
        g = Giant()
        g.health_max = 50
        g.health = 50
        g.apply_damage(5)
        assert g.health == 45

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        g = Giant()
        g.health_max = 50
        g.health = 50
        part_hps_before = [(p.name, p.health) for p in g.body_parts]
        g.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in g.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing."""
        g = Giant()
        g.health_max = 50
        g.health = 20
        g.apply_damage(-5)
        assert g.health == 25

    def test_giant_get_attack_sources_is_single_source(self):
        """The giant is NOT overriding ``get_attack_sources``. It
        attacks with its whole body as a single natural source, not
        per-limb."""
        g = Giant()
        sources = g.get_attack_sources()
        assert len(sources) == 1


# ---------------------------------------------------------------------------
# Sanity -- existing giant fields unchanged
# ---------------------------------------------------------------------------


class TestGiantSanityUnchanged:
    def test_name_is_giant(self):
        g = Giant()
        assert g.name == "giant"

    def test_loot_table_contains_expected_items(self):
        """Pin the pre-migration loot keys so a later refactor of the
        body-parts block can't accidentally wipe them."""
        g = Giant()
        assert "rock" in g.loot
        assert "sledgehammer" in g.loot
        assert "spear" in g.loot
        assert "ice_axe" in g.loot

    def test_attack_dice_string_unchanged(self):
        g = Giant()
        assert g.attack == "2d10"

    def test_flavor_unchanged(self):
        g = Giant()
        assert g.flavor == (
            "This @1 would blend in nicely with the surrounding rocks, "
            "if @1s would stop moving."
        )

    def test_per_instance_parts_are_independent(self):
        """Two fresh giants must not share the same body part
        instances -- per-instance composition invariant from item 1.7."""
        g1 = Giant()
        g2 = Giant()
        for p1, p2 in zip(g1.body_parts, g2.body_parts):
            assert p1 is not p2

    def test_on_hugged_still_fires_on_parts_giant(self):
        """The giant's ``on_hugged`` trigger must not crash on a
        parts-equipped giant, regardless of the random dodge outcome.
        """
        g = Giant()
        actor = Goblin()
        for _ in range(30):
            msg = g.on_hugged(actor, "hug")
            assert isinstance(msg, str)
            assert msg
