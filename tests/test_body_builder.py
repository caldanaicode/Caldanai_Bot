"""Tests for the Phase B1 body-tree builder DSL.

Covers the two factory functions (:func:`node`, :func:`paired`)
and the :class:`_NodeSpec` materialization contract. Uses bare
:class:`Node` subclasses as stand-in plugins so the DSL tests
don't depend on the full BodyPart / BodyPartPlugin machinery —
that integration is covered by the per-creature migration tests.
"""

from unittest import TestCase

from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.node import Node


class _StubPlugin(Node):
    """Plain Node subclass that accepts kwargs the way real
    BodyPartPlugin classes do. Supports class-level ``name``
    defaults (so ``node(_TorsoStub)`` without explicit name
    uses ``"torso"``), and arbitrary overrides for test
    inspection."""

    name = ""

    def __init__(self, name=None, **overrides):
        super().__init__(name=name or type(self).name)
        self.overrides = overrides


class _TorsoStub(_StubPlugin):
    name = "torso"


class _NeckStub(_StubPlugin):
    name = "neck"


class _HeadStub(_StubPlugin):
    name = "head"


class _ArmStub(_StubPlugin):
    name = "arm"


class _EyeStub(_StubPlugin):
    name = "eye"


class _HandStub(_StubPlugin):
    name = "hand"


class _LegStub(_StubPlugin):
    name = "leg"


class NodeFactoryTests(TestCase):
    def test_node_without_children_builds_leaf(self):
        spec = node(_HeadStub)
        tree = spec.build()
        self.assertIsInstance(tree, _HeadStub)
        self.assertEqual(tree.name, "head")
        self.assertIsNone(tree.parent)
        self.assertEqual(tree.children, [])

    def test_node_with_explicit_name_overrides_class_default(self):
        spec = node(_HeadStub, name="head.2")
        tree = spec.build()
        self.assertEqual(tree.name, "head.2")

    def test_node_with_children_wires_parents(self):
        spec = node(_TorsoStub, children=[
            node(_HeadStub),
            node(_ArmStub, name="arm.left"),
        ])
        tree = spec.build()
        names = [n.name for n in tree.walk()]
        self.assertEqual(names, ["torso", "head", "arm.left"])
        for child in tree.children:
            self.assertIs(child.parent, tree)

    def test_node_overrides_passed_to_plugin_constructor(self):
        spec = node(_ArmStub, name="arm.left", health_max=12, custom_flag=True)
        tree = spec.build()
        self.assertEqual(tree.overrides, {"health_max": 12, "custom_flag": True})

    def test_same_spec_builds_fresh_instances(self):
        spec = node(_TorsoStub, children=[node(_ArmStub, name="arm.left")])
        a = spec.build()
        b = spec.build()
        # Two distinct trees — mutating one must not affect the other.
        self.assertIsNot(a, b)
        self.assertIsNot(a.children[0], b.children[0])


class PairedFactoryTests(TestCase):
    def test_paired_emits_two_specs(self):
        specs = paired(_ArmStub, "arm")
        self.assertEqual(len(specs), 2)
        built = [spec.build() for spec in specs]
        self.assertEqual([n.name for n in built], ["arm.left", "arm.right"])

    def test_paired_under_torso_builds_symmetric_tree(self):
        root = node(_TorsoStub, children=[*paired(_LegStub, "leg")]).build()
        names = [n.name for n in root.walk()]
        self.assertEqual(names, ["torso", "leg.left", "leg.right"])

    def test_paired_with_children_builder_names_per_side(self):
        """``hand.left`` lives under ``arm.left``, ``hand.right``
        under ``arm.right``. Each side gets its own child
        subtree, named symmetrically."""
        arms = paired(
            _ArmStub,
            "arm",
            children_builder=lambda side: [node(_HandStub, name=f"hand.{side}")],
        )
        root = node(_TorsoStub, children=list(arms)).build()
        names = [n.name for n in root.walk()]
        self.assertEqual(
            names,
            ["torso", "arm.left", "hand.left", "arm.right", "hand.right"],
        )
        # Verify parent wiring on the per-side hand children.
        hand_left = root.find("hand.left")
        hand_right = root.find("hand.right")
        assert hand_left is not None and hand_right is not None
        self.assertEqual(hand_left.parent.name, "arm.left")
        self.assertEqual(hand_right.parent.name, "arm.right")

    def test_paired_overrides_applied_to_both_sides(self):
        specs = paired(_ArmStub, "arm", health_max=12)
        for spec in specs:
            built = spec.build()
            self.assertEqual(built.overrides, {"health_max": 12})


class UniquenessCheckTests(TestCase):
    def test_duplicate_name_at_same_level_raises(self):
        spec = node(_TorsoStub, children=[
            node(_ArmStub, name="arm.left"),
            node(_ArmStub, name="arm.left"),  # dup!
        ])
        with self.assertRaises(ValueError) as ctx:
            spec.build()
        self.assertIn("arm.left", str(ctx.exception))

    def test_duplicate_name_across_levels_raises(self):
        spec = node(_TorsoStub, children=[
            node(_HeadStub),
            node(_ArmStub, name="head"),  # collides with head above
        ])
        with self.assertRaises(ValueError):
            spec.build()

    def test_unique_tree_builds_clean(self):
        spec = node(_TorsoStub, children=[
            node(_NeckStub, children=[
                node(_HeadStub, children=[*paired(_EyeStub, "eye")]),
            ]),
            *paired(_ArmStub, "arm"),
            *paired(_LegStub, "leg"),
        ])
        root = spec.build()
        names = [n.name for n in root.walk()]
        self.assertEqual(
            names,
            [
                "torso",
                "neck",
                "head",
                "eye.left",
                "eye.right",
                "arm.left",
                "arm.right",
                "leg.left",
                "leg.right",
            ],
        )


class HydraLikeDynamicTreeTests(TestCase):
    """Sanity check the 'list-comp-inside-children' pattern the
    Hydra family will use post-B1. Not strictly a DSL feature —
    it's what happens when you pass a dynamically generated list
    as ``children`` — but pin it so the hydra use case stays
    readable."""

    def test_dynamic_head_count_builds_correctly(self):
        head_count = 5
        root = node(_TorsoStub, children=[
            *[
                node(_NeckStub, name=f"neck.{i}", children=[
                    node(_HeadStub, name=f"head.{i}"),
                ])
                for i in range(1, head_count + 1)
            ],
        ]).build()
        names = [n.name for n in root.walk()]
        expected = ["torso"]
        for i in range(1, head_count + 1):
            expected.extend([f"neck.{i}", f"head.{i}"])
        self.assertEqual(names, expected)
