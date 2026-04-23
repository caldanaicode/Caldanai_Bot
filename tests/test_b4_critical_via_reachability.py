"""Phase B4: a destroyed non-critical part that severs a
critical descendant from the rest of the body tree kills the
creature.

Rationale: per the design contract, a body part being
``is_critical=True`` means "destroying it kills the creature."
Under B1's tree semantics, destroying a non-critical ancestor
makes descendants *unreachable* — the descendant's HP stays
intact but it's dangling off a ruined limb. For critical
descendants, unreachable = functionally dead = creature dies.

The canonical case is player anatomy: ``neck`` is non-critical
and sits between torso and head; ``head`` is critical. A broken
neck leaves the head dangling but functionally severed. By
design, that's death.
"""

from unittest import TestCase
from unittest.mock import MagicMock

from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import DamageTypes


def _fresh_player() -> Player:
    p = Player(
        pid=1, gid=1, uid=1,
        health=20, health_max=20,
        defense=3, dodge=5,
    )
    p.member = MagicMock()
    p.member.id = 1
    p.name = "TestSubject"
    return p


class NeckDestructionKillsPlayerTests(TestCase):
    def test_destroying_neck_kills_player_via_critical_head_descendant(self):
        """Neck is non-critical. Head is critical. Neck → head
        in the player's body tree. Destroying the neck severs
        the head → creature dies."""
        p = _fresh_player()
        neck = p.get_part("neck")
        assert neck is not None
        assert not neck.is_critical
        head = p.get_part("head")
        assert head is not None
        assert head.is_critical

        self.assertFalse(p.is_dead(), "fresh player should be alive")
        # Apply enough damage to destroy the neck directly.
        p.apply_damage(neck.health_max, dmg_type=None, target_part=neck)
        self.assertTrue(
            p.is_dead(),
            "player should be dead after neck destruction severs head",
        )

    def test_destroying_neck_via_multiple_small_hits_kills(self):
        """Cumulative damage that eventually destroys the neck
        should still trip the critical-descendant-unreachable
        death path."""
        p = _fresh_player()
        neck = p.get_part("neck")
        assert neck is not None

        # Chip away with damage smaller than max HP.
        while not neck.is_destroyed() and not p.is_dead():
            p.apply_damage(1, dmg_type=None, target_part=neck)
        self.assertTrue(p.is_dead())

    def test_non_critical_destruction_without_critical_descendant_does_not_kill(self):
        """Baseline: destroying an arm (no critical descendants)
        should leave the player alive. Only severance of critical
        descendants triggers the new death path."""
        p = _fresh_player()
        arm = p.get_part("arm.left")
        assert arm is not None
        assert not arm.is_critical

        p.apply_damage(arm.health_max, dmg_type=None, target_part=arm)
        self.assertTrue(arm.is_destroyed())
        self.assertFalse(
            p.is_dead(),
            "arm destruction with no critical descendants should not kill",
        )

    def test_destroying_head_directly_still_kills(self):
        """Pre-B4 behavior preserved: a critical part being
        directly destroyed kills the creature. The new B4 path
        only ADDS the ancestor-severance case."""
        p = _fresh_player()
        head = p.get_part("head")
        assert head is not None
        assert head.is_critical

        p.apply_damage(head.health_max, dmg_type=None, target_part=head)
        self.assertTrue(p.is_dead())

    def test_destroying_non_critical_part_with_non_critical_descendants_does_not_kill(self):
        """Example topology check: if a future non-critical part
        (say a hand, if it existed) were destroyed, and only the
        fingers beneath it were also non-critical, the creature
        wouldn't die. Today player anatomy doesn't have
        multi-level non-critical chains — verify the base arm
        destruction case (arm → no descendants at all) stays
        safe. Redundant with the arm test above but pins the
        decision for future deeper anatomies."""
        p = _fresh_player()
        leg = p.get_part("leg.left")
        assert leg is not None
        p.apply_damage(leg.health_max, dmg_type=None, target_part=leg)
        self.assertTrue(leg.is_destroyed())
        self.assertFalse(p.is_dead())
