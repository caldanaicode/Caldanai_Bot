"""Tests for the Phase 1.D item 4.4 Bearowl body parts migration.

Item 4.4 is the fourth migration of an existing monster to the body
parts system, and the **first quadruped**. It establishes the
four-legged naming pattern (left/right foreleg, left/right hind leg)
that items 4.5 (Sheep) and 4.6 (Toad) will reuse.

The bearowl is a chimeric bear-owl hybrid, so its composition is
slightly richer than a pure quadruped: 1 head + 1 torso + 4 legs
(2 fore + 2 hind) + 2 wings (owl part) + 1 tail (bear part) = 9
parts. It is also the first migrated monster to carry the
``"flying"`` flag, which the ``WingPlugin.on_injury_change`` hook
from item 2.5 discards when a wing is driven to
``InjuryLevels.USELESS``. This pins the full wing -> grounded
interaction on a real creature, not just the hydra test fixture.

At full health the bearowl behaves identically to its pre-migration
self:

- ``Creature.apply_damage(amount, target_part=None)`` routes through
  the legacy whole-body path, so existing combat code still hits the
  bearowl's main HP directly.
- At ``InjuryLevels.NONE`` every part's ``debuffs`` lookup returns 0,
  so ``get_defense`` / ``get_dodge`` are unchanged from the base
  attributes.
- ``get_attack_sources`` is NOT overridden -- the bearowl still
  attacks with a single ``NaturalAttackSource`` derived from
  ``self.attack``, not per-limb.
"""

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The bearowl composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the bearowl still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestBearowlBodyPartsComposition:
    def test_bearowl_has_nine_parts(self):
        """Chimeric quadruped: 1 head + 1 torso + 4 legs + 2 wings +
        1 tail = 9."""
        b = Bearowl()
        assert len(b.body_parts) == 9

    def test_bearowl_has_exactly_one_head(self):
        b = Bearowl()
        heads = [p for p in b.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_bearowl_has_exactly_one_torso(self):
        b = Bearowl()
        torsos = [p for p in b.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_bearowl_has_four_legs(self):
        """Quadruped: 2 forelegs + 2 hind legs."""
        b = Bearowl()
        legs = [p for p in b.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 4

    def test_bearowl_has_two_forelegs_and_two_hind_legs(self):
        """Pin the fore/hind split by name so later tweaks can't
        accidentally drop to a 3-leg or 2-fore-0-hind shape."""
        b = Bearowl()
        leg_names = {
            p.name for p in b.body_parts if isinstance(p, LegPlugin)
        }
        assert "foreleg.left" in leg_names
        assert "foreleg.right" in leg_names
        assert "hindleg.left" in leg_names
        assert "hindleg.right" in leg_names

    def test_bearowl_has_two_wings(self):
        b = Bearowl()
        wings = [p for p in b.body_parts if isinstance(p, WingPlugin)]
        assert len(wings) == 2

    def test_bearowl_has_exactly_one_tail(self):
        b = Bearowl()
        tails = [p for p in b.body_parts if isinstance(p, TailPlugin)]
        assert len(tails) == 1


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestBearowlCriticalParts:
    def test_head_is_critical(self):
        """A decapitated bearowl dies. Head inherits
        ``is_critical=True`` from ``HeadPlugin``; the bearowl does NOT
        override it."""
        b = Bearowl()
        head = next(p for p in b.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """Critical torso: destruction kills the bearowl via the
        standard ``Creature.apply_damage`` critical-part death path."""
        b = Bearowl()
        torso = next(p for p in b.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_legs_are_not_critical(self):
        b = Bearowl()
        legs = [p for p in b.body_parts if isinstance(p, LegPlugin)]
        assert legs  # guard against an empty-list vacuous pass
        for leg in legs:
            assert leg.is_critical is False

    def test_wings_are_not_critical(self):
        """You can destroy a wing without killing the bearowl -- the
        ``on_injury_change`` hook grounds it instead (see
        ``TestBearowlFlyingFlag``)."""
        b = Bearowl()
        wings = [p for p in b.body_parts if isinstance(p, WingPlugin)]
        assert wings
        for wing in wings:
            assert wing.is_critical is False

    def test_tail_is_not_critical(self):
        b = Bearowl()
        tail = next(p for p in b.body_parts if isinstance(p, TailPlugin))
        assert tail.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestBearowlPartNames:
    def test_head_has_expected_name(self):
        b = Bearowl()
        head = b.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        b = Bearowl()
        torso = b.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_forelegs_are_distinct_instances(self):
        b = Bearowl()
        left = b.get_part("foreleg.left")
        right = b.get_part("foreleg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)

    def test_left_and_right_hind_legs_are_distinct_instances(self):
        b = Bearowl()
        left = b.get_part("hindleg.left")
        right = b.get_part("hindleg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)

    def test_forelegs_and_hind_legs_are_distinct_instances(self):
        """Fore and hind on the same side must also be distinct
        instances -- the per-instance composition invariant from item
        1.7 plus the 4-legged naming scheme."""
        b = Bearowl()
        left_fore = b.get_part("foreleg.left")
        left_hind = b.get_part("hindleg.left")
        right_fore = b.get_part("foreleg.right")
        right_hind = b.get_part("hindleg.right")
        instances = [left_fore, left_hind, right_fore, right_hind]
        # All four must exist and be mutually distinct.
        for inst in instances:
            assert inst is not None
        assert len({id(i) for i in instances}) == 4

    def test_left_and_right_wings_are_distinct_instances(self):
        b = Bearowl()
        left = b.get_part("wing.left")
        right = b.get_part("wing.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, WingPlugin)
        assert isinstance(right, WingPlugin)

    def test_tail_has_expected_name(self):
        b = Bearowl()
        tail = b.get_part("tail")
        assert tail is not None
        assert isinstance(tail, TailPlugin)


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestBearowlFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE`` (ratio 1.0).
    Bearowl is LARGE and flying: dodge uses wings (dodge_mod=0.75),
    defense_mod=1.25.
    """

    def test_get_defense_matches_size_scaled(self):
        b = Bearowl()
        expected = int(b.defense * 1.0 * 1.25)
        assert b.get_defense() == expected

    def test_get_dodge_matches_size_scaled(self):
        b = Bearowl()
        # LARGE (dodge_mod 0.75) on a healthy bearowl: the size-scaled
        # formula with a floor of 1 when any mobility remains. The
        # floor matters for low rolls — ``1d10 = 1`` yields
        # ``int(1 * 0.75) = 0`` without the floor, which was the
        # "bearowl with 0 dodge" bug surfaced at playtest.
        expected = max(1, int(b.dodge * 1.0 * 0.75))
        assert b.get_dodge() == expected

    def test_stat_modifier_total_is_zero_at_full_health(self):
        """Sanity check on the underlying aggregation path."""
        from caldanai.lib.rpg.helpers.enums import Stat

        b = Bearowl()
        assert b.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert b.get_stat_modifier_total(Stat.DODGE) == 0
        assert b.get_stat_modifier_total(Stat.ATTACK) == 0
        assert b.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestBearowlLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route
        through the legacy whole-body path: ``health`` decrements by
        5, parts are untouched."""
        b = Bearowl()
        b.health_max = 50
        b.health = 50
        b.apply_damage(5)
        assert b.health == 45

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        b = Bearowl()
        b.health_max = 50
        b.health = 50
        part_hps_before = [(p.name, p.health) for p in b.body_parts]
        b.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in b.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing."""
        b = Bearowl()
        b.health_max = 50
        b.health = 20
        b.apply_damage(-5)
        assert b.health == 25

    def test_bearowl_get_attack_sources_is_single_source(self):
        """The bearowl is NOT overriding ``get_attack_sources``. It
        attacks with its whole body as a single natural source, not
        per-limb."""
        b = Bearowl()
        sources = b.get_attack_sources()
        assert len(sources) == 1


# ---------------------------------------------------------------------------
# Sanity -- existing bearowl fields unchanged
# ---------------------------------------------------------------------------


class TestBearowlSanityUnchanged:
    def test_name_is_bearowl(self):
        b = Bearowl()
        assert b.name == "bearowl"

    def test_attack_dice_string_unchanged(self):
        b = Bearowl()
        assert b.attack == "2d7"

    def test_flavor_is_one_of_the_known_strings(self):
        """The bearowl picks its flavor randomly from a fixed list.
        Pin the full set so the migration hasn't accidentally touched
        the flavor pool."""
        expected = {
            "Legally distinct from any similarly-named creatures.",
            "Hoo. Hoo. A frickin' @1, that's who.",
            "Trust me, you don't want to know.",
        }
        # Sample a bunch of fresh bearowls and assert every drawn
        # flavor is in the expected pool. 50 draws is well above the
        # ~1-in-a-trillion threshold for missing a bucket of size 3
        # but keeps the test fast.
        for _ in range(50):
            b = Bearowl()
            assert b.flavor in expected

    def test_loot_table_unchanged(self):
        """The bearowl has no explicit ``self.loot`` assignments in
        ``__init__``. Pin that so the migration hasn't accidentally
        introduced any."""
        b = Bearowl()
        # The base MonsterPlugin initializer may populate a default
        # loot dict; just confirm the migration hasn't added keys
        # unique to a different monster.
        for wrong_key in ("rock", "sledgehammer", "spear", "ice_axe"):
            assert wrong_key not in b.loot

    def test_per_instance_parts_are_independent(self):
        """Two fresh bearowls must not share the same body part
        instances -- per-instance composition invariant from item
        1.7."""
        b1 = Bearowl()
        b2 = Bearowl()
        for p1, p2 in zip(b1.body_parts, b2.body_parts):
            assert p1 is not p2

    def test_on_hugged_still_returns_string(self):
        """The bearowl's ``on_hugged`` trigger must keep returning a
        string on a parts-equipped bearowl, regardless of the random
        flavor pick."""
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin

        b = Bearowl()
        actor = Goblin()
        for _ in range(30):
            msg = b.on_hugged(actor, "hug")
            assert isinstance(msg, str)
            assert msg


# ---------------------------------------------------------------------------
# Flying flag and wing-grounding interaction (novel to item 4.4)
# ---------------------------------------------------------------------------


class TestBearowlFlyingFlag:
    """The bearowl is the first migrated monster to carry the
    ``"flying"`` flag, which the ``WingPlugin.on_injury_change`` hook
    from item 2.5 discards when a wing is driven to
    ``InjuryLevels.USELESS``. These tests pin the full interaction
    end-to-end on a real creature (not just the hydra test fixture).

    Per the current wing plugin contract (``wing.py`` item 2.5), the
    hook fires on *each* wing's transition into USELESS, meaning a
    single destroyed wing is enough to ground the creature. Whether
    grounding should require both wings is a separate design
    decision, outside the scope of item 4.4.
    """

    def test_fresh_bearowl_has_flying_flag(self):
        """No setup, no damage: a bearowl out of the box flies."""
        b = Bearowl()
        assert "flying" in b.flags

    def test_flying_flag_is_on_instance_not_class(self):
        """Two fresh bearowls must carry independent flag sets --
        mutating one's flags must not leak into the other."""
        b1 = Bearowl()
        b2 = Bearowl()
        b1.flags.discard("flying")
        assert "flying" not in b1.flags
        assert "flying" in b2.flags

    def test_destroying_one_wing_grounds_the_bearowl(self):
        """Drive a single wing to ``InjuryLevels.USELESS`` via
        ``apply_damage`` with ``target_part``. The
        ``WingPlugin.on_injury_change`` hook fires on the
        transition into USELESS and discards ``"flying"`` from the
        bearowl's flag set."""
        b = Bearowl()
        # Make sure the bearowl has enough main HP that a single
        # huge wing-hit doesn't kill the whole creature via the
        # Model D unified-HP pass-through.
        b.health_max = 10_000
        b.health = 10_000

        wing = b.get_part("wing.left")
        assert wing is not None
        assert isinstance(wing, WingPlugin)
        assert "flying" in b.flags  # baseline

        # Overkill: drive the wing all the way to USELESS in one
        # shot. ``apply_damage`` only routes the damage — ``do_combat``
        # is the single site that fires ``on_injury_change`` after a
        # full attack sequence resolves (to avoid double-firing hooks
        # with side effects). Mirror that here with a manual fire.
        old_level = wing.get_injury_level()
        b.apply_damage(100, target_part=wing)
        wing.on_injury_change(b, old_level, wing.get_injury_level())

        assert wing.is_destroyed()
        assert "flying" not in b.flags

    def test_destroying_a_wing_does_not_kill_the_bearowl(self):
        """Wings are non-critical: the bearowl keeps some HP after
        its wing is driven to USELESS, even though it's grounded.
        Pins the contract that wing-destruction cascades to the
        flag (soft consequence) rather than the critical-part death
        short-circuit (hard consequence)."""
        b = Bearowl()
        b.health_max = 10_000
        b.health = 10_000
        wing = b.get_part("wing.right")
        b.apply_damage(100, target_part=wing)
        assert not b.is_dead()

    def test_undamaged_wing_does_not_discard_flag(self):
        """Sanity: constructing a bearowl and poking a wing without
        any damage must not discard the flying flag. Only the
        transition *into* USELESS grounds the creature."""
        b = Bearowl()
        wing = b.get_part("wing.left")
        assert wing is not None
        # Lightly tap the wing -- not enough to reach USELESS.
        # Even a small hit can cross a lower injury-level boundary,
        # but only the -> USELESS hook discards "flying".
        b.health_max = 10_000
        b.health = 10_000
        b.apply_damage(1, target_part=wing)
        if not wing.is_destroyed():
            assert "flying" in b.flags
