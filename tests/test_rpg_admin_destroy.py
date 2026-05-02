"""Tests for the ``$creature destroy`` admin command in
``caldanai.lib.cogs.rpg_admin_commands``.

Force-destroys named body parts on a target creature. Lives under
the ``$creature`` admin group (alongside future per-creature
state ops like heal / inspect / etc.) rather than top-level
because ``destroy`` is already an alias of ``$attack`` in the
user cog.

Target resolution: mention → player; first arg fuzzy-match against
``game.monster.name`` → that monster; fallthrough → ``game.monster``.
Useful for playtesting part-driven death paths (e.g. hydra
decapitation, critical-part-destruction rescue on a player) without
burning combat rounds on lucky rolls.

Intentional contract: ``$creature destroy`` sets parts to 0 HP and
fires ``on_destroyed`` hooks, but does NOT itself kill the
target. Part-driven death (via
:meth:`Creature.check_part_driven_death`) fires in the next combat
round — this is what we WANT to exercise during playtest, so the
admin command should not short-circuit it.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_admin_commands import RpgAdminCommands


@pytest.fixture
def cog():
    return RpgAdminCommands(bot=MagicMock())


def _make_part(name: str, *, health_max: int = 10, on_destroyed_return: str = ""):
    """Minimal part stub — exposes just the attributes
    ``$creature destroy`` reads."""
    part = MagicMock()
    part.name = name
    part.display_name = name.replace(".", " ")
    part.health = health_max
    part.health_max = health_max
    part.is_destroyed = MagicMock(side_effect=lambda: part.health <= 0)
    part.on_destroyed = MagicMock(return_value=on_destroyed_return)
    return part


def _make_ctx_with_monster(cog, monster, channel_id: int = 42):
    """Wire a context whose ``RpgUtilities.get_game`` resolution
    returns a game with the given monster. The patch is active
    during the test body via ``with patch(...)``; tests that need
    it should wrap their callback invocation in
    ``patch_get_game(game)``.
    """
    ctx = MagicMock()
    ctx.channel.id = channel_id
    ctx.message.mentions = []
    game = MagicMock()
    game.monster = monster
    game.channel = MagicMock()
    return ctx, game


def _patch_get_game(game):
    """Context manager that makes ``RpgUtilities.get_game`` return
    ``game``. Mirrors the production resolution path the new
    ``$creature destroy`` uses."""
    return patch(
        "caldanai.lib.cogs.rpg_admin_commands.RpgUtilities.get_game",
        new=AsyncMock(return_value=game),
    )


class TestDestroyBasics:
    """Verify ``$creature destroy`` routes through ``apply_damage``
    with ``target_part`` so the canonical critical-part safety
    sweep fires (zeros body HP on critical-part destruction) and
    gear placements clear via the normal pipeline. Tests check the
    apply_damage call shape rather than direct part.health
    mutation since the previous mutation was the bug being fixed."""

    @pytest.mark.asyncio
    async def test_single_part_routes_through_apply_damage(self, cog):
        part = _make_part("head.1")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.creature_destroy.callback(cog, ctx, "head.1")

        # apply_damage called with the part as target — drives the
        # canonical destruction path (body-HP safety sweep, gear
        # drop) instead of direct mutation.
        monster.apply_damage.assert_called_once_with(
            part.health_max, dmg_type=None, target_part=part,
        )
        part.on_destroyed.assert_called_once_with(monster)

    @pytest.mark.asyncio
    async def test_multiple_parts_variadic(self, cog):
        h1 = _make_part("head.1")
        h2 = _make_part("head.2")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        # find_parts returns the specific part for each name. We mock
        # per-call behavior by name.
        def _find(name):
            return {"head.1": [h1], "head.2": [h2]}.get(name, [])
        monster.find_parts = MagicMock(side_effect=_find)
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.creature_destroy.callback(cog, ctx, "head.1", "head.2")

        # Each part triggered its own apply_damage call.
        assert monster.apply_damage.call_count == 2
        called_parts = [
            kwargs.get("target_part") or args[2]
            for args, kwargs in (
                (call.args, call.kwargs)
                for call in monster.apply_damage.call_args_list
            )
        ]
        assert h1 in called_parts and h2 in called_parts

    @pytest.mark.asyncio
    async def test_fuzzy_match_delegates_to_find_parts(self, cog):
        """``$creature destroy h.1`` should work because the parser's
        fuzzy-match layer (``Creature.find_parts``) resolves the
        short form. The admin command just hands the raw token off."""
        part = _make_part("head.1")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.creature_destroy.callback(cog, ctx, "h.1")

        # The fuzzy-match happens inside ``find_parts``; the admin
        # command just passes the literal token. So what we verify
        # is that the token reached find_parts verbatim.
        monster.find_parts.assert_called_once_with("h.1")
        monster.apply_damage.assert_called_once_with(
            part.health_max, dmg_type=None, target_part=part,
        )


class TestDestroyGuards:
    @pytest.mark.asyncio
    async def test_no_game_noop(self, cog):
        """No game in the channel → command exits silently
        (consistent with other admin commands in this cog)."""
        ctx = MagicMock()
        ctx.channel.id = 42
        ctx.message.mentions = []

        # Should not raise.
        with _patch_get_game(None), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx, "head.1")

        # No dispatch calls made — silent no-op.
        assert dispatcher.add.call_count == 0

    @pytest.mark.asyncio
    async def test_no_target_prints_error(self, cog):
        """No mention, no monster, no fuzzy match → no target,
        error message surfaces to the invoker."""
        monster = None
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx, "head.1")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "no target" in sent.lower()

    @pytest.mark.asyncio
    async def test_no_parts_args_prints_usage(self, cog):
        monster = MagicMock()
        monster.name = "goblin"
        monster.uses_article = True
        monster.find_parts = MagicMock()
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx)

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "usage" in sent.lower()
        assert "$creature destroy" in sent
        # find_parts shouldn't have been invoked — we bail before.
        monster.find_parts.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmatched_part_name_warns(self, cog):
        monster = MagicMock()
        monster.name = "goblin"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx, "tentacle")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "no body part matched" in sent.lower()
        assert "tentacle" in sent

    @pytest.mark.asyncio
    async def test_already_destroyed_part_skipped(self, cog):
        """If the part is already at 0 HP, ``$spawn destroy`` should not
        re-invoke ``on_destroyed`` (the hook fires once per
        destruction, matching the combat-resolution contract)."""
        part = _make_part("head.1")
        part.health = 0  # already destroyed
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.creature_destroy.callback(cog, ctx, "head.1")

        part.on_destroyed.assert_not_called()


class TestDestroyAnnouncement:
    @pytest.mark.asyncio
    async def test_monster_with_article_uses_the(self, cog):
        part = _make_part("head.1")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx, "head.1")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "the hydra's" in sent

    @pytest.mark.asyncio
    async def test_monster_without_article_omits_the(self, cog):
        """Named-monster case (rare — monsters typically use article,
        but a named boss wouldn't). Renders without 'the'."""
        part = _make_part("head")
        monster = MagicMock()
        monster.name = "Kraegos"
        monster.uses_article = False
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx, "head")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "Kraegos's" in sent
        assert "the Kraegos" not in sent

    @pytest.mark.asyncio
    async def test_part_display_names_in_announcement(self, cog):
        h1 = _make_part("head.1")
        h2 = _make_part("head.2")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        def _find(name):
            return {"head.1": [h1], "head.2": [h2]}.get(name, [])
        monster.find_parts = MagicMock(side_effect=_find)
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.creature_destroy.callback(cog, ctx, "head.1", "head.2")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert h1.display_name in sent
        assert h2.display_name in sent


class TestDestroyPlayerTargeting:
    """The new ``$creature destroy @player <part>`` shape — pulls
    the target via ``RpgUtilities.get_player`` instead of falling
    through to ``game.monster``. Useful for setting up critical-
    part-rescue tests on players (which the prior ``$spawn destroy``
    couldn't do at all)."""

    @pytest.mark.asyncio
    async def test_player_mention_targets_player(self, cog):
        """Mentioning a player routes destruction at them, leaves
        the spawned monster untouched, and the announcement omits
        the article (players don't take ``the``)."""
        head = _make_part("head", health_max=15)
        player = MagicMock()
        player.name = "Caels"
        # Players don't have ``uses_article`` — duck-type check
        # in the production code falls through to no article.
        del player.uses_article
        player.find_parts = MagicMock(return_value=[head])

        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[_make_part("ignored")])

        ctx, game = _make_ctx_with_monster(cog, monster)
        member = MagicMock()
        ctx.message.mentions = [member]

        with (
            _patch_get_game(game),
            patch(
                "caldanai.lib.cogs.rpg_admin_commands.RpgUtilities.get_player",
                new=AsyncMock(return_value=player),
            ),
            patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher,
        ):
            await cog.creature_destroy.callback(cog, ctx, "head")

        # Player's head routed through apply_damage; monster untouched.
        player.apply_damage.assert_called_once_with(
            head.health_max, dmg_type=None, target_part=head,
        )
        head.on_destroyed.assert_called_once_with(player)
        monster.find_parts.assert_not_called()

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        # Player gets no ``the`` article.
        assert "Caels's head" in sent
        assert "the Caels" not in sent

    @pytest.mark.asyncio
    async def test_monster_fuzzy_name_targets_monster(self, cog):
        """``$creature destroy hydra head.1`` — first arg is a
        substring of the spawned monster's name → target the
        monster, treat remaining args as parts."""
        h1 = _make_part("head.1")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[h1])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with _patch_get_game(game), patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.creature_destroy.callback(cog, ctx, "hydra", "head.1")

        # Monster's head routed through apply_damage; the "hydra"
        # arg was consumed as the target identifier, not passed
        # to find_parts.
        monster.apply_damage.assert_called_once_with(
            h1.health_max, dmg_type=None, target_part=h1,
        )
        monster.find_parts.assert_called_once_with("head.1")
