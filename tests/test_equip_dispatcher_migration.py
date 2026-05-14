"""Integration tests for ``$equip`` after the Step 4 fuzzy-resolve
dispatcher migration.

Step 4 of the project_fuzzy_resolution.md plan rewrites the
``$equip`` callback to route the per-term ``<item>[@<hint>]``
grammar through call-site ``@``-split parsing + two
``fuzzy_resolve`` calls (one against ``ItemConverter``, one
against ``EquipmentSlotConverter``). Per-term ambiguity surfacing
is preserved by re-querying the underlying
:meth:`Player.resolve_item_query` on a None dispatcher result —
the dispatcher's Optional contract collapses no-match and
ambiguity, but ``$equip`` still wants the "did you mean: ..." UX.

Existing ``RpgUtilities.resolve_items_or_notify`` tests
(``test_resolve_items_or_notify.py``) still cover the per-shape
slot-hint vocabulary; this file pins the end-to-end ``equip``
callback against a real :class:`Player` so the new
ItemConverter / EquipmentSlotConverter wiring stays sound.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_inventory_commands import RpgInventoryCommands
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _player() -> Player:
    return Player(uid=1, gid=2, cid=3)


def _give(player: Player, plugin_name: str, *, quality: str = None):
    data = {"plugin": plugin_name}
    if quality is not None:
        data["quality"] = quality
    item = Inventory.load_item(data=data)
    player.inventory.add(item)
    return item


def _make_game(player):
    g = MagicMock()
    g.monster = None
    g.channel = MagicMock()
    g.guild = MagicMock()
    g.player_manager = MagicMock()
    g.player_manager.players = {player.user_id: player}
    return g


def _make_ctx():
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = []
    return ctx


async def _invoke_equip(cog, game, player, *args):
    """Drive ``equip.callback`` with patched Dispatcher and
    RpgUtilities so the fuzzy-resolve dispatcher walk exercises a
    stubbed game state.

    Both ``get_game_and_player`` (entry-point) AND ``get_game`` are
    patched on RpgUtilities — ItemConverter.try_convert re-fetches
    the (game, player) pair during the dispatcher walk.
    """
    ctx = _make_ctx()
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    with (
        patch.object(
            RpgUtilities,
            "get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ),
        patch.object(
            RpgUtilities,
            "get_game",
            new=AsyncMock(return_value=game),
        ),
        patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher") as dispatcher,
    ):
        await cog.equip.callback(cog, ctx, *args)
        return dispatcher


def _dispatched_strings(dispatcher_mock):
    sent = []
    for call in dispatcher_mock.add.call_args_list:
        for arg in call.args[1:]:
            if isinstance(arg, str):
                sent.append(arg)
        for value in call.kwargs.values():
            if isinstance(value, str):
                sent.append(value)
    return sent


def _cog() -> RpgInventoryCommands:
    return RpgInventoryCommands(bot=MagicMock())


# ---------------------------------------------------------------------------
# @-split routing — the load-bearing change in Step 4. Each per-term
# ``<item>@<hint>`` parses out the item portion and the slot hint, runs
# each through fuzzy_resolve, and the call site decides what to do with
# the (item, slot) pair.
# ---------------------------------------------------------------------------


class TestAtSplitRouting:
    @pytest.mark.asyncio
    async def test_at_split_binds_left_hand(self):
        """``$equip shortsword@l`` parses ``shortsword`` as the
        item portion and ``l`` as the slot hint; the item ends up
        on the left hand."""
        cog = _cog()
        player = _player()
        sword = _give(player, "shortsword")
        game = _make_game(player)

        await _invoke_equip(cog, game, player, "shortsword@l")

        # Left arm should now hold the sword.
        held = player._iter_equipped_items()
        assert sword in held

    @pytest.mark.asyncio
    async def test_no_at_auto_resolves_slot(self):
        """``$equip <item>`` without ``@`` auto-resolves the slot
        per the existing default (the item lands at its first
        compatible empty placement)."""
        cog = _cog()
        player = _player()
        hat = _give(player, "mushroom_hat")
        game = _make_game(player)

        await _invoke_equip(cog, game, player, "mushroom")

        assert hat in player._iter_equipped_items()

    @pytest.mark.asyncio
    async def test_multiple_terms_no_at(self):
        """``$equip sword hat`` (no @s) processes both terms
        through the item resolver, each auto-resolving to its slot."""
        cog = _cog()
        player = _player()
        sword = _give(player, "shortsword")
        hat = _give(player, "mushroom_hat")
        game = _make_game(player)

        await _invoke_equip(cog, game, player, "shortsword", "mushroom")

        equipped = list(player._iter_equipped_items())
        assert sword in equipped
        assert hat in equipped

    @pytest.mark.asyncio
    async def test_mixed_at_and_no_at_terms(self):
        """``$equip <item>@<hint> <item>`` — first term routes
        through the explicit slot, second auto-resolves."""
        cog = _cog()
        player = _player()
        sword = _give(player, "shortsword")
        hat = _give(player, "mushroom_hat")
        game = _make_game(player)

        await _invoke_equip(cog, game, player, "shortsword@r", "mushroom")

        equipped = list(player._iter_equipped_items())
        assert sword in equipped
        assert hat in equipped


# ---------------------------------------------------------------------------
# Miss handling — preserved UX from the resolve_items_or_notify era.
# ---------------------------------------------------------------------------


class TestMissHandling:
    @pytest.mark.asyncio
    async def test_item_miss_no_at_emits_no_match_message(self):
        cog = _cog()
        player = _player()
        _give(player, "shortsword")
        game = _make_game(player)

        dispatcher = await _invoke_equip(cog, game, player, "nonsense_junk")

        sent = "\n".join(_dispatched_strings(dispatcher))
        assert "don't seem to have" in sent
        assert "nonsense_junk" in sent

    @pytest.mark.asyncio
    async def test_item_resolves_part_hint_unknown(self):
        """``$equip jerkin@nonsensepart`` — item resolves, part
        misses; preserve the "I don't know the slot" UX."""
        cog = _cog()
        player = _player()
        _give(player, "shortsword")
        game = _make_game(player)

        dispatcher = await _invoke_equip(
            cog, game, player, "shortsword@nonsensepart",
        )

        sent = "\n".join(_dispatched_strings(dispatcher))
        assert "don't know the slot" in sent
        assert "nonsensepart" in sent

    @pytest.mark.asyncio
    async def test_partial_failure_doesnt_block_other_terms(self):
        """Mixed success / failure across terms: the success lands,
        the failure emits its own message."""
        cog = _cog()
        player = _player()
        hat = _give(player, "mushroom_hat")
        game = _make_game(player)

        dispatcher = await _invoke_equip(
            cog, game, player, "mushroom", "nonsense_junk",
        )

        assert hat in player._iter_equipped_items()
        sent = "\n".join(_dispatched_strings(dispatcher))
        assert "nonsense_junk" in sent


# ---------------------------------------------------------------------------
# Ambiguity surfacing — preserved by re-querying the underlying
# resolver when the dispatcher returns None. The dispatcher's
# Optional contract collapses no-match and ambiguity into one None;
# $equip's UX wants the candidate list when one exists.
# ---------------------------------------------------------------------------


class TestAmbiguitySurfacing:
    @pytest.mark.asyncio
    async def test_ambiguous_query_surfaces_candidates(self):
        """``$equip leather.fine`` against three differently-named
        leather items collapses to >1 distinct ambiguity labels —
        the resolver returns no items but populates
        ``ambiguity_candidates``. The dispatcher's Optional contract
        collapses ambiguity and no-match into one ``None``; the
        call-site re-query path is what reconstructs the
        distinction and surfaces the candidate list. Regression
        pin against accidental removal of the re-query block."""
        cog = _cog()
        player = _player()
        _give(player, "leather_glove", quality="FINE")
        _give(player, "leather_cap", quality="FINE")
        _give(player, "leather_boot", quality="FINE")
        game = _make_game(player)

        dispatcher = await _invoke_equip(
            cog, game, player, "leather.fine",
        )

        sent = "\n".join(_dispatched_strings(dispatcher))
        assert "did you mean" in sent.lower()
        # Each ambiguity candidate label should appear.
        assert "leather glove" in sent
        assert "leather cap" in sent
        assert "leather boot" in sent

    @pytest.mark.asyncio
    async def test_pure_no_match_does_not_surface_candidates(self):
        """Inverse: a no-match query with NO ambiguity candidates
        emits the "don't seem to have" wording, NOT "did you mean."
        Pairs with the test above to pin the re-query's branch
        selection."""
        cog = _cog()
        player = _player()
        _give(player, "shortsword")
        game = _make_game(player)

        dispatcher = await _invoke_equip(cog, game, player, "nonsense_xyz")

        sent = "\n".join(_dispatched_strings(dispatcher))
        assert "did you mean" not in sent.lower()
        assert "don't seem to have" in sent


# ---------------------------------------------------------------------------
# Legacy 2-arg trailing-hint form still rewrites to the canonical
# ``<item>@<hint>``.
# ---------------------------------------------------------------------------


class TestLegacyTrailingHint:
    @pytest.mark.asyncio
    async def test_legacy_2arg_form_routes_through_at_split(self):
        """``$equip sword left`` rewrites to ``$equip sword@left``
        — back-compat for the pre-binding-syntax UX."""
        cog = _cog()
        player = _player()
        sword = _give(player, "shortsword")
        game = _make_game(player)

        await _invoke_equip(cog, game, player, "shortsword", "left")

        assert sword in player._iter_equipped_items()
