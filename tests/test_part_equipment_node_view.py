"""Tests for the Phase B3 node-view part_equipment contract.

B3 moved equipment placement storage off ``Player.part_equipment``
(a nested dict field) onto each :class:`Equippable` body-part
node (a ``placements`` dict populated by the plugin's
``PLACEMENT_KEYS``). ``Player.part_equipment`` is now a
``@property`` that returns a dict whose inner values are live
references to each node's ``placements`` — so dict-style reads
and writes continue to work for back-compat.

Phase D updated the ``PLACEMENT_KEYS`` vocabulary to generic
``worn``/``held``/``outer``/``accent`` with dotted sub-keys,
and introduced hand/foot as dedicated body-part nodes.

Pins here:
- The property reports live state matching the nodes.
- Writes through the property (dict-style) propagate to the
  authoritative node storage.
- The new ``place`` / ``clear_placement`` helpers perform the
  expected mutations and surface KeyError on typos.
- A fresh Player's nodes come with the full PLACEMENT_KEYS set
  pre-populated to None (no more Player-side pre-seed loop).
"""

from unittest import TestCase
from unittest.mock import MagicMock

from caldanai.lib.rpg.creatures.mixins import Equippable
from caldanai.lib.rpg.creatures.player import Player


def _fresh_player() -> Player:
    p = Player(
        pid=1, gid=1, uid=1,
        health=20, health_max=20,
        defense=3, dodge=5,
    )
    p.member = MagicMock()
    p.member.id = 1
    return p


class NodeViewPropertyTests(TestCase):
    def test_property_returns_dict_of_live_node_placements(self):
        p = _fresh_player()
        view = p.part_equipment
        head_node = p.get_part("head")
        self.assertIs(view["head"], head_node.placements)

    def test_property_iterates_over_all_equippable_parts(self):
        """Every ``Equippable`` node appears as a top-level key.
        Non-equippable parts (eyes) do not."""
        p = _fresh_player()
        view = p.part_equipment
        self.assertIn("torso", view)
        self.assertIn("head", view)
        self.assertIn("neck", view)
        self.assertIn("arm.left", view)
        self.assertIn("leg.right", view)
        self.assertIn("hand.left", view)
        self.assertIn("foot.right", view)
        # Eyes are Sensory but not Equippable — absent from view.
        self.assertNotIn("eye.left", view)
        self.assertNotIn("eye.right", view)

    def test_fresh_placements_are_all_none(self):
        """Nodes self-init their placements dict at materialization
        time. No Player-side pre-seed loop needed anymore."""
        p = _fresh_player()
        for part_name, placements in p.part_equipment.items():
            for key, val in placements.items():
                self.assertIsNone(
                    val,
                    f"{part_name}.{key} should be None on fresh player"
                )

    def test_placement_keys_match_plugin_declaration(self):
        """Each node's placements dict has exactly the keys its
        plugin declared — no cross-contamination.

        Phase D generic-key vocabulary: ``worn`` is main armor,
        ``outer`` is overlay, ``accent`` is jewelry/accessory,
        ``held`` is hand only. Dotted sub-keys carry paired or
        layered variants (``worn.upper`` vs ``worn.lower``;
        ``ring.1`` vs ``ring.2``; ``earring.left`` vs ``.right``).
        """
        p = _fresh_player()
        self.assertEqual(
            set(p.part_equipment["head"].keys()),
            {"worn", "outer", "earring.left", "earring.right", "accent"},
        )
        self.assertEqual(
            set(p.part_equipment["torso"].keys()),
            {"worn", "outer", "accent"},
        )
        self.assertEqual(
            set(p.part_equipment["arm.left"].keys()),
            {"worn.upper", "worn.lower"},
        )
        self.assertEqual(
            set(p.part_equipment["hand.left"].keys()),
            {"held", "worn", "ring.1", "ring.2"},
        )
        self.assertEqual(
            set(p.part_equipment["neck"].keys()),
            {"accent"},
        )


class LegacyWriteCompatTests(TestCase):
    """The pre-B3 world wrote ``player.part_equipment[x][y] = z``
    directly. Those sites have to keep working via the
    property's live-ref inner dicts."""

    def test_dict_style_write_propagates_to_node(self):
        p = _fresh_player()
        fake_item = MagicMock()
        fake_item.name = "shiny_helm"
        p.part_equipment["head"]["worn"] = fake_item

        head_node = p.get_part("head")
        self.assertIs(head_node.placements["worn"], fake_item)

    def test_dict_style_clear_propagates_to_node(self):
        p = _fresh_player()
        fake_item = MagicMock()
        p.part_equipment["hand.left"]["held"] = fake_item
        # Clearing back to None through the view.
        p.part_equipment["hand.left"]["held"] = None
        self.assertIsNone(p.get_part("hand.left").placements["held"])


class PlaceHelperTests(TestCase):
    def test_place_writes_to_authoritative_node_storage(self):
        p = _fresh_player()
        fake_item = MagicMock()
        fake_item.name = "magic_belt"
        p.place("torso", "accent", fake_item)

        torso = p.get_part("torso")
        self.assertIs(torso.placements["accent"], fake_item)

    def test_place_view_read_after_helper_write(self):
        """Writing through the helper is visible via the legacy
        property read."""
        p = _fresh_player()
        fake_item = MagicMock()
        p.place("hand.right", "held", fake_item)
        self.assertIs(p.part_equipment["hand.right"]["held"], fake_item)

    def test_clear_placement_sets_to_none(self):
        p = _fresh_player()
        fake_item = MagicMock()
        p.place("head", "worn", fake_item)
        p.clear_placement("head", "worn")
        self.assertIsNone(p.part_equipment["head"]["worn"])

    def test_place_raises_on_unknown_part(self):
        p = _fresh_player()
        with self.assertRaises(KeyError) as ctx:
            p.place("not_a_part", "held", MagicMock())
        self.assertIn("no equippable part", str(ctx.exception).lower())

    def test_place_raises_on_non_equippable_part(self):
        p = _fresh_player()
        # Eyes are Sensory but not Equippable.
        with self.assertRaises(KeyError):
            p.place("eye.left", "lens", MagicMock())

    def test_place_raises_on_unknown_key(self):
        p = _fresh_player()
        with self.assertRaises(KeyError) as ctx:
            p.place("head", "not_a_key", MagicMock())
        self.assertIn("valid keys", str(ctx.exception))
