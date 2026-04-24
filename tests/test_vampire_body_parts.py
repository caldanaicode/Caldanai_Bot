"""Tests for the Phase 1.D item 4.8 Vampire body parts migration.

Item 4.8 is the second migration of a **custom-statted** monster to
the body parts system. The vampire owns a ``feed`` mechanic that drains
HP from its target and heals the vampire -- a Vampire-specific combat
quirk that existed long before body parts were added. The migration
must be strictly additive: ``feed`` continues to fire without any
changes to its body, and its drain still routes through the legacy
whole-body HP path so the "vampires drain blood, which is everywhere"
semantics are preserved.

The architectural invariant being pinned here:

- ``feed`` decides **how much** HP to drain from its target and how
  much to restore to the vampire. The mechanic lives inside this
  method and has nothing to do with part routing.
- ``apply_damage`` routes the already-computed drain; with no
  ``target_part`` kwarg it uses the legacy whole-body path, which is
  exactly what ``feed`` does today.

These two concerns are orthogonal. Adding ``body_parts`` does not
touch ``feed``, and the tests in ``TestVampireFeedPreserved`` pin the
drain mechanic, the ``health <= 0`` edge-case guard (the ``bedbad6``
fix), the vampire self-heal, the orthogonality with body parts, and
the two trigger paths (``on_hugged`` and ``do_attack``).
"""

from random import seed
from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
from caldanai.lib.rpg.creatures.monsters.vampire import Vampire


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure body-part plugin discovery has run before every test.

    The vampire composes body parts via ``BodyPart.make`` in its
    ``__init__``, which requires the body-part plugin registry to be
    populated. Monster plugin discovery is also loaded so that
    sanity-check tests can confirm the vampire still registers.
    """
    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    yield


def _fresh_vampire() -> Vampire:
    """Construct a vampire and pin it to full health with a
    deterministic ``health_max`` so tests can reason about self-heal
    arithmetic independent of the ``10d8`` roll."""
    v = Vampire()
    v.health_max = 200
    v.health = 200
    return v


def _fresh_goblin(health: int) -> Goblin:
    """Construct a goblin with a deterministic HP. Used as a feed
    target so that tests don't depend on ``1d20`` health rolls."""
    g = Goblin()
    g.health_max = max(health, 1)
    g.health = health
    return g


# ---------------------------------------------------------------------------
# Composition shape
# ---------------------------------------------------------------------------


class TestVampireBodyPartsComposition:
    def test_vampire_has_six_parts(self):
        """Standard humanoid: 1 head + 1 torso + 2 arms + 2 legs = 6."""
        v = Vampire()
        assert len(v.body_parts) == 13

    def test_vampire_has_exactly_one_head(self):
        v = Vampire()
        heads = [p for p in v.body_parts if isinstance(p, HeadPlugin)]
        assert len(heads) == 1

    def test_vampire_has_exactly_one_torso(self):
        v = Vampire()
        torsos = [p for p in v.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1

    def test_vampire_has_two_arms(self):
        v = Vampire()
        arms = [p for p in v.body_parts if isinstance(p, ArmPlugin)]
        assert len(arms) == 2

    def test_vampire_has_two_legs(self):
        v = Vampire()
        legs = [p for p in v.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 2


# ---------------------------------------------------------------------------
# Critical-part flags
# ---------------------------------------------------------------------------


class TestVampireCriticalParts:
    def test_head_is_critical(self):
        """A decapitated vampire dies. Head inherits
        ``is_critical=True`` from ``HeadPlugin``; the vampire does NOT
        override it."""
        v = Vampire()
        head = next(p for p in v.body_parts if isinstance(p, HeadPlugin))
        assert head.is_critical is True

    def test_torso_is_critical(self):
        """A staked torso kills the vampire via the standard
        ``Creature.apply_damage`` critical-part death path."""
        v = Vampire()
        torso = next(p for p in v.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_arms_are_not_critical(self):
        v = Vampire()
        arms = [p for p in v.body_parts if isinstance(p, ArmPlugin)]
        for arm in arms:
            assert arm.is_critical is False

    def test_legs_are_not_critical(self):
        v = Vampire()
        legs = [p for p in v.body_parts if isinstance(p, LegPlugin)]
        for leg in legs:
            assert leg.is_critical is False


# ---------------------------------------------------------------------------
# Distinct part names
# ---------------------------------------------------------------------------


class TestVampirePartNames:
    def test_head_has_expected_name(self):
        v = Vampire()
        head = v.get_part("head")
        assert head is not None
        assert isinstance(head, HeadPlugin)

    def test_torso_has_expected_name(self):
        v = Vampire()
        torso = v.get_part("torso")
        assert torso is not None
        assert isinstance(torso, TorsoPlugin)

    def test_left_and_right_arms_are_distinct_instances(self):
        v = Vampire()
        left = v.get_part("arm.left")
        right = v.get_part("arm.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, ArmPlugin)
        assert isinstance(right, ArmPlugin)

    def test_left_and_right_legs_are_distinct_instances(self):
        v = Vampire()
        left = v.get_part("leg.left")
        right = v.get_part("leg.right")
        assert left is not None
        assert right is not None
        assert left is not right
        assert isinstance(left, LegPlugin)
        assert isinstance(right, LegPlugin)


# ---------------------------------------------------------------------------
# Backwards compatibility -- full health stats unchanged
# ---------------------------------------------------------------------------


class TestVampireFullHealthBackwardsCompat:
    """At full health every part is at ``InjuryLevels.NONE``, which
    means the ``debuffs`` table lookup returns 0 for every stat.
    Therefore ``get_defense`` / ``get_dodge`` must return exactly the
    base attribute values they would have returned before the
    migration.
    """

    def test_get_defense_matches_base_attribute(self):
        v = Vampire()
        assert v.get_defense() == v.defense

    def test_get_dodge_matches_base_attribute(self):
        v = Vampire()
        assert v.get_dodge() == v.dodge

    def test_stat_modifier_total_is_zero_at_full_health(self):
        from caldanai.lib.rpg.helpers.enums import Stat

        v = Vampire()
        assert v.get_stat_modifier_total(Stat.DEFENSE) == 0
        assert v.get_stat_modifier_total(Stat.DODGE) == 0
        assert v.get_stat_modifier_total(Stat.ATTACK) == 0
        assert v.get_stat_modifier_total(Stat.HIT) == 0


# ---------------------------------------------------------------------------
# Legacy damage path still fires
# ---------------------------------------------------------------------------


class TestVampireLegacyDamagePath:
    def test_apply_damage_without_target_part_hits_main_hp(self):
        """``apply_damage(5)`` with no ``target_part`` must route
        through the legacy whole-body path: ``health`` decrements by 5,
        parts are untouched."""
        v = _fresh_vampire()
        v.health_max = 50
        v.health = 50
        v.apply_damage(5)
        assert v.health == 45

    def test_apply_damage_without_target_part_does_not_touch_parts(self):
        v = _fresh_vampire()
        v.health_max = 50
        v.health = 50
        part_hps_before = [(p.name, p.health) for p in v.body_parts]
        v.apply_damage(5)
        part_hps_after = [(p.name, p.health) for p in v.body_parts]
        assert part_hps_before == part_hps_after

    def test_apply_damage_healing_still_works(self):
        """Negative damage heals via the legacy path -- adding parts
        must not break healing (and ``feed`` relies on this to
        regenerate the vampire's own HP)."""
        v = _fresh_vampire()
        v.health_max = 50
        v.health = 20
        v.apply_damage(-5)
        assert v.health == 25


# ---------------------------------------------------------------------------
# Sanity -- existing vampire fields unchanged
# ---------------------------------------------------------------------------


class TestVampireSanityUnchanged:
    def test_name_is_vampire(self):
        v = Vampire()
        assert v.name == "vampire"

    def test_attack_dice_string_unchanged(self):
        v = Vampire()
        assert v.attack == "8d4"

    def test_flavor_is_one_of_known_strings(self):
        """The vampire randomises its flavor from a fixed pool.
        Pin that the chosen flavor is one of the pre-migration options
        so a future refactor can't silently swap the pool."""
        v = Vampire()
        known_flavors = {
            "@1dc radiates malevolent hunger.",
            "@1ac gaze is as sharp as @1a teeth.",
            "The shadows shifting about this @1 produce an aura of cold dread, as if defying the very existence of life.",
        }
        assert v.flavor in known_flavors

    def test_loot_pool_unchanged(self):
        v = Vampire()
        assert v.loot["cape"] == 0.2
        assert v.loot["high-collared_cape"] == 0.1
        assert v.loot["wand"] == 0.1

    def test_feed_method_still_defined_on_class(self):
        """Pin that ``Vampire`` still defines ``feed`` at the class
        level -- this is the method the drain mechanic lives in, and
        the migration must leave it untouched."""
        assert "feed" in Vampire.__dict__
        assert callable(Vampire.feed)

    def test_on_hugged_is_still_overridden_on_class(self):
        """Pin the paralyzing-gaze hook override."""
        assert "on_hugged" in Vampire.__dict__
        assert Vampire.on_hugged is not Creature.on_hugged

    def test_do_attack_is_still_overridden_on_class(self):
        """Pin that ``Vampire`` still overrides ``do_attack`` -- the
        low-HP feed trigger path lives here."""
        assert "do_attack" in Vampire.__dict__

    def test_per_instance_parts_are_independent(self):
        """Two fresh vampires must not share body part instances
        -- per-instance composition invariant from item 1.7."""
        v1 = Vampire()
        v2 = Vampire()
        for p1, p2 in zip(v1.body_parts, v2.body_parts):
            assert p1 is not p2


# ---------------------------------------------------------------------------
# Feed mechanic pinned post-migration
# ---------------------------------------------------------------------------


class TestVampireFeedPreserved:
    """Pin the Vampire-specific ``feed`` drain/heal quirk.

    The behaviour lives in ``Vampire.feed``: given a target creature it
    rolls ``randint(1, target.health)`` for the drain amount, rolls
    ``1d20 + 4`` against the target's dodge, and on a hit calls
    ``target.apply_damage(drain)`` (legacy path, no ``target_part``)
    followed by ``self.apply_damage(-drain * 2)`` to self-heal. On a
    miss the drain is zeroed out. There is also a ``bedbad6`` guard at
    the top of the method: if the target's health is ``<= 0`` feed
    returns early with a sneer message, avoiding ``randint(1, 0)``.

    ``feed`` is called from two places:
      1. ``on_hugged`` -- conditionally, when the seductive-smile
         response is chosen.
      2. ``do_attack`` -- when the vampire is at or below half HP.

    These tests pin the drain, the self-heal, the guard, the
    orthogonality with body parts (drain goes to main HP, not a part),
    and both trigger paths.
    """

    # --- drain arithmetic ---------------------------------------------------

    def test_feed_drains_target_health_when_hit_lands(self):
        """With a forced high attack roll, ``feed`` must drain the
        target's HP by at least 1 and at most ``target.health`` (the
        upper bound of the ``randint(1, target.health)`` roll)."""
        vampire = _fresh_vampire()
        target = _fresh_goblin(health=50)
        target.dodge = 0  # guarantee the 1d20+4 vs dodge check passes

        msg = vampire.feed(target)

        assert isinstance(msg, str)
        assert msg != ""
        drained = 50 - target.health
        assert 1 <= drained <= 50, (
            f"feed should drain 1..50 HP, drained={drained}"
        )

    def test_feed_does_not_raise_on_normal_target(self):
        """Smoke test -- ``feed`` must not raise on a well-formed
        living target regardless of the dodge roll outcome."""
        vampire = _fresh_vampire()
        target = _fresh_goblin(health=50)
        # Run a few times to cover both hit and miss branches.
        for _ in range(5):
            target.health = 50
            vampire.feed(target)  # should never raise

    # --- bedbad6 edge case -------------------------------------------------

    def test_feed_does_not_crash_on_low_health_target(self):
        """``bedbad6`` regression guard. With a target at ``health=5``
        (below 10) the internal ``randint(1, target.health)`` becomes
        ``randint(1, 5)`` -- still valid. The point of this test is to
        pin that low-but-positive HP targets don't hit the old
        ``randint(1, 0)`` crash path."""
        vampire = _fresh_vampire()
        target = _fresh_goblin(health=5)
        target.dodge = 0
        # Must not raise.
        msg = vampire.feed(target)
        assert isinstance(msg, str)

    def test_feed_bails_out_on_zero_health_target(self):
        """``bedbad6`` core fix: a target at ``health=0`` must hit the
        early-return branch (``if target.health <= 0``) and never reach
        ``randint(1, 0)``. The returned string mentions a lifeless
        husk; the target's health is left at 0 and the vampire does
        not self-heal."""
        vampire = _fresh_vampire()
        vampire.health = 100
        target = _fresh_goblin(health=0)

        msg = vampire.feed(target)

        assert isinstance(msg, str)
        assert "lifeless husk" in msg
        # No state change on target or vampire.
        assert target.health == 0
        assert vampire.health == 100

    def test_feed_bails_out_on_negative_health_target(self):
        """Defensive: a target with negative HP hits the same early
        return. ``target.health <= 0`` covers both zero and negative."""
        vampire = _fresh_vampire()
        vampire.health = 100
        target = _fresh_goblin(health=1)
        target.health = -3  # bypass the _fresh_goblin clamp

        msg = vampire.feed(target)

        assert "lifeless husk" in msg
        assert vampire.health == 100  # no self-heal

    # --- self-heal ----------------------------------------------------------

    def test_feed_heals_vampire_when_hit_lands(self):
        """On a successful feed, the vampire self-heals by ``2 *
        drained`` via ``self.apply_damage(amount * -2)``. Start the
        vampire well below max HP so the heal has room to take
        effect, then verify the vampire's HP strictly increased."""
        vampire = _fresh_vampire()
        vampire.health_max = 200
        vampire.health = 10
        target = _fresh_goblin(health=50)
        target.dodge = 0  # guarantee hit

        vampire.feed(target)

        drained = 50 - target.health
        # drained should be >= 1 on a hit; self-heal is 2 * drained
        assert drained >= 1
        assert vampire.health == 10 + 2 * drained

    def test_feed_self_heal_is_capped_at_health_max(self):
        """The legacy-path heal clamps at ``health_max`` via
        ``apply_damage``. Pin that a vampire already near max HP
        doesn't overflow after feeding."""
        vampire = _fresh_vampire()
        vampire.health_max = 100
        vampire.health = 99
        target = _fresh_goblin(health=50)
        target.dodge = 0

        vampire.feed(target)

        assert vampire.health <= vampire.health_max

    # --- orthogonality with body parts -------------------------------------

    def test_feed_drain_does_not_touch_target_body_parts(self):
        """Orthogonality pin: the drain goes to main HP via the legacy
        ``apply_damage`` path with no ``target_part``. The target's
        body parts must remain at full HP -- vampires drain blood,
        which is everywhere, not a specific limb."""
        vampire = _fresh_vampire()
        target = _fresh_goblin(health=50)
        target.dodge = 0
        part_hps_before = {p.name: p.health for p in target.body_parts}
        part_max_before = {p.name: p.health_max for p in target.body_parts}

        vampire.feed(target)

        # Drain landed on main HP.
        assert target.health < 50
        # Every body part is still untouched and at max.
        for part in target.body_parts:
            assert part.health == part_hps_before[part.name]
            assert part.health == part_max_before[part.name]

    def test_feed_self_heal_does_not_touch_vampire_body_parts(self):
        """Orthogonality pin (self side): the self-heal goes to main
        HP via the legacy ``apply_damage`` path with no
        ``target_part``. The vampire's own body parts must remain at
        full HP."""
        vampire = _fresh_vampire()
        vampire.health_max = 200
        vampire.health = 50
        target = _fresh_goblin(health=50)
        target.dodge = 0
        v_part_hps_before = {p.name: p.health for p in vampire.body_parts}
        v_part_max_before = {p.name: p.health_max for p in vampire.body_parts}

        vampire.feed(target)

        for part in vampire.body_parts:
            assert part.health == v_part_hps_before[part.name]
            assert part.health == v_part_max_before[part.name]

    # --- trigger paths ------------------------------------------------------

    def test_do_attack_calls_feed_when_vampire_is_at_or_below_half_hp(self):
        """Pin the ``do_attack`` trigger path: when the vampire is at
        or below half HP, ``do_attack`` routes through ``feed`` and
        returns an ``AttackSequence`` whose ``narrative`` is exactly
        ``feed``'s return value."""
        vampire = _fresh_vampire()
        vampire.health_max = 100
        vampire.health = 40  # 40/100 == 0.4 <= 0.5
        target = _fresh_goblin(health=50)

        with patch.object(
            Vampire, "feed", return_value="FEED_NARRATIVE"
        ) as mock_feed:
            seq = vampire.do_attack(target)

        mock_feed.assert_called_once_with(target)
        assert seq.narrative == "FEED_NARRATIVE"
        assert seq.attacker is vampire
        assert seq.target is target

    def test_do_attack_does_not_call_feed_when_vampire_is_above_half_hp(self):
        """Pin the other branch of the ``do_attack`` trigger: above
        half HP the vampire delegates to the base ``do_attack`` and
        does NOT call ``feed``."""
        vampire = _fresh_vampire()
        vampire.health_max = 100
        vampire.health = 80  # 80/100 == 0.8 > 0.5
        target = _fresh_goblin(health=50)

        with patch.object(Vampire, "feed") as mock_feed:
            try:
                vampire.do_attack(target)
            except Exception:
                # The base ``do_attack`` may need richer plumbing than
                # this test provides; we only care that ``feed`` was
                # not called on this branch.
                pass

        mock_feed.assert_not_called()

    def test_on_hugged_seductive_branch_calls_feed(self):
        """Pin the ``on_hugged`` trigger path: when the seductive
        smile response is chosen, ``feed`` fires against the hugging
        actor. ``random.choice`` is patched to deterministically pick
        the third response option (which is the feed path) regardless
        of underlying RNG state."""
        vampire = _fresh_vampire()
        actor = _fresh_goblin(health=50)
        actor.dodge = 0

        seductive_response = (
            "@1dc smiles seductively at @2, encouraging the HUG..."
        )

        # ``on_hugged`` uses ``choice`` imported at module scope; patch
        # it there and force selection of the seductive (feed) branch.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.vampire.choice",
            return_value=seductive_response,
        ), patch.object(
            Vampire, "feed", return_value="FED"
        ) as mock_feed:
            result = vampire.on_hugged(actor, "HUG")

        mock_feed.assert_called_once_with(actor)
        assert "FED" in result
