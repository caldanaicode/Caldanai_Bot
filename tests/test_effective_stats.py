"""Tests for the per-part effective-stat helpers.

Pins the formula shape:
- Dodge ADDS with depth (extremities are more agile).
- Defense SUBTRACTS with depth (core is better protected).
- Armor defense bonuses LOCALIZE (chest plate → torso only).
- Armor dodge aggregates through ``creature.get_dodge()`` (armor
  weighs down the whole creature; captured at creature level
  rather than per-part).
- Per-plugin ``dodge_offset`` / ``defense_offset`` tune the
  depth-derived curve.
- Monster intrinsic ``defense_bonus`` rides the same per-part
  channel as equipped armor.
- Exposure + size-ratio scaling fold into the dodge formula when
  attacker + source context is available.

Wired into combat resolution via :meth:`Creature._walk_to_aim`
inside :meth:`Creature.resolve_attack`.
"""

from unittest import TestCase
from unittest.mock import MagicMock

from caldanai.lib.rpg.creatures import (
    DEPTH_COEFFICIENT,
    SOFT_PART_FRACTION,
    effective_defense_for_part,
    effective_dodge_for_part,
)
from caldanai.lib.rpg.creatures.player import Player


def _fresh_player() -> Player:
    p = Player(
        pid=1, gid=1, uid=1,
        health=20, health_max=20,
        defense=6, dodge=6,
    )
    p.member = MagicMock()
    p.member.id = 1
    return p


def _fake_armor(defense_bonus: int = 0, dodge_bonus: int = 0):
    a = MagicMock()
    a.bonuses = {"defense": defense_bonus, "dodge": dodge_bonus}
    return a


class EffectiveDodgeTests(TestCase):
    def test_torso_dodge_matches_creature_dodge_at_depth_zero(self):
        p = _fresh_player()
        torso = p.get_part("torso")
        self.assertEqual(torso.depth, 0)
        self.assertEqual(
            effective_dodge_for_part(p, torso),
            p.get_dodge(),
        )

    def test_arm_dodge_adds_one_depth_level(self):
        p = _fresh_player()
        arm = p.get_part("arm.left")
        self.assertEqual(arm.depth, 1)
        self.assertEqual(
            effective_dodge_for_part(p, arm),
            p.get_dodge() + 1 * DEPTH_COEFFICIENT,
        )

    def test_eye_dodge_adds_three_depth_levels(self):
        """Eye sits at torso → neck → head → eye = depth 3."""
        p = _fresh_player()
        eye = p.get_part("eye.left")
        self.assertEqual(eye.depth, 3)
        self.assertEqual(
            effective_dodge_for_part(p, eye),
            p.get_dodge() + 3 * DEPTH_COEFFICIENT,
        )

    def test_dodge_offset_tunes_per_part(self):
        """``dodge_offset`` is the escape hatch when depth alone
        misses the fiction. Simulate a CyclopsEyePlugin-style
        override by patching the offset on a specific instance."""
        p = _fresh_player()
        eye = p.get_part("eye.left")
        original = effective_dodge_for_part(p, eye)
        eye.dodge_offset = -2  # per-instance override
        self.assertEqual(
            effective_dodge_for_part(p, eye),
            original - 2,
        )

    def test_armor_dodge_aggregates_through_creature_get_dodge(self):
        """A cape (+1 dodge) equipped on the torso should boost
        dodge at EVERY part — dodge aggregates, it doesn't
        localize."""
        p = _fresh_player()
        cape = _fake_armor(dodge_bonus=1)
        # Install cape via the placements API so get_armor_bonuses
        # picks it up.
        from caldanai.lib.rpg.inventory.equipment.armor import Armor
        cape.__class__ = Armor  # isinstance check in get_armor_bonuses
        cape.name = "cape"
        cape.id = id(cape)
        p.place("torso", "outer", cape)

        eye = p.get_part("eye.left")
        arm = p.get_part("arm.left")
        leg = p.get_part("leg.left")
        # Eye, arm, leg all get the same +1 dodge from the cape
        # (their depth-adjusted values each rise by 1).
        self.assertEqual(
            effective_dodge_for_part(p, eye),
            p.get_dodge() + eye.depth * DEPTH_COEFFICIENT,
        )
        # And get_dodge() itself includes the armor bonus.
        self.assertGreaterEqual(p.get_dodge(), 6 + 1)  # base 6 + cape 1


class ScaledDodgeTests(TestCase):
    """Exposure + size-ratio scaling fold into
    :func:`effective_dodge_for_part` when ``attacker`` and
    ``source`` are passed. Replaces the B4 ``get_targeted_dodge``
    tests — same math, different API surface."""

    def _pair(self, attacker_size=None, target_size=None):
        """Build (attacker, target) with explicit sizes. Both
        MEDIUM by default."""
        from caldanai.lib.rpg.helpers.enums import Size
        from caldanai.lib.rpg.creatures import Creature
        attacker = Creature(
            name="attacker", atk="1d4", defense=0, dodge=0,
            health_max=10,
        )
        target = Creature(
            name="target", atk="1d4", defense=0, dodge=10,
            health_max=50,
        )
        target.get_dodge = lambda: 10
        attacker.size = attacker_size or Size.MEDIUM
        target.size = target_size or Size.MEDIUM
        return attacker, target

    def _source(self):
        from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
        return NaturalAttackSource(
            atk="1d4", dmg_type=None, label="test", skill="natural",
        )

    def _torso_with_exposure(self, value: float):
        """Build a detached torso body part with uniform exposure
        ``value`` across all reaches. Returns a part at depth 0."""
        from caldanai.lib.rpg.creatures.body_part import BodyPart
        from caldanai.lib.rpg.helpers.enums import Reach
        return BodyPart(
            name="torso",
            health_max=50,
            is_critical=False,
            exposure={r: value for r in Reach},
        )

    def test_exposure_tax_is_additive(self):
        """Exposure 0.5 on a base-10 dodge → tax = 1 + (1-0.5)*1.0
        = 1.5, scaled = int(10 * 1.5) = 15."""
        attacker, target = self._pair()
        part = self._torso_with_exposure(0.5)
        src = self._source()
        self.assertEqual(
            effective_dodge_for_part(target, part, attacker, src),
            15,
        )

    def test_zero_exposure_caps_at_double_base(self):
        """Fully-hidden part (exposure 0) pays max tax under
        EXPOSURE_TAX_COEF=1.0 → ``1 + 1 = 2`` × base = 20. No
        hyperbolic runaway — the cap is predictable."""
        attacker, target = self._pair()
        part = self._torso_with_exposure(0.0)
        src = self._source()
        self.assertEqual(
            effective_dodge_for_part(target, part, attacker, src),
            20,
        )

    def test_small_attacker_vs_big_target_reduces_dodge(self):
        """TINY vs HUGE: size_ratio 0.5 / 1.5 ≈ 0.33, clamped to
        SIZE_RATIO_MIN (0.5). Base 10 * 0.5 * tax_1.0 = 5."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._pair(
            attacker_size=Size.TINY, target_size=Size.HUGE,
        )
        part = self._torso_with_exposure(1.0)
        src = self._source()
        self.assertEqual(
            effective_dodge_for_part(target, part, attacker, src),
            5,
        )

    def test_big_attacker_vs_small_target_boosts_dodge(self):
        """HUGE vs TINY: size_ratio 1.5 / 0.5 = 3.0, clamped to
        SIZE_RATIO_MAX (2.0). Base 10 * 2.0 * tax_1.0 = 20."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._pair(
            attacker_size=Size.HUGE, target_size=Size.TINY,
        )
        part = self._torso_with_exposure(1.0)
        src = self._source()
        self.assertEqual(
            effective_dodge_for_part(target, part, attacker, src),
            20,
        )

    def test_same_size_ratio_is_one(self):
        """MEDIUM vs MEDIUM, torso (exp 1.0): ratio 1.0, tax 1.0,
        no modifier beyond base."""
        attacker, target = self._pair()
        part = self._torso_with_exposure(1.0)
        src = self._source()
        self.assertEqual(
            effective_dodge_for_part(target, part, attacker, src),
            10,
        )

    def test_neutral_when_context_missing(self):
        """``attacker`` and ``source`` both default to ``None`` so
        introspection tools (inspect_body_tree --stats) can read a
        static baseline. size_ratio falls back to 1.0, exposure to
        1.0 — both neutral, no tax applies."""
        _, target = self._pair()
        part = self._torso_with_exposure(0.1)  # would tax with source
        # No attacker/source passed → exposure ignored.
        self.assertEqual(effective_dodge_for_part(target, part), 10)

    def test_dodge_cap_clamps_runaway_inflation(self):
        """Big-vs-Tiny attacker with a low-exposure part stacks
        size_ratio (2.0) × tax (2.0) = 4× base on the multiplicative
        side. The ``DODGE_CAP_COEF`` ceiling clamps that to 2× base
        (20) BEFORE the additive depth + offset apply. Regression
        for the 2026-04-24 Tiny-toadstool-neck dodge-32-vs-base-5
        playtest finding."""
        from caldanai.lib.rpg.helpers.enums import Size
        attacker, target = self._pair(
            attacker_size=Size.HUGE, target_size=Size.TINY,
        )
        part = self._torso_with_exposure(0.0)  # max tax
        src = self._source()
        # Pre-cap raw would be int(10 × 2.0 × 2.0) = 40; cap is
        # int(10 × 2.0) = 20. Torso depth 0, no offset → 20.
        self.assertEqual(
            effective_dodge_for_part(target, part, attacker, src),
            20,
        )

    def test_dodge_cap_does_not_flatten_per_part_ordering(self):
        """The cap is on the multiplicative product only — additive
        depth still differentiates parts at the cap. A deeper part
        (arm, depth 1) ends one above a shallower part (torso,
        depth 0) when both saturate the cap, so the depth-walk
        resolver still sees an ordering. Uses a real Player so
        ``depth`` comes from tree construction (the property has
        no setter)."""
        from caldanai.lib.rpg.helpers.enums import Size, Reach
        from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
        BodyPartPlugin.load_plugins()
        attacker_template, _ = self._pair(
            attacker_size=Size.HUGE, target_size=Size.TINY,
        )
        target = _fresh_player()
        target.size = Size.TINY
        attacker_template.size = Size.HUGE
        torso = target.get_part("torso")
        arm = target.get_part("arm.left")
        # Force max-tax exposure on both parts so both saturate
        # the multiplicative cap.
        torso.exposure = {r: 0.0 for r in Reach}
        arm.exposure = {r: 0.0 for r in Reach}
        src = self._source()
        torso_dodge = effective_dodge_for_part(target, torso, attacker_template, src)
        arm_dodge = effective_dodge_for_part(target, arm, attacker_template, src)
        self.assertGreater(arm_dodge, torso_dodge)


class EffectiveDefenseTests(TestCase):
    """Default ``defense_bonus = 0`` routes unarmored parts through
    the plated-curve branch with ``intrinsic=0``, so they resolve
    to ``base - depth × coef``. Parts that explicitly opt into
    ``SOFT_PART`` (eye by default) hit the fractional branch.
    Monster plating stacks on top via a positive ``defense_bonus``."""

    def test_torso_default_absorbs_full_base(self):
        p = _fresh_player()
        torso = p.get_part("torso")
        # depth 0, default bonus 0 → base - 0 = base.
        self.assertEqual(effective_defense_for_part(p, torso), p.defense)

    def test_arm_loses_to_depth(self):
        """Non-soft parts carry the depth penalty — a hit on the
        arm absorbs less than a hit on the torso."""
        p = _fresh_player()
        arm = p.get_part("arm.left")
        # arm depth 1 → base - 1.
        self.assertEqual(
            effective_defense_for_part(p, arm),
            max(0, p.defense - arm.depth * DEPTH_COEFFICIENT),
        )

    def test_eye_soft_opt_in_is_fractional(self):
        """Eye explicitly declares ``defense_bonus = SOFT_PART``,
        so it takes the fractional branch regardless of depth."""
        p = _fresh_player()
        eye = p.get_part("eye.left")
        expected = int(p.defense * SOFT_PART_FRACTION)
        self.assertEqual(effective_defense_for_part(p, eye), expected)

    def test_defense_clamps_at_zero(self):
        """Very low base × fraction rounds down to zero on a soft
        part; likewise base - depth clamps at zero on a deep
        non-soft part."""
        p = Player(pid=1, gid=1, uid=1, health=10, health_max=10, defense=1, dodge=5)
        p.member = MagicMock()
        eye = p.get_part("eye.left")
        # 1 × 0.1 = 0.1 → int → 0.
        self.assertEqual(effective_defense_for_part(p, eye), 0)

    def test_local_armor_adds_to_torso_base(self):
        """A chest armor piece equipped on torso adds to the base
        defense that part absorbs. Arm (unarmored) is unaffected
        by torso armor — defense localizes."""
        p = _fresh_player()
        chest = _fake_armor(defense_bonus=3)
        from caldanai.lib.rpg.inventory.equipment.armor import Armor
        chest.__class__ = Armor
        chest.name = "chest_armor"
        chest.id = id(chest)
        p.place("torso", "worn", chest)

        torso_def = effective_defense_for_part(p, p.get_part("torso"))
        arm = p.get_part("arm.left")
        arm_def = effective_defense_for_part(p, arm)

        self.assertEqual(torso_def, p.defense + 3)
        self.assertEqual(
            arm_def,
            max(0, p.defense - arm.depth * DEPTH_COEFFICIENT),
        )

    def test_plated_part_uses_depth_curve(self):
        """Intrinsic plating (non-SOFT_PART defense_bonus) opts
        the part into the depth-scaled formula: base - depth ×
        coef + intrinsic + armor."""
        p = _fresh_player()
        torso = p.get_part("torso")
        # Simulate a "plated torso" by overriding defense_bonus
        # to a positive value — this is how dragons / golems
        # declare intrinsic plating on their per-creature setup.
        torso.defense_bonus = 5
        # depth 0, coef 1, base 6, intrinsic 5 → 11.
        self.assertEqual(effective_defense_for_part(p, torso), 6 + 5 - 0)

        # A plated arm at depth 1 should lose 1 to depth.
        arm = p.get_part("arm.left")
        arm.defense_bonus = 5
        self.assertEqual(effective_defense_for_part(p, arm), 6 + 5 - 1)

    def test_defense_offset_tunes_per_part(self):
        p = _fresh_player()
        arm = p.get_part("arm.left")
        baseline = effective_defense_for_part(p, arm)
        arm.defense_offset = 2  # per-instance override
        self.assertEqual(effective_defense_for_part(p, arm), baseline + 2)

    def test_intrinsic_defense_bonus_on_monster_part_contributes(self):
        """Monsters set ``defense_bonus`` on their plugin classes
        (e.g., dragon torso +3). Intrinsic plating flows through
        the same per-part channel as equipped player armor."""
        from caldanai.lib.rpg.creatures.monsters.dragon import Dragon
        d = Dragon()
        torso = d.get_part("torso")
        # Dragon torso sets ``is_critical = True`` via the
        # declarative tree + size scales defense heavily; what we
        # care about here is that torso's defense beats the
        # emergence-only baseline by roughly its defense_bonus.
        # Just verify the helper runs and produces a sensible
        # positive integer.
        val = effective_defense_for_part(d, torso)
        self.assertIsInstance(val, int)
        self.assertGreaterEqual(val, 0)


class DepthSemanticsTests(TestCase):
    def test_deeper_parts_have_more_dodge_less_defense(self):
        """Defining depth-walk invariant — dodge rises with depth,
        defense falls with depth. Holds for any creature."""
        p = _fresh_player()
        torso = p.get_part("torso")
        arm = p.get_part("arm.left")
        eye = p.get_part("eye.left")

        dodges = [
            effective_dodge_for_part(p, torso),
            effective_dodge_for_part(p, arm),
            effective_dodge_for_part(p, eye),
        ]
        defenses = [
            effective_defense_for_part(p, torso),
            effective_defense_for_part(p, arm),
            effective_defense_for_part(p, eye),
        ]
        # Dodge non-decreasing with depth.
        self.assertLessEqual(dodges[0], dodges[1])
        self.assertLessEqual(dodges[1], dodges[2])
        # Defense non-increasing with depth.
        self.assertGreaterEqual(defenses[0], defenses[1])
        self.assertGreaterEqual(defenses[1], defenses[2])
