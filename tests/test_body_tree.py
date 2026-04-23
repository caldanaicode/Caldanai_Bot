"""Tests for the Phase B1 tree primitive.

Covers the contract exposed by :class:`caldanai.lib.rpg.creatures.node.Node`:
identity / hierarchy wiring, depth-first traversal, exact-name
lookup, ancestor walk, and the reachability semantics that earn
the migration (destroyed middle node → descendants unreachable
even when their own state is healthy).

The body-tree builder DSL has its own test file
(``tests/test_body_builder.py``); this one pins the primitive.
"""

from unittest import TestCase

from caldanai.lib.rpg.creatures.node import Node


class _DestroyableNode(Node):
    """Helper that lets tests flip destroyed state without
    pulling in BodyPart / health machinery."""

    def __init__(self, name: str = "", destroyed: bool = False):
        super().__init__(name=name)
        self._destroyed = destroyed

    def is_destroyed(self) -> bool:
        return self._destroyed


class TreeConstructionTests(TestCase):
    def test_bare_node_has_empty_children_and_no_parent(self):
        n = Node(name="torso")
        self.assertEqual(n.name, "torso")
        self.assertIsNone(n.parent)
        self.assertEqual(n.children, [])

    def test_add_child_wires_parent_and_appends(self):
        torso = Node(name="torso")
        arm = Node(name="arm.left")
        returned = torso.add_child(arm)
        self.assertIs(returned, arm)
        self.assertIs(arm.parent, torso)
        self.assertEqual(torso.children, [arm])

    def test_add_child_supports_multiple_children_in_order(self):
        torso = Node(name="torso")
        for label in ("arm.left", "arm.right", "leg.left", "leg.right"):
            torso.add_child(Node(name=label))
        self.assertEqual(
            [c.name for c in torso.children],
            ["arm.left", "arm.right", "leg.left", "leg.right"],
        )

    def test_add_child_reassigns_parent_on_reattach(self):
        a = Node(name="a")
        b = Node(name="b")
        leaf = Node(name="leaf")
        a.add_child(leaf)
        # Re-attaching to b should update the leaf's parent; B1
        # does not require reparenting, but the API shouldn't
        # silently leave a stale parent pointer.
        b.add_child(leaf)
        self.assertIs(leaf.parent, b)


class WalkTests(TestCase):
    def _build_humanoid(self):
        torso = Node(name="torso")
        neck = torso.add_child(Node(name="neck"))
        head = neck.add_child(Node(name="head"))
        head.add_child(Node(name="eye.left"))
        head.add_child(Node(name="eye.right"))
        torso.add_child(Node(name="arm.left"))
        torso.add_child(Node(name="arm.right"))
        torso.add_child(Node(name="leg.left"))
        torso.add_child(Node(name="leg.right"))
        return torso

    def test_walk_depth_first_preorder(self):
        torso = self._build_humanoid()
        names = [n.name for n in torso.walk()]
        self.assertEqual(names, [
            "torso",
            "neck",
            "head",
            "eye.left",
            "eye.right",
            "arm.left",
            "arm.right",
            "leg.left",
            "leg.right",
        ])

    def test_walk_on_leaf_yields_only_self(self):
        leaf = Node(name="eye.left")
        self.assertEqual([n.name for n in leaf.walk()], ["eye.left"])

    def test_walk_on_subtree_yields_only_subtree(self):
        torso = self._build_humanoid()
        head = torso.find("head")
        assert head is not None
        names = [n.name for n in head.walk()]
        self.assertEqual(names, ["head", "eye.left", "eye.right"])


class FindTests(TestCase):
    def test_find_returns_matching_node(self):
        torso = Node(name="torso")
        arm = torso.add_child(Node(name="arm.left"))
        self.assertIs(torso.find("arm.left"), arm)

    def test_find_returns_none_for_missing(self):
        torso = Node(name="torso")
        torso.add_child(Node(name="arm.left"))
        self.assertIsNone(torso.find("tail"))

    def test_find_finds_root_itself(self):
        torso = Node(name="torso")
        self.assertIs(torso.find("torso"), torso)


class AncestorTests(TestCase):
    def test_ancestors_walks_up_chain(self):
        torso = Node(name="torso")
        neck = torso.add_child(Node(name="neck"))
        head = neck.add_child(Node(name="head"))
        eye = head.add_child(Node(name="eye.left"))
        self.assertEqual(
            [a.name for a in eye.ancestors()],
            ["head", "neck", "torso"],
        )

    def test_ancestors_on_root_is_empty(self):
        torso = Node(name="torso")
        self.assertEqual(list(torso.ancestors()), [])


class ReachabilityTests(TestCase):
    def _build(self, *, torso_dead=False, arm_dead=False, head_dead=False):
        """Builds a minimal humanoid with destroyable nodes and
        flips the given states. Returns (torso, arm, hand, head,
        eye) tuple for assertion convenience."""
        torso = _DestroyableNode(name="torso", destroyed=torso_dead)
        arm = _DestroyableNode(name="arm.left", destroyed=arm_dead)
        hand = _DestroyableNode(name="hand.left")
        head = _DestroyableNode(name="head", destroyed=head_dead)
        eye = _DestroyableNode(name="eye.left")
        torso.add_child(arm)
        arm.add_child(hand)
        torso.add_child(head)
        head.add_child(eye)
        return torso, arm, hand, head, eye

    def test_healthy_chain_every_node_reachable(self):
        torso, arm, hand, head, eye = self._build()
        for n in (torso, arm, hand, head, eye):
            self.assertTrue(n.is_reachable(), f"{n.name} should be reachable")

    def test_destroyed_root_every_descendant_unreachable(self):
        torso, arm, hand, head, eye = self._build(torso_dead=True)
        for n in (torso, arm, hand, head, eye):
            self.assertFalse(
                n.is_reachable(),
                f"{n.name} should be unreachable under destroyed root",
            )

    def test_destroyed_middle_only_its_subtree_is_unreachable(self):
        torso, arm, hand, head, eye = self._build(arm_dead=True)
        # Arm itself destroyed → unreachable.
        self.assertFalse(arm.is_reachable())
        # Hand is child of dead arm → unreachable even though hand
        # is healthy.
        self.assertFalse(hand.is_reachable())
        # Sibling subtree (head + eye) is untouched.
        self.assertTrue(torso.is_reachable())
        self.assertTrue(head.is_reachable())
        self.assertTrue(eye.is_reachable())

    def test_destroyed_leaf_only_itself_unreachable(self):
        torso, arm, hand, head, eye = self._build(head_dead=True)
        # Head destroyed.
        self.assertFalse(head.is_reachable())
        # Eye (child of dead head) → unreachable.
        self.assertFalse(eye.is_reachable())
        # The rest is fine.
        self.assertTrue(torso.is_reachable())
        self.assertTrue(arm.is_reachable())
        self.assertTrue(hand.is_reachable())

    def test_default_node_is_destroyed_returns_false(self):
        """Bare Node without health tracking is never destroyed —
        callers can walk the tree without combat machinery."""
        n = Node(name="structural")
        self.assertFalse(n.is_destroyed())
        self.assertTrue(n.is_reachable())
