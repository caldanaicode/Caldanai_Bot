"""Tests for caldanai.lib.rpg.player_manager.PlayerManager class."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.rpg.helpers.enums import Roles
from caldanai.lib.rpg.player_manager import PlayerManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_player(uid=111, gid=999, is_dirty=False):
    """Create a lightweight mock Player."""
    player = MagicMock()
    player.user_id = uid
    player.guild_id = gid
    player.is_dirty = is_dirty
    player.last_active = datetime.now()
    player.name = "TestPlayer"
    player.member = MagicMock()
    player.member.roles = []
    player.member.add_roles = AsyncMock()
    player.member.remove_roles = AsyncMock()
    player.member.display_name = "TestPlayer"
    return player


def _setup_roles(pm):
    """Populate the PlayerManager's roles dict with mock Role objects."""
    for role_enum in Roles:
        mock_role = MagicMock()
        mock_role.name = role_enum.value
        pm.roles[role_enum] = mock_role


# ---------------------------------------------------------------------------
# add_player / remove_player
# ---------------------------------------------------------------------------

class TestAddRemovePlayer:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.DB")
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    async def test_add_player_success(self, mock_utils, mock_db, mock_ctx):
        pm = PlayerManager()
        _setup_roles(pm)
        # Use a MagicMock instead of a real set because Player objects are
        # not hashable, so set.add(player) would raise TypeError.
        mock_utils.new_players = MagicMock()

        result = await pm.add_player(mock_ctx)
        assert result is True
        # The new player's member should have received ALL and ACTIVE roles
        mock_ctx.author.add_roles.assert_awaited_once_with(
            pm.roles[Roles.ALL], pm.roles[Roles.ACTIVE], reason="Player joined game."
        )

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.DB")
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    async def test_add_player_already_exists(self, mock_utils, mock_db, mock_ctx):
        pm = PlayerManager()
        _setup_roles(pm)
        # Use a MagicMock instead of a real set because Player objects are
        # not hashable, so set.add(player) would raise TypeError.
        mock_utils.new_players = MagicMock()

        # First add succeeds
        await pm.add_player(mock_ctx)
        # Second add for same user should return False
        # We need to manually add the user_id to pm.players since the first call
        # creates a real Player with ctx.author.id
        pm.players[mock_ctx.author.id] = _make_player(uid=mock_ctx.author.id)
        result = await pm.add_player(mock_ctx)
        assert result is False

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_remove_player(self, mock_db, mock_guild):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player(uid=42, gid=mock_guild.id)
        pm.players[42] = player

        await pm.remove_player(42, mock_guild.id, channel_id=888)
        assert 42 not in pm.players
        mock_db.delete_player.assert_called_once_with(mock_guild.id, 888, 42)

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_remove_player_not_present(self, mock_db, mock_guild):
        pm = PlayerManager()
        await pm.remove_player(999, mock_guild.id, channel_id=888)
        mock_db.delete_player.assert_called_once_with(mock_guild.id, 888, 999)


# ---------------------------------------------------------------------------
# get_player
# ---------------------------------------------------------------------------

class TestGetPlayer:
    @pytest.mark.asyncio
    async def test_get_player_from_context(self, mock_ctx):
        from discord.ext.commands import Context

        pm = PlayerManager()
        player = _make_player(uid=mock_ctx.author.id)
        pm.players[mock_ctx.author.id] = player

        # mock_ctx is a MagicMock, so isinstance(ctx, Context) will be False.
        # We need to make it pass the isinstance check.
        mock_ctx.__class__ = Context
        result = await pm.get_player(mock_ctx)
        assert result is player

    @pytest.mark.asyncio
    async def test_get_player_not_found(self, mock_ctx):
        from discord.ext.commands import Context

        pm = PlayerManager()
        mock_ctx.__class__ = Context
        result = await pm.get_player(mock_ctx)
        assert result is None


# ---------------------------------------------------------------------------
# set_player_active / set_player_inactive
# ---------------------------------------------------------------------------

class TestPlayerActiveInactive:
    @pytest.mark.asyncio
    async def test_set_player_active_removes_inactive_role(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        # Simulate the player having the INACTIVE role
        player.member.roles = [pm.roles[Roles.INACTIVE]]

        await pm.set_player_active(player)
        player.member.remove_roles.assert_awaited_once_with(
            pm.roles[Roles.INACTIVE], reason="Activity in game."
        )
        assert player.is_dirty is True

    @pytest.mark.asyncio
    async def test_set_player_active_adds_active_role(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        # Player has no roles — should receive ACTIVE
        player.member.roles = []

        await pm.set_player_active(player)
        player.member.add_roles.assert_awaited_once_with(
            pm.roles[Roles.ACTIVE], reason="Activity in game."
        )

    @pytest.mark.asyncio
    async def test_set_player_inactive_removes_active_adds_inactive(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        # Player currently has ACTIVE role
        player.member.roles = [pm.roles[Roles.ACTIVE]]

        await pm.set_player_inactive(player)
        player.member.remove_roles.assert_awaited_once_with(
            pm.roles[Roles.ACTIVE], reason="No activity in game for at least 24 hours."
        )
        player.member.add_roles.assert_awaited_once_with(
            pm.roles[Roles.INACTIVE], reason="No activity in game for at least 24 hours."
        )

    @pytest.mark.asyncio
    async def test_set_player_inactive_no_op_when_already_inactive(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        # Player already has INACTIVE role and no ACTIVE role
        player.member.roles = [pm.roles[Roles.INACTIVE]]

        await pm.set_player_inactive(player)
        player.member.remove_roles.assert_not_awaited()
        player.member.add_roles.assert_not_awaited()


# ---------------------------------------------------------------------------
# combat role management
# ---------------------------------------------------------------------------

class TestCombatantRoles:
    @pytest.mark.asyncio
    async def test_set_combatant_adds_role(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        player.member.roles = []

        await pm.set_player_combatant(player)
        player.member.add_roles.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_combatant_skips_if_already_has_role(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        player.member.roles = [pm.roles[Roles.COMBAT_MAIN]]

        await pm.set_player_combatant(player)
        player.member.add_roles.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_clear_combatant_removes_role(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        player.member.roles = [pm.roles[Roles.COMBAT_MAIN]]

        await pm.clear_player_combatant(player, "Combat over.")
        player.member.remove_roles.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_combatant_skips_if_no_role(self):
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        player.member.roles = []

        await pm.clear_player_combatant(player, "Combat over.")
        player.member.remove_roles.assert_not_awaited()
