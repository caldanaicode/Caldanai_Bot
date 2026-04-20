"""Tests for the ``$spawn destroy`` admin command in
``caldanai.lib.cogs.rpg_admin_commands``.

Force-destroys named body parts on the current monster. Lives
under the ``$spawn`` admin group (alongside ``$spawn kill``,
``$spawn monster``, etc.) rather than top-level because
``destroy`` is already an alias of ``$attack`` in the user cog.
Useful for playtesting part-driven death paths (e.g. hydra
decapitation) without burning combat rounds on lucky rolls.

Intentional contract: ``$spawn destroy`` sets parts to 0 HP and
fires ``on_destroyed`` hooks, but does NOT itself kill the
monster. Part-driven death (via
:meth:`Creature.check_part_driven_death`) fires in the next combat
round — this is what we WANT to exercise during playtest, so the
admin command should not short-circuit it.
"""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_admin_commands import RpgAdminCommands


@pytest.fixture
def cog():
    return RpgAdminCommands(bot=MagicMock())


def _make_part(name: str, *, health_max: int = 10, on_destroyed_return: str = ""):
    """Minimal part stub — exposes just the attributes
    ``$spawn destroy`` reads."""
    part = MagicMock()
    part.name = name
    part.display_name = name.replace(".", " ")
    part.health = health_max
    part.health_max = health_max
    part.is_destroyed = MagicMock(side_effect=lambda: part.health <= 0)
    part.on_destroyed = MagicMock(return_value=on_destroyed_return)
    return part


def _make_ctx_with_monster(cog, monster, channel_id: int = 42):
    """Wire ``ctx.channel.id`` → ``bot.games`` → monster."""
    ctx = MagicMock()
    ctx.channel.id = channel_id
    game = MagicMock()
    game.monster = monster
    game.channel = MagicMock()
    cog.bot.games.get = MagicMock(return_value=game)
    return ctx, game


class TestDestroyBasics:
    @pytest.mark.asyncio
    async def test_single_part_zeroed(self, cog):
        part = _make_part("head.1")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.destroy.callback(cog, ctx, "head.1")

        assert part.health == 0
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

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.destroy.callback(cog, ctx, "head.1", "head.2")

        assert h1.health == 0
        assert h2.health == 0

    @pytest.mark.asyncio
    async def test_fuzzy_match_delegates_to_find_parts(self, cog):
        """``$spawn destroy h.1`` should work because the parser's
        fuzzy-match layer (``Creature.find_parts``) resolves the
        short form. The admin command just hands the raw token off."""
        part = _make_part("head.1")
        monster = MagicMock()
        monster.name = "hydra"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[part])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.destroy.callback(cog, ctx, "h.1")

        # The fuzzy-match happens inside ``find_parts``; the admin
        # command just passes the literal token. So what we verify
        # is that the token reached find_parts verbatim.
        monster.find_parts.assert_called_once_with("h.1")
        assert part.health == 0


class TestDestroyGuards:
    @pytest.mark.asyncio
    async def test_no_game_noop(self, cog):
        """No game in the channel → command exits silently
        (consistent with other admin commands in this cog)."""
        cog.bot.games.get = MagicMock(return_value=None)
        ctx = MagicMock()
        ctx.channel.id = 42

        # Should not raise.
        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx, "head.1")

        # No dispatch calls made — silent no-op.
        assert dispatcher.add.call_count == 0

    @pytest.mark.asyncio
    async def test_no_monster_prints_error(self, cog):
        monster = None
        ctx, game = _make_ctx_with_monster(cog, monster)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx, "head.1")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "no monster" in sent.lower()

    @pytest.mark.asyncio
    async def test_no_parts_args_prints_usage(self, cog):
        monster = MagicMock()
        monster.name = "goblin"
        monster.uses_article = True
        monster.find_parts = MagicMock()
        ctx, game = _make_ctx_with_monster(cog, monster)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx)

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert "usage" in sent.lower()
        assert "$spawn destroy" in sent
        # find_parts shouldn't have been invoked — we bail before.
        monster.find_parts.assert_not_called()

    @pytest.mark.asyncio
    async def test_unmatched_part_name_warns(self, cog):
        monster = MagicMock()
        monster.name = "goblin"
        monster.uses_article = True
        monster.find_parts = MagicMock(return_value=[])
        ctx, game = _make_ctx_with_monster(cog, monster)

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx, "tentacle")

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

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher"):
            await cog.destroy.callback(cog, ctx, "head.1")

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

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx, "head.1")

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

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx, "head")

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

        with patch("caldanai.lib.cogs.rpg_admin_commands.Dispatcher") as dispatcher:
            await cog.destroy.callback(cog, ctx, "head.1", "head.2")

        sent = " ".join(
            call.args[1] for call in dispatcher.add.call_args_list if len(call.args) > 1
        )
        assert h1.display_name in sent
        assert h2.display_name in sent
