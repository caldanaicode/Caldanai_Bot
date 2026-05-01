"""Tests for ``$sell duplicates [n]`` — the bulk-clear-extras
flow. Exercises the cog helper directly with a real ``Player`` +
``Inventory`` so the keep-N math hits real ``item.plugin``
grouping. 2026-04-29 feature for Caels' QoL ask."""

from unittest.mock import MagicMock, patch

import pytest

from bson.objectid import ObjectId

from caldanai.lib.cogs.rpg_inventory_commands import RpgInventoryCommands
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment import Equipment


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
    member.display_name = "TestPlayer"
    p.member = member
    p.name = "TestPlayer"
    return p


def _equip(name, plugin, quality, slots=EquipmentSlots.EITHER_HELD):
    return Equipment(
        iid=ObjectId(),
        name=name,
        slots=slots,
        unit_weight=0.5,
        unit_value=10,
        quality=quality,
        plugin=plugin,
    )


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_keep_one_default(mock_dispatch):
    """Default ``$sell duplicates`` keeps the best one of each
    plugin, sells the rest. Three wands of varying quality →
    keep masterwork, sell superior + ordinary."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    junk = _equip("junk wand", "wand", Qualities.JUNK)
    superior = _equip("superior wand", "wand", Qualities.SUPERIOR)
    masterwork = _equip("masterwork wand", "wand", Qualities.MASTERWORK)
    p.inventory.add(junk)
    p.inventory.add(superior)
    p.inventory.add(masterwork)

    await cog._sell_duplicates(MagicMock(), p, keep=1)

    remaining = list(p.inventory.all())
    assert masterwork in remaining
    assert superior not in remaining
    assert junk not in remaining


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_keep_two_dual_wield_safe(mock_dispatch):
    """``$sell duplicates 2`` keeps the best two of each plugin
    — covers the dual-wield case (Serena's bow incident). With
    three shortswords, keep masterwork + superior, sell ordinary."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    ordinary = _equip("ordinary shortsword", "shortsword", Qualities.ORDINARY)
    superior = _equip("superior shortsword", "shortsword", Qualities.SUPERIOR)
    masterwork = _equip("masterwork shortsword", "shortsword", Qualities.MASTERWORK)
    p.inventory.add(ordinary)
    p.inventory.add(superior)
    p.inventory.add(masterwork)

    await cog._sell_duplicates(MagicMock(), p, keep=2)

    remaining = list(p.inventory.all())
    assert masterwork in remaining
    assert superior in remaining
    assert ordinary not in remaining


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_favorited_excluded_from_pool(mock_dispatch):
    """Favorited items aren't candidates for the duplicates sweep
    — the favoriting system is the user's "hands off" signal,
    independent of the keep-N rule."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    junk_fav = _equip("junk wand", "wand", Qualities.JUNK)
    junk_fav.favorited = True
    masterwork = _equip("masterwork wand", "wand", Qualities.MASTERWORK)
    superior = _equip("superior wand", "wand", Qualities.SUPERIOR)
    p.inventory.add(junk_fav)
    p.inventory.add(masterwork)
    p.inventory.add(superior)

    # keep=1 → keep best non-favorited (masterwork), sell superior.
    # The favorited junk stays untouched.
    await cog._sell_duplicates(MagicMock(), p, keep=1)

    remaining = list(p.inventory.all())
    assert junk_fav in remaining   # favorited — protected
    assert masterwork in remaining # best non-fav, kept
    assert superior not in remaining


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_equipped_excluded_from_pool(mock_dispatch):
    """Equipped items aren't candidates either — same protection
    as every other sell path."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    worn = _equip("ordinary wand", "wand", Qualities.ORDINARY)
    inv_fine = _equip("fine wand", "wand", Qualities.FINE)
    inv_quality = _equip("quality wand", "wand", Qualities.QUALITY)
    p.inventory.add(worn)
    p.inventory.add(inv_fine)
    p.inventory.add(inv_quality)
    p.equip(worn)

    # keep=1 → keep best non-equipped (quality, mult 1.5), sell
    # fine (mult 1.25). Worn ordinary protected even though it's
    # the worst-quality.
    await cog._sell_duplicates(MagicMock(), p, keep=1)

    remaining = list(p.inventory.all())
    assert worn in remaining        # equipped — protected
    assert inv_quality in remaining # best inv, kept
    assert inv_fine not in remaining


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_no_duplicates_silent_message(mock_dispatch):
    """When nothing meets the duplicate criteria, surface a
    friendly "no duplicates to sell" line instead of an empty
    receipt."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    only = _equip("masterwork wand", "wand", Qualities.MASTERWORK)
    p.inventory.add(only)

    channel = MagicMock()
    await cog._sell_duplicates(channel, p, keep=1)

    remaining = list(p.inventory.all())
    assert only in remaining
    mock_dispatch.add.assert_called_once()
    args = mock_dispatch.add.call_args.args
    assert "no duplicates" in args[1].lower()


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_shared_object_ids_dont_silently_fail(mock_dispatch):
    """Shield regression: when inventory contains multiple items
    that share one ``_id`` (e.g. seeded by a pre-fix doppy-clone
    harvest), ``$sell duplicates`` must still sell all duplicates
    via identity lookup, not the prior first-match-by-id path
    that silently failed siblings 2+N. 2026-04-29 fix."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    shared_id = ObjectId()
    a = Equipment(
        iid=shared_id, name="bandanna",
        slots=EquipmentSlots.FACE,
        unit_weight=0.2, unit_value=1, quality=Qualities.QUALITY,
        plugin="bandanna",
    )
    b = Equipment(
        iid=shared_id, name="bandanna",
        slots=EquipmentSlots.FACE,
        unit_weight=0.2, unit_value=1, quality=Qualities.QUALITY,
        plugin="bandanna",
    )
    c = Equipment(
        iid=shared_id, name="bandanna",
        slots=EquipmentSlots.FACE,
        unit_weight=0.2, unit_value=1, quality=Qualities.QUALITY,
        plugin="bandanna",
    )
    p.inventory.add(a)
    p.inventory.add(b)
    p.inventory.add(c)

    # All three carry the same ``_id``, but are distinct
    # instances — keep=1 should sell two of them.
    await cog._sell_duplicates(MagicMock(), p, keep=1)

    remaining = list(p.inventory.all())
    # Exactly one should remain (the kept best — first in the
    # quality-tied sort).
    assert len(remaining) == 1
    # And the remaining one is the FIRST-inserted (sort is stable
    # on ties; iteration order reflects insertion).
    assert remaining[0] is a


@pytest.mark.asyncio
@patch("caldanai.lib.cogs.rpg_inventory_commands.Dispatcher")
async def test_per_plugin_grouping(mock_dispatch):
    """Each unique ``item.plugin`` gets its own keep-N tally —
    five wands and three shortswords with keep=1 yields 4 wand
    sales + 2 shortsword sales (keep best of each group)."""
    cog = RpgInventoryCommands(bot=MagicMock())
    p = _player()
    # 5 wands varying quality
    w_master = _equip("masterwork wand", "wand", Qualities.MASTERWORK)
    w_superior = _equip("superior wand", "wand", Qualities.SUPERIOR)
    w_fine = _equip("fine wand", "wand", Qualities.FINE)
    w_quality = _equip("quality wand", "wand", Qualities.QUALITY)
    w_junk = _equip("junk wand", "wand", Qualities.JUNK)
    # 3 shortswords
    s_master = _equip("masterwork shortsword", "shortsword", Qualities.MASTERWORK)
    s_fine = _equip("fine shortsword", "shortsword", Qualities.FINE)
    s_junk = _equip("junk shortsword", "shortsword", Qualities.JUNK)
    for it in (w_master, w_superior, w_fine, w_quality, w_junk,
               s_master, s_fine, s_junk):
        p.inventory.add(it)

    await cog._sell_duplicates(MagicMock(), p, keep=1)

    remaining = list(p.inventory.all())
    # Best of each plugin survived.
    assert w_master in remaining
    assert s_master in remaining
    # Everything else gone.
    for sold in (w_superior, w_fine, w_quality, w_junk, s_fine, s_junk):
        assert sold not in remaining
