"""Tests for the Phase B2 capability mixins.

Pins two things:
- Which plugins carry which mixins (the contract surface that
  Creature.find_all and upcoming B3/B4 work depend on).
- The per-plugin mixin attribute values (IS_PRIMARY_SENSE,
  MOBILITY_MODE) so a future sub-plugin doesn't accidentally
  flip the default and corrupt emergence.

Pure marker classes don't need deep tests — what matters is
that the right plugins ARE the right kind of thing.
"""

from unittest import TestCase

from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.toe import ToePlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.creatures.mixins import (
    Defensive,
    Equippable,
    Mobility,
    Offensive,
    Sensory,
)


class PluginMixinTaggingTests(TestCase):
    """One test per plugin pins the full mixin set it carries,
    plus any per-plugin mixin attribute overrides. Failures here
    catch accidental loss of a mixin during a refactor."""

    def test_head_is_offensive_sensory_equippable(self):
        head = HeadPlugin(name="head")
        self.assertIsInstance(head, Offensive)
        self.assertIsInstance(head, Sensory)
        self.assertIsInstance(head, Equippable)
        # Head is a FALLBACK sense only — not primary.
        self.assertFalse(head.IS_PRIMARY_SENSE)
        # Negative invariants: head is NOT Mobility or Defensive.
        self.assertNotIsInstance(head, Mobility)
        self.assertNotIsInstance(head, Defensive)

    def test_eye_is_primary_sensory(self):
        eye = EyePlugin(name="eye")
        self.assertIsInstance(eye, Sensory)
        self.assertTrue(eye.IS_PRIMARY_SENSE)
        # Eye is not Offensive (it doesn't attack on its own in B2 —
        # future basilisk work might tag a subclass).
        self.assertNotIsInstance(eye, Offensive)
        self.assertNotIsInstance(eye, Mobility)
        self.assertNotIsInstance(eye, Equippable)

    def test_arm_is_offensive_equippable(self):
        arm = ArmPlugin(name="arm.left")
        self.assertIsInstance(arm, Offensive)
        self.assertIsInstance(arm, Equippable)
        self.assertNotIsInstance(arm, Sensory)
        self.assertNotIsInstance(arm, Mobility)

    def test_leg_is_grounded_mobility_equippable(self):
        leg = LegPlugin(name="leg.left")
        self.assertIsInstance(leg, Mobility)
        self.assertIsInstance(leg, Equippable)
        self.assertEqual(leg.MOBILITY_MODE, "grounded")
        self.assertNotIsInstance(leg, Offensive)

    def test_wing_is_airborne_mobility(self):
        wing = WingPlugin(name="wing.left")
        self.assertIsInstance(wing, Mobility)
        self.assertEqual(wing.MOBILITY_MODE, "airborne")
        # Wing is not Equippable today (no wing-gear in the game).
        self.assertNotIsInstance(wing, Equippable)

    def test_torso_is_defensive_equippable(self):
        torso = TorsoPlugin(name="torso")
        self.assertIsInstance(torso, Defensive)
        self.assertIsInstance(torso, Equippable)
        self.assertNotIsInstance(torso, Mobility)

    def test_neck_is_equippable(self):
        neck = NeckPlugin(name="neck")
        self.assertIsInstance(neck, Equippable)
        # Neck has no combat-mechanical contribution today.
        self.assertNotIsInstance(neck, Offensive)
        self.assertNotIsInstance(neck, Defensive)
        self.assertNotIsInstance(neck, Mobility)
        self.assertNotIsInstance(neck, Sensory)

    def test_tail_is_unclassified_today(self):
        """Tail contributes DODGE *debuffs* via its debuffs table
        (destroyed tail → -DODGE) but not as a Mobility SOURCE.
        The :class:`TailPlugin` docstring aspires to tail-as-
        balance mobility, but no emergence path uses it that way
        today. B2 stays pure-refactor; tagging tail Mobility would
        change balance (pulling it into get_dodge's functionality
        ratio), so it's deferred to a deliberate design change."""
        tail = TailPlugin(name="tail")
        self.assertNotIsInstance(tail, Mobility)
        self.assertNotIsInstance(tail, Offensive)
        self.assertNotIsInstance(tail, Defensive)
        self.assertNotIsInstance(tail, Sensory)
        self.assertNotIsInstance(tail, Equippable)

    def test_toe_is_unclassified(self):
        """Toe is the dragon-variant DODGE-debuff curiosity — not
        a Mobility source, not Equippable, not anything else."""
        toe = ToePlugin(name="toe")
        self.assertNotIsInstance(toe, Mobility)
        self.assertNotIsInstance(toe, Offensive)
        self.assertNotIsInstance(toe, Defensive)
        self.assertNotIsInstance(toe, Sensory)
        self.assertNotIsInstance(toe, Equippable)


class FindAllTests(TestCase):
    """``Creature.find_all`` is the API surface that upcoming
    phases will lean on. Test it against real materialized
    anatomies, not hand-constructed fake lists."""

    def _new_player(self):
        from caldanai.lib.rpg.creatures.player import Player
        return Player(pid=1, gid=1, uid=1, health=20, health_max=20)

    def test_find_all_defensive_returns_torso(self):
        p = self._new_player()
        found = p.find_all(Defensive)
        self.assertEqual([n.name for n in found], ["torso"])

    def test_find_all_sensory_returns_head_and_eyes(self):
        p = self._new_player()
        found = p.find_all(Sensory)
        # Player has head (fallback sense) + two eyes (primary).
        names = sorted(n.name for n in found)
        self.assertEqual(names, ["eye.left", "eye.right", "head"])

    def test_find_all_mobility_returns_legs_and_feet_for_player(self):
        """Phase D: feet are grounded Mobility too — they're where
        the actual ground contact happens. Both legs and feet
        contribute."""
        p = self._new_player()
        found = p.find_all(Mobility)
        names = sorted(n.name for n in found)
        self.assertEqual(
            names,
            ["foot.left", "foot.right", "leg.left", "leg.right"],
        )
        for m in found:
            self.assertEqual(m.MOBILITY_MODE, "grounded")

    def test_find_all_offensive_returns_head_arms_hands(self):
        """Phase D: hands are Offensive (for punch / grapple
        actions), joining head (bite/headbutt) and arms (punch)."""
        p = self._new_player()
        names = sorted(n.name for n in p.find_all(Offensive))
        self.assertEqual(
            names,
            ["arm.left", "arm.right", "hand.left", "hand.right", "head"],
        )

    def test_find_all_equippable_covers_visible_parts(self):
        """Every visible body part on a player is Equippable per
        the B2 design. Phase D adds hand / foot nodes to the
        equippable set — gloves on hands, boots on feet."""
        p = self._new_player()
        names = sorted(n.name for n in p.find_all(Equippable))
        self.assertEqual(names, [
            "arm.left", "arm.right",
            "foot.left", "foot.right",
            "hand.left", "hand.right",
            "head",
            "leg.left", "leg.right",
            "neck",
            "torso",
        ])

    def test_find_all_preserves_body_parts_order(self):
        """The tree-walk order (which is the BODY_TREE declaration
        order) is load-bearing for aggregation math like
        ``_functionality_ratio`` — pin it."""
        p = self._new_player()
        find_all_order = [n.name for n in p.find_all(Sensory)]
        body_parts_order = [
            n.name for n in p.body_parts
            if isinstance(n, Sensory)
        ]
        self.assertEqual(find_all_order, body_parts_order)

    def test_find_all_on_dragon_finds_airborne_mobility(self):
        """Dragons have wings and legs — both Mobility, distinct
        MOBILITY_MODE values. Pins that the attribute carries
        through correctly for the emergence-selector pattern
        ``[p for p in find_all(Mobility) if p.MOBILITY_MODE == ...]``."""
        from caldanai.lib.rpg.creatures.monsters.dragon import Dragon
        d = Dragon()
        all_mob = d.find_all(Mobility)
        grounded = [p for p in all_mob if p.MOBILITY_MODE == "grounded"]
        airborne = [p for p in all_mob if p.MOBILITY_MODE == "airborne"]
        # Phase D: dragon has 4 legs + 4 paws (grounded) + 2 wings (airborne).
        self.assertEqual(len(grounded), 8)
        self.assertEqual(len(airborne), 2)

    def test_find_all_on_spirit_returns_empty(self):
        """Spirit has no body at all (BODY_TREE = None). Every
        find_all call returns []."""
        from caldanai.lib.rpg.creatures.monsters.spirit import Spirit
        s = Spirit()
        for mixin in (Offensive, Sensory, Mobility, Defensive, Equippable):
            self.assertEqual(s.find_all(mixin), [])
