"""Tests for tools.inspect_body_tree.

The tool renders a body tree — structure, mixin tags, and
(Phase B3) per-node equipment placements. Tests here pin the
rendering shape so future B-arc changes (new mixin, new
placement key) have a single place to update the snapshot.
"""

from unittest import TestCase
from unittest.mock import MagicMock

from tools.inspect_body_tree import (
    _build_creature,
    _mixin_tags,
    _placements_summary,
    _render_tree,
    inspect,
)


class MixinTagRenderTests(TestCase):
    def test_head_renders_all_three_tags(self):
        from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
        h = HeadPlugin(name="head")
        tags = _mixin_tags(h)
        # Order is deterministic: Offensive, Sensory, Mobility,
        # Defensive, Equippable in declaration order.
        self.assertEqual(tags, "Offensive Sensory(fallback) Equippable")

    def test_eye_renders_primary_sense(self):
        from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
        e = EyePlugin(name="eye.left")
        self.assertEqual(_mixin_tags(e), "Sensory(primary)")

    def test_leg_renders_grounded_mobility(self):
        from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
        l = LegPlugin(name="leg.left")
        self.assertEqual(_mixin_tags(l), "Mobility(grounded) Equippable")

    def test_wing_renders_airborne_mobility(self):
        from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
        w = WingPlugin(name="wing.left")
        self.assertEqual(_mixin_tags(w), "Mobility(airborne)")

    def test_untagged_node_renders_em_dash(self):
        from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
        t = TailPlugin(name="tail")
        # Tail deliberately carries no mixin tags today (see B2
        # commit). Pins that the tool distinguishes "no tags" from
        # an empty tag list.
        self.assertEqual(_mixin_tags(t), "—")


class PlacementsSummaryTests(TestCase):
    def test_non_equippable_returns_empty_string(self):
        from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
        e = EyePlugin(name="eye.left")
        self.assertEqual(_placements_summary(e), "")

    def test_equippable_with_all_empty_placements(self):
        from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
        h = HeadPlugin(name="head")
        out = _placements_summary(h)
        # All four placement keys present, all empty (·).
        self.assertIn("helm=·", out)
        self.assertIn("face=·", out)
        self.assertIn("ear.left=·", out)
        self.assertIn("ear.right=·", out)

    def test_equippable_with_populated_placement(self):
        from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
        t = TorsoPlugin(name="torso")
        fake_item = MagicMock()
        fake_item.name = "plate_armor"
        t.placements["chest"] = fake_item
        out = _placements_summary(t)
        self.assertIn("chest=plate_armor", out)
        self.assertIn("cape=·", out)


class RenderTreeTests(TestCase):
    def test_render_tree_handles_none_root(self):
        """Spirits have ``body_root=None`` — the tool should
        render a sensible placeholder rather than crash."""
        out = _render_tree(None)
        self.assertEqual(out, ["  (no body tree)"])

    def test_render_tree_indents_children(self):
        from caldanai.lib.rpg.creatures.body_builder import node
        from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
        from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
        root = node(TorsoPlugin, name="torso", children=[
            node(HeadPlugin, name="head"),
        ]).build()
        lines = _render_tree(root)
        # Two lines: torso at indent 0, head at indent 1.
        self.assertEqual(len(lines), 2)
        self.assertTrue(lines[0].startswith("- torso"))
        self.assertTrue(lines[1].startswith("  - head"))


class BuildCreatureTests(TestCase):
    def test_player_target_builds_default_player(self):
        c = _build_creature("player")
        self.assertIsNotNone(c.body_root)
        # Default player has 9 body parts (torso/neck/head + 2
        # eyes + 2 arms + 2 legs).
        self.assertEqual(len(c.body_parts), 9)

    def test_monster_target_builds_via_plugin_registry(self):
        c = _build_creature("goblin")
        self.assertEqual(c.name, "goblin")

    def test_unknown_target_raises(self):
        with self.assertRaises(SystemExit) as ctx:
            _build_creature("not_a_real_monster")
        self.assertIn("Unknown target", str(ctx.exception))


class InspectTopLevelTests(TestCase):
    def test_inspect_player_includes_placements_line(self):
        """Top-level smoke: a fresh player's inspect() output
        includes both the header and at least one placements
        entry (torso has chest/cape/belt)."""
        out = inspect("player")
        self.assertIn("PLAYER", out)
        self.assertIn("torso", out)
        self.assertIn("chest=·", out)

    def test_inspect_spirit_reports_no_body_tree(self):
        """Spirit is the body-less monster. The inspect output
        should say so rather than crash."""
        out = inspect("spirit")
        self.assertIn("body_root=none", out)
        self.assertIn("(no body tree)", out)
