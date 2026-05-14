"""Regression tests for ``$haunt <target>`` monster fuzzy matching.

Pre-fuzzy ``$haunt`` only accepted the spawned monster's exact
``self.name`` (case-insensitively). Players reaching for
``$haunt cyc`` against a cyclops or ``$haunt hyd`` against a
hexed hydra silently bounced into the bare-invocation flavor pool.

Resolution now routes through :func:`resolve_active_monster`,
which delegates to :meth:`Creature.matches_token` — same fuzzy
pass-chain as ``$look`` and ``$kill``: exact / word-token →
prefix-of-any-word → typo tolerance. The tests below exercise
the end-to-end ``haunt`` callback so the wiring stays sound, not
just the helper. The helper itself is covered by
``test_look_target_match.py``.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson.objectid import ObjectId

from caldanai.lib.cogs.rpg_social_commands import RpgSocialCommands
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.player import Player


def _make_player(name="Alice", uid=111111111111111111, dead=False):
    p = Player(
        pid=ObjectId(),
        gid=100,
        uid=uid,
        weight_limit=100,
        clarks=0,
        defense=6,
        dodge=6,
        health=0 if dead else 20,
        health_max=20,
        gender="female",
        pronouns="she,her,her,hers,herself",
    )
    member = MagicMock()
    member.id = uid
    member.display_name = name
    p.member = member
    p.name = name
    return p


def _make_monster(name="cyclops", dead=False):
    m = Creature(
        name=name,
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=20,
        gender="male",
        pronouns="he,him,his,his,himself",
    )
    m.health = 0 if dead else 20
    m.body_parts = [
        BodyPart(name="head", health_max=10),
        BodyPart(name="torso", health_max=20),
    ]
    return m


def _make_game(monster, players):
    game = MagicMock()
    game.monster = monster
    game.channel = MagicMock()
    game.player_manager = MagicMock()
    game.player_manager.players = {p.user_id: p for p in players}
    return game


def _make_ctx(*, mentions=None, bot_user=None):
    ctx = MagicMock()
    ctx.guild = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = mentions or []
    ctx.bot = MagicMock()
    ctx.bot.user = bot_user or MagicMock()
    return ctx


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


async def _invoke_haunt(cog, game, player, target):
    """Drive ``haunt.callback`` with patched Dispatcher and
    RpgUtilities so monster fuzzy resolution is exercised against
    a stubbed game state.

    ``cog.haunt.cog`` is set on the Command instance so the
    fall-through ``await self.haunt(ctx)`` re-invocation (fired on
    fuzzy non-match) resolves the cog binding correctly — discord.py
    sets this at cog-load time, which we bypass in unit tests.
    """
    ctx = _make_ctx()
    cog.bot = MagicMock()
    cog.bot.user = MagicMock()  # Distinct from any mention.
    cog.haunt.cog = cog

    from caldanai.lib.rpg.helpers.utils import RpgUtilities

    with (
        patch.object(
            RpgUtilities,
            "get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ),
        patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher") as dispatcher,
    ):
        await cog.haunt.callback(cog, ctx, target=target)
        game._dispatcher = dispatcher


def _cog() -> RpgSocialCommands:
    return RpgSocialCommands(bot=MagicMock())


# ---------------------------------------------------------------------------
# Fuzzy success — dead player so the targeted monster name surfaces.
# ---------------------------------------------------------------------------


class TestHauntFuzzyMonsterTarget:
    """Dead player + monster present: the targeted-monster flavor
    pool references ``@2`` (the monster). When fuzzy resolves, the
    monster's name appears in the dispatched text; when it doesn't,
    the code falls back to ``self.haunt(ctx)`` with no target and
    emits a bare ``@1``-only line."""

    @pytest.mark.asyncio
    async def test_exact_monster_name_matches(self):
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice])

        await _invoke_haunt(cog, game, alice, target="cyclops")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "cyclops" in sent

    @pytest.mark.asyncio
    async def test_uppercase_exact_matches(self):
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice])

        await _invoke_haunt(cog, game, alice, target="CYCLOPS")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "cyclops" in sent

    @pytest.mark.asyncio
    async def test_prefix_three_letters_matches(self):
        """The motivating case: ``$haunt cyc`` against a cyclops."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice])

        await _invoke_haunt(cog, game, alice, target="cyc")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "cyclops" in sent

    @pytest.mark.asyncio
    async def test_word_token_matches_variant_name(self):
        """``$haunt hydra`` against a "hexed hydra" — word-token
        equality on a multi-word monster name."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        hydra = _make_monster("hexed hydra")
        game = _make_game(monster=hydra, players=[alice])

        await _invoke_haunt(cog, game, alice, target="hydra")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "hydra" in sent

    @pytest.mark.asyncio
    async def test_prefix_of_variant_word_matches(self):
        """``$haunt hyd`` against a "hexed hydra" — prefix of one
        of the words in a multi-word name."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        hydra = _make_monster("hexed hydra")
        game = _make_game(monster=hydra, players=[alice])

        await _invoke_haunt(cog, game, alice, target="hyd")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "hydra" in sent


# ---------------------------------------------------------------------------
# Non-match — falls back to bare haunt; monster name must not surface.
# ---------------------------------------------------------------------------


class TestHauntNonMatchFallsBackToBare:
    """When the target doesn't fuzzy-match the spawned monster, the
    handler recurses into the bare-invocation flavor pool. The
    monster's name must not appear in that pool's output — those
    lines reference ``@1`` only."""

    @pytest.mark.asyncio
    async def test_unrelated_target_falls_through(self):
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice])

        await _invoke_haunt(cog, game, alice, target="bandit")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # Bare pool references only the player (@1), not @2.
        assert "cyclops" not in sent
        # Something was dispatched — the bare pool ran.
        assert sent.strip()

    @pytest.mark.asyncio
    async def test_no_monster_falls_through(self):
        """``game.monster is None`` short-circuits the resolver and
        re-invokes the bare path."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        game = _make_game(monster=None, players=[alice])

        await _invoke_haunt(cog, game, alice, target="cyc")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert sent.strip()
