"""Tests for caldanai.lib.rpg.player_manager.PlayerManager class."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import discord
from discord.errors import NotFound

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
    async def test_add_player_registers_in_live_players_dict(
        self, mock_utils, mock_db, mock_ctx,
    ):
        """Regression: fresh $game join used to succeed (``Welcome,
        …`` + role assignment) but never register the player in
        ``self.players``. Downstream commands consulting the live
        registry — ``get_player`` in the cog helpers, any command
        that routes through ``get_game_and_player`` — then treated
        the joiner as "not even playing the game". The DB-side
        deferred-insert set (``RpgUtilities.new_players``) is not a
        substitute for the live dict; it only backfills the _id
        field after the first persistence round-trip. Reported
        live by Serena on TEST 2026-04-19."""
        pm = PlayerManager()
        _setup_roles(pm)
        mock_utils.new_players = MagicMock()

        assert mock_ctx.author.id not in pm.players

        result = await pm.add_player(mock_ctx)

        assert result is True
        # The player must be immediately visible in the live registry
        # — no bot restart required, no DB round-trip required.
        assert mock_ctx.author.id in pm.players
        registered = pm.players[mock_ctx.author.id]
        assert registered.user_id == mock_ctx.author.id

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.DB")
    @patch("caldanai.lib.rpg.helpers.utils.RpgUtilities")
    async def test_add_player_already_exists(self, mock_utils, mock_db, mock_ctx):
        pm = PlayerManager()
        _setup_roles(pm)
        # Use a MagicMock instead of a real set because Player objects are
        # not hashable, so set.add(player) would raise TypeError.
        mock_utils.new_players = MagicMock()

        # First add registers into ``pm.players`` (post-fix — previously
        # this required a manual workaround here because add_player
        # forgot to register, and the second call would otherwise
        # succeed again).
        first = await pm.add_player(mock_ctx)
        assert first is True
        # Second add for the same user short-circuits on the
        # ``ctx.author.id not in self.players`` guard and returns False.
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
# maybe_update_member_name (display-name sync hook)
# ---------------------------------------------------------------------------


class TestMaybeUpdateMemberName:
    """Pin the display-name sync helper wired into the
    ``on_member_update`` cog listener. Without this, a player who
    changes their guild nickname / global name still gets narrated
    under their original name until the next bot restart
    rehydrates from Mongo."""

    def _member(self, uid=42, display_name="Alice"):
        m = MagicMock()
        m.id = uid
        m.display_name = display_name
        return m

    def test_updates_name_when_display_name_changed(self):
        pm = PlayerManager()
        player = _make_player(uid=42)
        player.name = "OldName"
        player.is_dirty = False
        pm.players[42] = player

        updated = pm.maybe_update_member_name(self._member(42, "NewName"))

        assert updated is True
        assert player.name == "NewName"
        assert player.is_dirty is True

    def test_noop_when_name_unchanged(self):
        pm = PlayerManager()
        player = _make_player(uid=42)
        player.name = "Steady"
        player.is_dirty = False
        pm.players[42] = player

        updated = pm.maybe_update_member_name(self._member(42, "Steady"))

        assert updated is False
        assert player.is_dirty is False

    def test_noop_when_member_not_in_this_game(self):
        """A member update for someone who isn't a player here must
        not mutate unrelated players."""
        pm = PlayerManager()
        player = _make_player(uid=42)
        player.name = "OnlyPlayer"
        player.is_dirty = False
        pm.players[42] = player

        # Different member id — stranger.
        updated = pm.maybe_update_member_name(self._member(999, "Visitor"))

        assert updated is False
        assert player.name == "OnlyPlayer"
        assert player.is_dirty is False

    def test_refreshes_member_reference(self):
        """The new ``Member`` object replaces the old one on the
        player — stale member refs (e.g. cached from a pre-
        nickname-change state) would produce cursed output later."""
        pm = PlayerManager()
        player = _make_player(uid=42)
        old_member = player.member
        pm.players[42] = player

        new_member = self._member(42, "Fresh")
        pm.maybe_update_member_name(new_member)

        assert player.member is new_member
        assert player.member is not old_member


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
    async def test_clear_combatant_fires_unconditionally(self):
        """remove_roles is called even when the cache says the player
        doesn't have the role — the cached role list can be stale after
        reconnects, and Discord is idempotent about redundant removals."""
        pm = PlayerManager()
        _setup_roles(pm)
        player = _make_player()
        player.member.roles = []

        await pm.clear_player_combatant(player, "Combat over.")
        player.member.remove_roles.assert_awaited_once()


# ---------------------------------------------------------------------------
# load_players
# ---------------------------------------------------------------------------

def _player_doc(uid, gid=123456789):
    """A stub DB row — ``Player.from_dict`` is patched in these tests,
    so only ``user_id`` is actually read by ``load_players`` itself."""
    return {"user_id": uid, "guild_id": gid}


def _stub_player():
    """Build a stand-in Player so from_dict can return something the
    load loop can bind ``.member`` / ``.name`` / ``.channel_id`` onto
    without dragging in the whole Player schema."""
    return MagicMock(channel_id=None, member=None, name=None)


class TestLoadPlayers:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Player")
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_chunk_warms_cache_and_no_per_player_fetch(self, mock_db, mock_player_cls, mock_guild):
        """The common path: members intent is on, so ``guild.chunk()``
        populates every member at once and ``fetch_member`` is never
        called."""
        pm = PlayerManager()
        ids = [101, 202, 303]
        mock_db.find_players_by_game.return_value = [_player_doc(u) for u in ids]
        mock_player_cls.from_dict.side_effect = lambda _p: _stub_player()

        members = {u: MagicMock(display_name=f"user{u}") for u in ids}
        mock_guild.chunked = False  # auto-chunk didn't complete; we should chunk
        mock_guild.chunk = AsyncMock()
        mock_guild.get_member = MagicMock(side_effect=lambda uid: members.get(uid))

        await pm.load_players(mock_guild, channel_id=888)

        mock_guild.chunk.assert_awaited_once()
        mock_guild.fetch_member.assert_not_awaited()
        assert set(pm.players.keys()) == set(ids)
        for uid in ids:
            assert pm.players[uid].member is members[uid]

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Player")
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_chunk_skipped_when_guild_already_chunked(self, mock_db, mock_player_cls, mock_guild):
        """discord.py auto-chunks at startup with the members intent
        enabled. When ``guild.chunked`` is already True by the time
        we call ``load_players``, our explicit ``chunk()`` call must
        be skipped — calling it again during ``on_ready`` processing
        can deadlock the gateway."""
        pm = PlayerManager()
        ids = [101, 202]
        mock_db.find_players_by_game.return_value = [_player_doc(u) for u in ids]
        mock_player_cls.from_dict.side_effect = lambda _p: _stub_player()

        members = {u: MagicMock(display_name=f"user{u}") for u in ids}
        mock_guild.chunked = True  # auto-chunk already populated the cache
        mock_guild.chunk = AsyncMock()
        mock_guild.get_member = MagicMock(side_effect=lambda uid: members.get(uid))

        await pm.load_players(mock_guild, channel_id=888)

        mock_guild.chunk.assert_not_awaited()
        mock_guild.fetch_member.assert_not_awaited()
        assert set(pm.players.keys()) == set(ids)

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_chunk_skipped_when_no_players(self, mock_db, mock_guild):
        """No DB rows means no work to do — chunk should not fire."""
        pm = PlayerManager()
        mock_db.find_players_by_game.return_value = []
        mock_guild.chunked = False
        mock_guild.chunk = AsyncMock()

        await pm.load_players(mock_guild, channel_id=888)

        mock_guild.chunk.assert_not_awaited()
        assert pm.players == {}

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Player")
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_chunk_failure_falls_back_to_fetch_member(self, mock_db, mock_player_cls, mock_guild):
        """If ``chunk`` blows up, the per-player ``fetch_member`` fallback
        must still load members the gateway did deliver."""
        pm = PlayerManager()
        mock_db.find_players_by_game.return_value = [_player_doc(777)]
        mock_player_cls.from_dict.side_effect = lambda _p: _stub_player()

        # ClientException is the realistic chunk() failure — discord.py raises it
        # when the members intent is off. Generic RuntimeError would also be caught
        # by the broad except, but this keeps the test faithful to the real failure.
        mock_guild.chunked = False
        mock_guild.chunk = AsyncMock(
            side_effect=discord.ClientException("Intents.members must be enabled")
        )
        mock_guild.get_member = MagicMock(return_value=None)
        fetched = MagicMock(display_name="fallback")
        mock_guild.fetch_member = AsyncMock(return_value=fetched)

        await pm.load_players(mock_guild, channel_id=888)

        mock_guild.fetch_member.assert_awaited_once_with(777)
        assert pm.players[777].member is fetched

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Player")
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_chunk_timeout_falls_back_to_fetch_member(self, mock_db, mock_player_cls, mock_guild):
        """If ``chunk`` hangs past the timeout, the per-player fallback
        must fire. Guards against the on_ready-chunk deadlock."""
        import asyncio as _asyncio
        pm = PlayerManager()
        mock_db.find_players_by_game.return_value = [_player_doc(888)]
        mock_player_cls.from_dict.side_effect = lambda _p: _stub_player()

        mock_guild.chunked = False
        mock_guild.chunk = AsyncMock(side_effect=_asyncio.TimeoutError())
        mock_guild.get_member = MagicMock(return_value=None)
        fetched = MagicMock(display_name="fallback")
        mock_guild.fetch_member = AsyncMock(return_value=fetched)

        await pm.load_players(mock_guild, channel_id=888)

        mock_guild.fetch_member.assert_awaited_once_with(888)
        assert pm.players[888].member is fetched

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Player")
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_channel_scoped_load_passes_channel_id_to_db(
        self, mock_db, mock_player_cls, mock_guild,
    ):
        """Regression for the 2026-05-02 cross-game bleed.

        A guild hosting two games (Vael-facing TEST channel + OOC
        engineering channel) used to load EVERY player in the guild
        into EACH game's PlayerManager because the DB query was
        guild-scoped. ``$join`` in the second game returned "already
        a player," ``$skills`` showed the wrong game's skills, and
        the next is_dirty save would have created duplicate records
        at channel_id=OOC for users from the original game.

        Fix: ``load_players`` now calls
        ``DB.find_players_by_game(guild_id, channel_id)`` — compound
        scoping so each game gets only its own players. This test
        guards the call site, not the query semantics (the DB-side
        method has its own coverage).
        """
        pm = PlayerManager()
        mock_db.find_players_by_game.return_value = []
        mock_guild.id = 1269749534473453568
        mock_guild.chunked = True

        await pm.load_players(mock_guild, channel_id=1500205779184255146)

        # Verify the query was scoped to BOTH guild_id and channel_id,
        # not guild-only. Without the channel_id arg, an OOC-channel
        # PlayerManager would pull Vael-channel players.
        mock_db.find_players_by_game.assert_called_once_with(
            1269749534473453568, 1500205779184255146,
        )
        # Guild-only fallback must NOT have been used when channel_id
        # is supplied — that path is only for legacy callers that
        # haven't been updated, and using it would re-introduce the
        # bleed.
        mock_db.find_players_by_guild_id.assert_not_called()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Player")
    @patch("caldanai.lib.rpg.player_manager.DB")
    async def test_unknown_member_after_chunk_is_removed(self, mock_db, mock_player_cls, mock_guild):
        """If a DB player isn't in the guild any more, ``fetch_member``
        raises NotFound(10007) and the player gets cleaned up."""
        pm = PlayerManager()
        mock_db.find_players_by_game.return_value = [_player_doc(444)]
        mock_player_cls.from_dict.side_effect = lambda _p: _stub_player()

        mock_guild.chunked = False
        mock_guild.chunk = AsyncMock()
        mock_guild.get_member = MagicMock(return_value=None)
        not_found = NotFound.__new__(NotFound)
        not_found.code = 10007
        not_found.status = 404
        not_found.text = "Unknown Member"
        mock_guild.fetch_member = AsyncMock(side_effect=not_found)

        pm.remove_player = AsyncMock()
        await pm.load_players(mock_guild, channel_id=888)

        pm.remove_player.assert_awaited_once_with(444, mock_guild.id, 888)
        assert 444 not in pm.players


# ---------------------------------------------------------------------------
# do_health_regen
# ---------------------------------------------------------------------------
# Slice 2 of the Game-shrink refactor: ``do_health_regen`` used to
# live on ``Game``; it was a closed function over
# ``self.player_manager.players`` with one dispatch target
# (``self.channel``) and no other game state. It now lives on
# PlayerManager, which Game stamps with its channel at construction
# (and re-stamps in ``Game.from_dict`` after the channel is resolved
# from the bot cache). Scheduling is still Game's concern — Game
# wires ``self.player_manager.do_health_regen`` onto the game clock.

class TestDoHealthRegen:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Dispatcher")
    async def test_heals_injured_player(self, mock_dispatch):
        channel = MagicMock()
        pm = PlayerManager(channel=channel)

        player = MagicMock()
        player.health = 15
        player.health_regen = 3
        player.get_health_max.return_value = 20
        player.apply_damage.return_value = ""

        pm.players = {1: player}
        await pm.do_health_regen()

        player.apply_damage.assert_called_once_with(-3)
        # health < max, so health_regen should increment by 2 (ramp).
        assert player.health_regen == 5

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Dispatcher")
    async def test_skips_full_health_player(self, mock_dispatch):
        channel = MagicMock()
        pm = PlayerManager(channel=channel)

        player = MagicMock()
        player.health = 20
        player.health_regen = 5
        player.get_health_max.return_value = 20

        pm.players = {1: player}
        await pm.do_health_regen()

        player.apply_damage.assert_not_called()
        # At full health, regen resets to 0
        assert player.health_regen == 0

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Dispatcher")
    async def test_resurrects_dead_player(self, mock_dispatch):
        channel = MagicMock()
        pm = PlayerManager(channel=channel)

        player = MagicMock()
        player.health = 0
        player.health_regen = 2
        player.get_health_max.return_value = 20
        player.apply_damage.return_value = "gasps as life returns"

        pm.players = {1: player}
        await pm.do_health_regen()

        player.apply_damage.assert_called_once_with(-2)
        # Still below max (health is mocked at 0, so remains < 20), regen
        # increments by 2 per tick (new ramp).
        assert player.health_regen == 4
        # Dispatcher should have been called with the resurrection message
        mock_dispatch.add.assert_called_once()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Dispatcher")
    async def test_heals_most_injured_part(self, mock_dispatch):
        """Body HP at max but a part destroyed: regen still ticks
        and heals the most-injured part. Regen amount keeps growing
        until everything is at full."""
        from caldanai.lib.rpg.creatures.body_part import BodyPart

        channel = MagicMock()
        pm = PlayerManager(channel=channel)

        # Real parts so the regen path exercises BodyPart.apply_damage.
        # Values chosen so healing stays within one injury level — no
        # threshold cross → no narration (and no parse() call that
        # would need a real player). Threshold narration has its own
        # dedicated test below.
        arm = BodyPart(name="arm.right", health_max=10)
        arm.health = 7  # MINOR (70%)
        leg = BodyPart(name="leg.left", health_max=10)
        leg.health = 9  # MINOR (90%) — less injured than the arm

        player = MagicMock()
        player.health = 20  # body HP at full
        player.health_regen = 2
        player.get_health_max.return_value = 20
        player.body_parts = [arm, leg]
        # apply_damage shouldn't fire because body is at full;
        # still track to make sure we don't call it incorrectly.
        player.apply_damage.return_value = ""

        pm.players = {1: player}
        await pm.do_health_regen()

        # Body HP at max → no body-HP healing.
        player.apply_damage.assert_not_called()

        # Arm was the most injured (7/10 vs 9/10) → regen flowed there.
        assert arm.health == 9
        # Leg untouched.
        assert leg.health == 9

        # Regen still ramps (+2) because the arm hasn't fully healed.
        assert player.health_regen == 4

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Dispatcher")
    async def test_part_transition_emits_recovery_narration(self, mock_dispatch):
        """When a healing tick lifts a part across an injury-level
        threshold (e.g. SEVERE → MODERATE), the regen routine emits
        a recovery message prefixed with the player's name."""
        from caldanai.lib.rpg.creatures.body_part import BodyPart
        from caldanai.lib.rpg.creatures import Creature

        channel = MagicMock()
        pm = PlayerManager(channel=channel)

        # Part at 1/10 (SEVERE range: 0 < % < 0.3). Healing by 3
        # lands at 4/10 → 0.4 → MODERATE.
        arm = BodyPart(name="arm.right", health_max=10)
        arm.health = 1

        # Real Creature so parser's @1 token resolves. We patch
        # the minimum Player surface the regen path touches.
        player = Creature(
            name="Caels", atk=None, defense=1, dodge=1,
            health_max=20, health=20,
            pronouns="she, her, hers, her",
        )
        player.uses_article = False
        player.health_regen = 3
        player.body_parts = [arm]

        pm.players = {1: player}
        await pm.do_health_regen()

        # Healed past a threshold — a recovery line should have been
        # dispatched to the channel.
        assert mock_dispatch.add.called
        call_args = mock_dispatch.add.call_args
        msg_text = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("text", "")
        # @ tokens should have been resolved: name present, no raw
        # tokens leaked, and some form of recovery language.
        assert "Caels" in msg_text
        assert "@1" not in msg_text
        assert any(word in msg_text.lower() for word in (
            "mend", "recover", "full strength", "as good as new", "feeling returns",
        ))

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.player_manager.Dispatcher")
    async def test_no_dispatch_when_channel_unset(self, mock_dispatch):
        """If the PlayerManager has no channel bound (pre-from_dict
        hydration, tests, headless contexts), the regen tick must
        still update players but silently skip dispatch so a
        resurrection message can't NPE on a None channel."""
        pm = PlayerManager(channel=None)

        player = MagicMock()
        player.health = 0
        player.health_regen = 2
        player.get_health_max.return_value = 20
        player.apply_damage.return_value = "gasps as life returns"

        pm.players = {1: player}
        await pm.do_health_regen()

        # Player state still mutated — only dispatch is suppressed.
        player.apply_damage.assert_called_once_with(-2)
        assert player.health_regen == 4
        mock_dispatch.add.assert_not_called()
