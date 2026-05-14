"""Regression tests for three $sell / $feed bugs surfaced
2026-05-13.

- Bug 1: ``$sell tee-shirt`` (hyphenated name) and ``$sell
  <category>`` (silent-fail path when one matched item is
  worn) — name with ``-`` must NOT be treated as a numeric
  range, and category-iterator failures must surface to the
  player instead of being swallowed.
- Bug 2: ``$sell <indices>`` equipped-check was matching by
  name not identity — three same-named tee-shirts with index
  46 worn refused to sell 44 + 45 with two identical "must
  un-equip" lines. Fix uses identity/index-based equip-check.
- Bug 3: ``$feed`` must skip ★-favorited fuel items so a
  masterwork stick doesn't get fed to an idle campfire.
"""

from unittest.mock import MagicMock, patch

import pytest

from bson.objectid import ObjectId

from caldanai.lib.cogs.rpg_inventory_commands import RpgInventoryCommands
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment import Equipment
from caldanai.lib.rpg.world.objects.campfire import Campfire, FireState


def _player():
    p = Player(
        pid=ObjectId(),
        gid=100,
        uid=200,
        health=20,
        health_max=20,
        defense=6,
        dodge=6,
        gender="male",
        pronouns="he,him,his,his",
        weight_limit=10000,
        clarks=0,
    )
    member = MagicMock()
    member.id = 200
    member.display_name = "alice"
    p.member = member
    p.name = "alice"
    return p


def _shirt(quality=Qualities.JUNK):
    return Equipment(
        iid=ObjectId(),
        name="tee-shirt",
        slots=EquipmentSlots.TORSO,
        unit_weight=0.6,
        unit_value=4,
        quality=quality,
        plugin="tee_shirt",
    )


def _stick(quality=Qualities.ORDINARY):
    return Equipment(
        iid=ObjectId(),
        name="stick",
        slots=EquipmentSlots.EITHER_HELD,
        unit_weight=0.3,
        unit_value=1,
        quality=quality,
        plugin="stick",
    )


# ---------------------------------------------------------------------------
# Bug 1 — $sell tee-shirt and $sell junk paths
# ---------------------------------------------------------------------------


class TestSellHyphenatedName:
    """``$sell tee-shirt`` must NOT split the hyphen as a numeric
    range. The regex gate at the call site already enforces this,
    but pin it with a behavior test so the gate can't quietly
    regress."""

    @pytest.mark.asyncio
    @patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
    async def test_sell_hyphenated_name_sells(self, mock_dispatch):
        # ``split_message`` is consumed by ``for m in msgs:`` — give it
        # a real iterable so the receipt loop actually fires.
        mock_dispatch.split_message.side_effect = lambda text, *_a, **_kw: [text]
        cog = RpgInventoryCommands(bot=MagicMock())
        p = _player()
        shirt = _shirt()
        p.inventory.add(shirt)

        ctx = MagicMock()
        ctx.guild = MagicMock()
        with patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.get_game_and_player",
            return_value=(MagicMock(), p),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.resolve_reply_channel",
            return_value=MagicMock(),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.dead_invoker_guard",
            return_value=False,
        ):
            await cog.sell.callback(cog, ctx, "tee-shirt")

        # Item should be gone from inventory — sold cleanly.
        assert shirt not in list(p.inventory.all())
        # No "Index range invalid" / "Unable to determine ..." line
        # in any dispatcher message.
        all_calls = [
            str(c) for c in mock_dispatch.add.call_args_list
        ]
        joined = " ".join(all_calls).lower()
        assert "range invalid" not in joined
        assert "unable to determine" not in joined

    @pytest.mark.asyncio
    @patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
    async def test_sell_surfaces_player_sell_failure(self, mock_dispatch):
        """When ``player.sell`` returns a failure tuple (e.g. the
        item vanished mid-loop), the receipt must surface a
        per-item "Failed to sell ..." line — NOT drop it silently.
        Patched player.sell makes the failure deterministic."""
        mock_dispatch.split_message.side_effect = lambda text, *_a, **_kw: [text]
        cog = RpgInventoryCommands(bot=MagicMock())
        p = _player()
        shirt = _shirt()
        p.inventory.add(shirt)

        ctx = MagicMock()
        ctx.guild = MagicMock()
        with patch.object(
            p, "sell", return_value=("Item not found", 0),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.get_game_and_player",
            return_value=(MagicMock(), p),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.resolve_reply_channel",
            return_value=MagicMock(),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.dead_invoker_guard",
            return_value=False,
        ):
            await cog.sell.callback(cog, ctx, "tee-shirt")

        joined = " ".join(
            str(c) for c in mock_dispatch.add.call_args_list
        ).lower()
        assert "failed to sell" in joined

    @pytest.mark.asyncio
    @patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
    async def test_sell_category_with_one_worn_surfaces_skip(self, mock_dispatch):
        """``$sell junk`` with three junk items where one is worn:
        the two unequipped sell, the worn one becomes an equipped-
        skipped line on the receipt. NOT silent."""
        mock_dispatch.split_message.side_effect = lambda text, *_a, **_kw: [text]
        cog = RpgInventoryCommands(bot=MagicMock())
        p = _player()
        a = _shirt()
        b = _shirt()
        worn = _shirt()
        p.inventory.add(a)
        p.inventory.add(b)
        p.inventory.add(worn)
        p.equip(worn)

        ctx = MagicMock()
        ctx.guild = MagicMock()
        with patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.get_game_and_player",
            return_value=(MagicMock(), p),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.resolve_reply_channel",
            return_value=MagicMock(),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.dead_invoker_guard",
            return_value=False,
        ):
            await cog.sell.callback(cog, ctx, "junk")

        remaining = list(p.inventory.all())
        # Worn shirt protected; two unequipped junks sold.
        assert worn in remaining
        assert a not in remaining
        assert b not in remaining
        # Receipt mentions "skipped (equipped" so the player knows
        # why their category-sweep didn't drain everything.
        all_text = " ".join(
            str(c) for c in mock_dispatch.add.call_args_list
        ).lower()
        assert "equipped" in all_text or "skipped" in all_text


# ---------------------------------------------------------------------------
# Bug 2 — $sell <indices> equip-check is identity-based, not name-based
# ---------------------------------------------------------------------------


class TestSellIndicesEquipCheck:
    """``$sell 1 2`` with three same-named items where ONLY #3 is
    worn must sell #1 and #2 — the equip-check is per-item, not
    per-name."""

    @pytest.mark.asyncio
    @patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
    async def test_sell_two_indices_skips_only_worn(self, mock_dispatch):
        mock_dispatch.split_message.side_effect = lambda text, *_a, **_kw: [text]
        cog = RpgInventoryCommands(bot=MagicMock())
        p = _player()
        a = _shirt()
        b = _shirt()
        worn = _shirt()
        p.inventory.add(a)
        p.inventory.add(b)
        p.inventory.add(worn)
        p.equip(worn)

        # Find the inventory indices (1-based) of a and b.
        all_items = list(p.inventory.all())
        idx_a = all_items.index(a) + 1
        idx_b = all_items.index(b) + 1

        ctx = MagicMock()
        ctx.guild = MagicMock()
        with patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.get_game_and_player",
            return_value=(MagicMock(), p),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.resolve_reply_channel",
            return_value=MagicMock(),
        ), patch(
            "caldanai.lib.cogs.rpg_inventory_commands.RpgUtilities.dead_invoker_guard",
            return_value=False,
        ):
            await cog.sell.callback(cog, ctx, idx_a, idx_b)

        remaining = list(p.inventory.all())
        # Worn shirt stays; unequipped indices sold.
        assert worn in remaining
        assert a not in remaining
        assert b not in remaining
        # No "must un-equip" line should fire — the equip-check is
        # identity-based, so a/b are independent of worn.
        joined = " ".join(
            str(c) for c in mock_dispatch.add.call_args_list
        ).lower()
        assert "un-equip" not in joined and "unequip" not in joined


# ---------------------------------------------------------------------------
# Bug 3 — $feed must respect favorited items
# ---------------------------------------------------------------------------


class TestFeedRespectsFavorites:
    """``$feed campfire`` (implicit fuel pick) and ``$feed campfire
    stick`` (explicit name) must both skip ★-favorited fuel items.
    Mirrors the favorited-skip protection that exists in $sell."""

    def test_feed_implicit_skips_favorited_stick(self):
        cf = Campfire()
        cf.state["fire"] = FireState.LIT
        cf.state["fuel"] = 10

        actor = MagicMock(name="player")
        actor.name = "alice"
        actor.uses_article = False
        fav = _stick(quality=Qualities.MASTERWORK)
        fav.favorited = True
        plain = _stick(quality=Qualities.ORDINARY)
        # Real-shape inventory stub: ``all()`` returns the tuple.
        actor.inventory = MagicMock(spec=["all"])
        actor.inventory.all = MagicMock(return_value=(fav, plain))
        actor.is_equipped = MagicMock(return_value=False)
        actor.take_item = MagicMock(side_effect=lambda i: i)

        cf.on_verb("feed", MagicMock(), actor, fuel_arg=None)

        # The favorited masterwork stick must NOT be the one
        # consumed. Implicit-feed should fall through to the plain
        # one.
        actor.take_item.assert_called_once_with(plain)

    def test_feed_explicit_skips_favorited_stick(self):
        cf = Campfire()
        cf.state["fire"] = FireState.LIT
        cf.state["fuel"] = 10

        actor = MagicMock(name="player")
        actor.name = "alice"
        actor.uses_article = False
        fav = _stick(quality=Qualities.MASTERWORK)
        fav.favorited = True
        plain = _stick(quality=Qualities.ORDINARY)
        actor.inventory = MagicMock(spec=["all"])
        actor.inventory.all = MagicMock(return_value=(fav, plain))
        actor.is_equipped = MagicMock(return_value=False)
        actor.take_item = MagicMock(side_effect=lambda i: i)

        cf.on_verb("feed", MagicMock(), actor, fuel_arg="stick")

        actor.take_item.assert_called_once_with(plain)

    def test_feed_only_favorited_stick_reports_no_fuel(self):
        """If every fuel candidate is favorited, $feed should
        report "no fuel" rather than silently eating one."""
        cf = Campfire()
        cf.state["fire"] = FireState.LIT
        cf.state["fuel"] = 10

        actor = MagicMock(name="player")
        actor.name = "alice"
        actor.uses_article = False
        fav = _stick(quality=Qualities.MASTERWORK)
        fav.favorited = True
        actor.inventory = MagicMock(spec=["all"])
        actor.inventory.all = MagicMock(return_value=(fav,))
        actor.is_equipped = MagicMock(return_value=False)
        actor.take_item = MagicMock()

        line = cf.on_verb("feed", MagicMock(), actor, fuel_arg=None)

        actor.take_item.assert_not_called()
        assert line is not None
        # Standard "nothing fuel-shaped" message wording.
        assert "fuel-shaped" in line.lower() or "no" in line.lower()
