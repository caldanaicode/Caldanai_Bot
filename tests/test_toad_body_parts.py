"""Tests for the Phase 1.D item 4.6 Toad body parts migration.

Item 4.6 is the sixth migration of an existing monster to the body
parts system, and the **last quadruped** in Phase 1.D. It reuses the
four-legged naming pattern established by bearowl (4.4) and sheep
(4.5): left/right foreleg, left/right hind leg.

Unlike the sheep, the toad has **no tail**. Adult toads (unlike
tadpoles) are tailless, so the composition is 1 head + 1 torso + 4
legs = 6 parts total. This "no tail" anatomy decision is pinned
explicitly in the composition test below.

At full health the toad behaves identically to its pre-migration
self:

- ``Creature.apply_damage(amount, target_part=None)`` routes through
  the legacy whole-body path.
- At ``InjuryLevels.NONE`` every part's ``debuffs`` lookup returns 0,
  so ``get_defense`` / ``get_dodge`` are unchanged from the base
  attributes.
- ``get_attack_sources`` is NOT overridden -- the toad still attacks
  with a single ``NaturalAttackSource`` derived from ``self.attack``.
"""

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.toad import Toad


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The toad composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the toad still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestToadBodyPartsComposition:
    def test_toad_has_six_parts(self):
        """Tailless quadruped: 1 head + 1 torso + 4 legs = 6."""
        t = Toad()
        assert len(t.body_parts) == 6

    def test_toad_has_exactly_one_head(self):
        t = Toad()
        heads = [p for p in t.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_toad_has_exactly_one_torso(self):
        t = Toad()
        torsos = [p for p in t.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_toad_has_four_legs(self):
        """Quadruped: 2 forelegs + 2 hind legs."""
        t = Toad()
        legs = [p for p in t.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 4

    def test_toad_has_two_forelegs_and_two_hind_legs(self):
        """Pin the fore/hind split by name so later tweaks can't
        accidentally drop to a 3-leg or 2-fore-0-hind shape."""
        t = Toad()
        leg_names = {
            p.name for p in t.body_parts if isinstance(p, LegPlugin)
        }
        assert "foreleg.left" in leg_names
        assert "foreleg.right" in leg_names
        assert "hindleg.left" in leg_names
        assert "hindleg.right" in leg_names

    def test_toad_has_no_tail(self):
        """Adult toads are tailless -- pin this anatomy decision
        explicitly so a future 'all quadrupeds get tails' refactor
        can't silently grow one back."""
        t = Toad()
        tails = [p for p in t.body_parts if isinstance(p, TailPlugin)]
        assert tails == []


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestToadCriticalParts:
    def test_head_is_critical(self):
        """A decapitated toad dies. Head inherits ``is_critical=True``
        from ``HeadPlugin``; the toad does NOT override it."""
        t = Toad()
        head = next(p for p in t.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """Critical torso: destruction kills the toad via the standard
        ``Creature.apply_damage`` critical-part death path."""
        t = Toad()
        torso = next(p for p in t.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_legs_are_not_critical(self):
        t = Toad()
        legs = [p for p in t.body_parts if isinstance(p, LegPlugin)]
        assert legs  # guard against an empty-list vacuous pass
        for leg in legs:
            assert leg.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestToadPartNames:
    def test_head_has_expected_name(self):
        t = Toad()
        head = t.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        t = Toad()
        torso = t.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_forelegs_are_distinct_instances(self):
        t = Toad()
        left = t.get_part("foreleg.left")
        right = t.get_part("foreleg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)

    def test_left_and_right_hind_legs_are_distinct_instances(self):
        t = Toad()
        left = t.get_part("hindleg.left")
        right = t.get_part("hindleg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)

    def test_forelegs_and_hind_legs_are_distinct_instances(self):
        """Fore and hind on the same side must also be distinct
        instances -- the per-instance composition invariant from item
        1.7 plus the 4-legged naming scheme."""
        t = Toad()
        left_fore = t.get_part("foreleg.left")
        left_hind = t.get_part("hindleg.left")
        right_fore = t.get_part("foreleg.right")
        right_hind = t.get_part("hindleg.right")
        instances = [left_fore, left_hind, right_fore, right_hind]
        for inst in instances:
            assert inst is not None
        assert len({id(i) for i in instances}) == 4


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestToadFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE`` (ratio 1.0).
    Toad is SMALL or MEDIUM depending on variant.
    """

    def test_get_defense_matches_size_scaled(self):
        t = Toad()
        defense_mod = t.size.value["defense_mod"]
        expected = int(t.defense * 1.0 * defense_mod)
        assert t.get_defense() == expected

    def test_get_dodge_matches_size_scaled(self):
        t = Toad()
        dodge_mod = t.size.value["dodge_mod"]
        expected = int(t.dodge * 1.0 * dodge_mod)
        assert t.get_dodge() == expected

    def test_stat_modifier_total_is_zero_at_full_health(self):
        """Sanity check on the underlying aggregation path."""
        from caldanai.lib.rpg.helpers.enums import Stat

        t = Toad()
        assert t.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert t.get_stat_modifier_total(Stat.DODGE) == 0
        assert t.get_stat_modifier_total(Stat.ATTACK) == 0
        assert t.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestToadLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route
        through the legacy whole-body path: ``health`` decrements by
        5, parts are untouched."""
        t = Toad()
        t.health_max = 50
        t.health = 50
        t.apply_damage(5)
        assert t.health == 45

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        t = Toad()
        t.health_max = 50
        t.health = 50
        part_hps_before = [(p.name, p.health) for p in t.body_parts]
        t.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in t.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing."""
        t = Toad()
        t.health_max = 50
        t.health = 20
        t.apply_damage(-5)
        assert t.health == 25

    def test_toad_get_attack_sources_is_single_source(self):
        """The toad is NOT overriding ``get_attack_sources``. It
        attacks with its whole body as a single natural source, not
        per-limb."""
        t = Toad()
        sources = t.get_attack_sources()
        assert len(sources) == 1


# ---------------------------------------------------------------------------
# Sanity -- existing toad fields unchanged
# ---------------------------------------------------------------------------


class TestToadSanityUnchanged:
    def test_name_is_toad(self):
        t = Toad()
        assert t.name == "toad"

    def test_attack_dice_string_unchanged(self):
        t = Toad()
        assert t.attack == "1d8"

    def test_flavor_is_one_of_the_known_strings(self):
        """The toad picks its flavor randomly from a fixed pair.
        Pin the full set so the migration hasn't accidentally touched
        the flavor pool."""
        expected = {
            "It remains unclear whether this _toadstool_ is just a remnant of a bad trip.",
            "This @1 is abnormally large, its diet primarily consisting of cute, small animals.",
        }
        for _ in range(50):
            t = Toad()
            assert t.flavor in expected

    def test_loot_table_unchanged(self):
        """Pin the toad's explicit loot keys from ``__init__`` so the
        migration hasn't dropped or added any."""
        t = Toad()
        assert t.loot["toad_slime"] == 0.9
        assert t.loot["mushroom_hat"] == 0.3

    def test_per_instance_parts_are_independent(self):
        """Two fresh toads must not share the same body part
        instances -- per-instance composition invariant from item
        1.7."""
        t1 = Toad()
        t2 = Toad()
        for p1, p2 in zip(t1.body_parts, t2.body_parts):
            assert p1 is not p2
