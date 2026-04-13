"""Tests for the Phase 1.D item 4.5 Sheep body parts migration.

Item 4.5 is the fifth migration of an existing monster to the body
parts system, and the **second quadruped** (after Bearowl in item
4.4). It reuses the four-legged naming pattern established by the
bearowl: left/right foreleg, left/right hind leg.

Unlike the bearowl, the sheep is a plain quadruped: 1 head + 1 torso
+ 4 legs (2 fore + 2 hind) + 1 tail = 7 parts. No wings, no flying
flag.

At full health the sheep behaves identically to its pre-migration
self:

- ``Creature.apply_damage(amount, target_part=None)`` routes through
  the legacy whole-body path, so existing combat code still hits the
  sheep's main HP directly.
- At ``InjuryLevels.NONE`` every part's ``debuffs`` lookup returns 0,
  so ``get_defense`` / ``get_dodge`` are unchanged from the base
  attributes.
- ``get_attack_sources`` is NOT overridden -- the sheep still attacks
  with a single ``NaturalAttackSource`` derived from ``self.attack``,
  not per-limb.
"""

import pytest

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.sheep import Sheep


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The sheep composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the sheep still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestSheepBodyPartsComposition:
    def test_sheep_has_seven_parts(self):
        """Plain quadruped: 1 head + 1 torso + 4 legs + 1 tail = 7."""
        s = Sheep()
        assert len(s.body_parts) == 7

    def test_sheep_has_exactly_one_head(self):
        s = Sheep()
        heads = [p for p in s.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_sheep_has_exactly_one_torso(self):
        s = Sheep()
        torsos = [p for p in s.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_sheep_has_four_legs(self):
        """Quadruped: 2 forelegs + 2 hind legs."""
        s = Sheep()
        legs = [p for p in s.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 4

    def test_sheep_has_two_forelegs_and_two_hind_legs(self):
        """Pin the fore/hind split by name so later tweaks can't
        accidentally drop to a 3-leg or 2-fore-0-hind shape."""
        s = Sheep()
        leg_names = {
            p.name for p in s.body_parts if isinstance(p, LegPlugin)
        }
        assert "foreleg.left" in leg_names
        assert "foreleg.right" in leg_names
        assert "hindleg.left" in leg_names
        assert "hindleg.right" in leg_names

    def test_sheep_has_exactly_one_tail(self):
        s = Sheep()
        tails = [p for p in s.body_parts if isinstance(p, TailPlugin)]
        assert len(tails) == 1


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestSheepCriticalParts:
    def test_head_is_critical(self):
        """A decapitated sheep dies. Head inherits ``is_critical=True``
        from ``HeadPlugin``; the sheep does NOT override it."""
        s = Sheep()
        head = next(p for p in s.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """Critical torso: destruction kills the sheep via the standard
        ``Creature.apply_damage`` critical-part death path."""
        s = Sheep()
        torso = next(p for p in s.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_legs_are_not_critical(self):
        s = Sheep()
        legs = [p for p in s.body_parts if isinstance(p, LegPlugin)]
        assert legs  # guard against an empty-list vacuous pass
        for leg in legs:
            assert leg.is_critical is False

    def test_tail_is_not_critical(self):
        s = Sheep()
        tail = next(p for p in s.body_parts if isinstance(p, TailPlugin))
        assert tail.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestSheepPartNames:
    def test_head_has_expected_name(self):
        s = Sheep()
        head = s.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        s = Sheep()
        torso = s.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_forelegs_are_distinct_instances(self):
        s = Sheep()
        left = s.get_part("foreleg.left")
        right = s.get_part("foreleg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)

    def test_left_and_right_hind_legs_are_distinct_instances(self):
        s = Sheep()
        left = s.get_part("hindleg.left")
        right = s.get_part("hindleg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)

    def test_forelegs_and_hind_legs_are_distinct_instances(self):
        """Fore and hind on the same side must also be distinct
        instances -- the per-instance composition invariant from item
        1.7 plus the 4-legged naming scheme."""
        s = Sheep()
        left_fore = s.get_part("foreleg.left")
        left_hind = s.get_part("hindleg.left")
        right_fore = s.get_part("foreleg.right")
        right_hind = s.get_part("hindleg.right")
        instances = [left_fore, left_hind, right_fore, right_hind]
        for inst in instances:
            assert inst is not None
        assert len({id(i) for i in instances}) == 4

    def test_tail_has_expected_name(self):
        s = Sheep()
        tail = s.get_part("tail")
        assert tail is not None
        assert isinstance(tail, TailPlugin)


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestSheepFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE`` (ratio 1.0).
    Dodge and defense are scaled by the creature's size modifier.
    Sheep is SMALL: dodge_mod=1.25, defense_mod=0.75.
    """

    def test_get_defense_matches_size_scaled(self):
        s = Sheep()
        expected = int(s.defense * 1.0 * 0.75)
        assert s.get_defense() == expected

    def test_get_dodge_matches_size_scaled(self):
        s = Sheep()
        expected = int(s.dodge * 1.0 * 1.25)
        assert s.get_dodge() == expected

    def test_stat_modifier_total_is_zero_at_full_health(self):
        """Sanity check on the underlying aggregation path."""
        from caldanai.lib.rpg.helpers.enums import Stat

        s = Sheep()
        assert s.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert s.get_stat_modifier_total(Stat.DODGE) == 0
        assert s.get_stat_modifier_total(Stat.ATTACK) == 0
        assert s.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestSheepLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route
        through the legacy whole-body path: ``health`` decrements by
        5, parts are untouched."""
        s = Sheep()
        s.health_max = 50
        s.health = 50
        s.apply_damage(5)
        assert s.health == 45

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        s = Sheep()
        s.health_max = 50
        s.health = 50
        part_hps_before = [(p.name, p.health) for p in s.body_parts]
        s.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in s.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing."""
        s = Sheep()
        s.health_max = 50
        s.health = 20
        s.apply_damage(-5)
        assert s.health == 25

    def test_sheep_get_attack_sources_is_single_source(self):
        """The sheep is NOT overriding ``get_attack_sources``. It
        attacks with its whole body as a single natural source, not
        per-limb."""
        s = Sheep()
        sources = s.get_attack_sources()
        assert len(sources) == 1


# ---------------------------------------------------------------------------
# Sanity -- existing sheep fields unchanged
# ---------------------------------------------------------------------------


class TestSheepSanityUnchanged:
    def test_name_is_sheep(self):
        s = Sheep()
        assert s.name == "sheep"

    def test_attack_dice_string_unchanged(self):
        s = Sheep()
        assert s.attack == "1d4"

    def test_flavor_is_one_of_the_known_strings(self):
        """The sheep picks its flavor randomly from a fixed list.
        Pin the full set so the migration hasn't accidentally touched
        the flavor pool."""
        expected = {
            "Just a cuddly @1, searching the lonely fields for hugs.",
            '"Ple-e-e-e-ease don\'t kill me-e-e-e-e."',
            "A sleepy looking @1, seeking naught but the warmth of @1a barn.",
        }
        for _ in range(50):
            s = Sheep()
            assert s.flavor in expected

    def test_loot_table_unchanged(self):
        """Pin the sheep's explicit loot keys from ``__init__`` so the
        migration hasn't dropped or added any."""
        s = Sheep()
        assert s.loot["stick"] == 0.5
        assert s.loot["wool"] == 0.5
        assert s.loot["leather"] == 0.25

    def test_per_instance_parts_are_independent(self):
        """Two fresh sheep must not share the same body part
        instances -- per-instance composition invariant from item
        1.7."""
        s1 = Sheep()
        s2 = Sheep()
        for p1, p2 in zip(s1.body_parts, s2.body_parts):
            assert p1 is not p2

    def test_on_hugged_still_returns_string(self):
        """The sheep's ``on_hugged`` trigger must keep returning a
        string on a parts-equipped sheep, regardless of the random
        flavor pick."""
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin

        s = Sheep()
        actor = Goblin()
        for _ in range(30):
            msg = s.on_hugged(actor, "hug")
            assert isinstance(msg, str)
            assert msg
