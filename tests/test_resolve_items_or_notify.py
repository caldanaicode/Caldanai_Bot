"""Tests for ``RpgUtilities.resolve_items_or_notify`` — the
messaging helper that parses ``@<placement-hint>`` bindings,
invokes the data-layer resolver, dispatches user-facing
messages, and returns ``(Item, placement)`` pairs.

Covers:

- ``@`` binding splits the query into item-portion and hint.
- Hints resolve through the short vocabulary
  (``l`` / ``left`` / ``r`` / ``right`` / ``_``) and the
  ``(part, key)`` routing table (``head.helm``, ``cape``, etc.).
- Unknown hints dispatch an error and skip the query.
- No-match and ambiguity dispatch appropriate messages.
- Multi-query invocations: each query resolves independently,
  errors from one don't block the others.
"""

from unittest.mock import MagicMock, patch

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _player() -> Player:
    return Player(uid=1, gid=2, cid=3)


def _give(player: Player, plugin_name: str):
    item = Inventory.load_item(name=plugin_name)
    player.inventory.add(item)
    return item


class TestEquipMode:
    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_single_item_no_hint(self, mock_dispatch):
        p = _player()
        hat = _give(p, "mushroom_hat")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["mushroom"], mode="equip",
        )
        assert len(result) == 1
        item, placement = result[0]
        assert item is hat
        assert placement is None
        mock_dispatch.add.assert_not_called()

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_at_hint_binds_left(self, mock_dispatch):
        p = _player()
        sword = _give(p, "shortsword")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["shortsword@l"], mode="equip",
        )
        assert len(result) == 1
        item, placement = result[0]
        assert item is sword
        assert placement == EquipmentSlots.LEFT_SIDE

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_at_hint_full_placement(self, mock_dispatch):
        p = _player()
        hat = _give(p, "mushroom_hat")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["mushroom@head.worn"], mode="equip",
        )
        assert len(result) == 1
        item, placement = result[0]
        assert item is hat
        assert placement == EquipmentSlots.HEAD

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_at_hint_bare_key(self, mock_dispatch):
        """Phase D: ``outer`` key is shared between torso (cape)
        and head (bandanna/mask); bare-key hint ``@outer`` is
        ambiguous. Use the full ``torso.outer`` path instead —
        that's the unambiguous target for a cape."""
        p = _player()
        cape = _give(p, "cape")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["cape@torso.outer"], mode="equip",
        )
        assert len(result) == 1
        item, placement = result[0]
        assert item is cape
        assert placement == EquipmentSlots.CAPE

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_unknown_hint_dispatches_error_and_skips(self, mock_dispatch):
        """Invalid slot hint should surface a clear error and
        skip the query, not crash the whole command."""
        p = _player()
        _give(p, "shortsword")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["shortsword@bogus"], mode="equip",
        )
        assert result == []
        mock_dispatch.add.assert_called_once()
        _, msg = mock_dispatch.add.call_args.args
        assert "bogus" in msg

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_multi_query_partial_failure(self, mock_dispatch):
        """Multi-arg invocation: one bad query shouldn't block
        the others — each resolves independently."""
        p = _player()
        hat = _give(p, "mushroom_hat")
        cape = _give(p, "cape")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p,
            ["mushroom", "nonexistent", "cape"],
            mode="equip",
        )
        items = [i for i, _ in result]
        assert hat in items
        assert cape in items
        # One "no match" message dispatched.
        assert mock_dispatch.add.call_count == 1

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_dup_quality_collapses_to_first(self, mock_dispatch):
        """``$equip wand.fine`` with two fine wands renders both
        candidates to the same disambiguation label (``wand.fine``)
        — surfaces the first match instead of asking. 2026-04-29
        fix for Caels' "did you mean tee-shirt.ordinary,
        tee-shirt.ordinary?" report."""
        from caldanai.lib.rpg.inventory import Inventory

        p = _player()
        wand_a = Inventory.load_item(
            data={"plugin": "wand", "quality": "FINE"},
        )
        wand_b = Inventory.load_item(
            data={"plugin": "wand", "quality": "FINE"},
        )
        p.inventory.add(wand_a)
        p.inventory.add(wand_b)

        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["wand.fine"], mode="equip",
        )
        assert len(result) == 1
        item, _ = result[0]
        assert item is wand_a
        # No ambiguity dispatch — first-match resolution is silent.
        mock_dispatch.add.assert_not_called()


class TestStowMode:
    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_placement_key_resolves_equipped(self, mock_dispatch):
        """Phase D: bare key ``worn`` broadens to every worn
        placement; with only a helm equipped, it resolves to
        the helm."""
        p = _player()
        hat = _give(p, "mushroom_hat")
        p.equip(hat)
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["worn"], mode="stow",
        )
        assert len(result) == 1
        item, _ = result[0]
        assert item is hat


class TestSellMode:
    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_multiple_unequipped_returned(self, mock_dispatch):
        p = _player()
        _give(p, "wand")
        _give(p, "wand")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["wand"], mode="sell",
        )
        # Sell mode returns every unequipped match — no ambiguity
        # prompt, no dispatched messages.
        assert len(result) == 2
        mock_dispatch.add.assert_not_called()


class TestHintParsing:
    """Each short-vocabulary hint maps to a specific
    ``EquipmentSlots`` mask. Tested here directly so regressions
    in the reverse-lookup table surface cleanly."""

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_right_maps_to_right_side(self, mock_dispatch):
        p = _player()
        _give(p, "shortsword")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["shortsword@right"], mode="equip",
        )
        _, placement = result[0]
        assert placement == EquipmentSlots.RIGHT_SIDE

    @patch("caldanai.lib.rpg.helpers.utils.Dispatcher")
    def test_underscore_maps_to_none(self, mock_dispatch):
        """``_`` is the "wildcard — all slots" marker; historically
        it meant "equip everywhere the item fits." We model it as
        "no specific placement" so the equip call auto-routes."""
        p = _player()
        _give(p, "shortsword")
        channel = MagicMock()
        result = RpgUtilities.resolve_items_or_notify(
            channel, p, ["shortsword@_"], mode="equip",
        )
        _, placement = result[0]
        assert placement is None
