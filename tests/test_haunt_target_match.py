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


async def _invoke_haunt(cog, game, player, target, *, mentions=None, bot_user=None):
    """Drive ``haunt.callback`` with patched Dispatcher and
    RpgUtilities so monster fuzzy resolution is exercised against
    a stubbed game state.

    Both ``get_game_and_player`` (used at command entry) and
    ``get_game`` (called inside the Converter family during
    fuzzy_resolve) are patched to return the stubbed game — the
    dispatcher walks Converters that re-query for game state, so
    that path needs the same fixture.

    ``bot_user`` lets a caller pre-seed ``cog.bot.user`` for the
    bot-mention reject path; otherwise a fresh MagicMock is used
    (distinct from any test-supplied mention).
    """
    cog.bot = MagicMock()
    cog.bot.user = bot_user if bot_user is not None else MagicMock()
    ctx = _make_ctx(mentions=mentions, bot_user=cog.bot.user)

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
    the call site falls through to the no-target ambient pool and
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
    call site falls through to the no-target ambient flavor pool.
    The monster's name must not appear in that pool's output — those
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
        """``game.monster is None`` short-circuits MonsterConverter
        and PlayerConverter has no fuzzy match for ``cyc``, so the
        dispatcher returns None and the call site falls through to
        the no-target ambient flavor pool."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        game = _make_game(monster=None, players=[alice])

        await _invoke_haunt(cog, game, alice, target="cyc")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert sent.strip()


# ---------------------------------------------------------------------------
# Dispatcher-pattern integration — silent fall-through on miss, mention
# routing through the dispatcher, bot-mention pre-check, monster-priority on
# name collision.
# ---------------------------------------------------------------------------


_AMBIENT_FRAGMENTS = (
    "ghostly presence",
    "sudden chill",
    "forlorn lament",
)


class TestHauntDispatcherIntegration:
    """End-to-end proofs that the dispatcher migration preserves the
    `$haunt` UX: a miss falls silently through to the no-target
    ambient pool (no error message), `@<player>` mentions still
    resolve, bot mentions still reject, and the `prefer="monster"`
    priority wins on name collision."""

    @pytest.mark.asyncio
    async def test_miss_falls_through_to_ambient_pool_not_error(self):
        """No-match resolves to ``None`` through ``fuzzy_resolve`` and
        the call site falls through to the bare ambient ghost flavor.
        Asserts the dispatched line is from the ambient pool (one of
        the three @1-only lines), not an error message about the
        unknown target."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice])

        await _invoke_haunt(
            cog, game, alice,
            target="nonsense_target_that_doesnt_match_anything",
        )

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # No monster name leaked from the targeted pool.
        assert "cyclops" not in sent
        # No error-shaped surfacing.
        assert "doesn't match" not in sent.lower()
        assert "unknown" not in sent.lower()
        # Hit the ambient pool — one of the three signature fragments
        # must appear.
        assert any(frag in sent for frag in _AMBIENT_FRAGMENTS)

    @pytest.mark.asyncio
    async def test_mention_routes_through_dispatcher_to_player(self):
        """``$haunt <@id>`` flows through the dispatcher: the mention
        misses MonsterConverter, then hits PlayerConverter's mention
        fast-path. The dispatched flavor is from the player-targeted
        pool (``@2`` referencing the player), and ``haunted`` is the
        Player object — not the bot's-imagination reject path and not
        the ambient pool."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        # Bob is the haunting actor (must be dead for the targeted
        # pool to surface); Alice is the @-mentioned target.
        bob = _make_player("Bob", uid=222222222222222222, dead=True)
        game = _make_game(monster=None, players=[alice, bob])

        # Build a Member-shaped mention object and patch
        # MemberConverter so the mention-fast-path resolves to Alice
        # without needing a real Discord guild.
        mention = MagicMock()
        mention.id = alice.user_id
        mention.display_name = "Alice"

        from caldanai.lib.rpg.helpers.utils import RpgUtilities
        from discord.ext.commands import MemberConverter

        with (
            patch.object(
                RpgUtilities,
                "get_game_and_player",
                new=AsyncMock(return_value=(game, bob)),
            ),
            patch.object(
                RpgUtilities,
                "get_game",
                new=AsyncMock(return_value=game),
            ),
            patch.object(
                RpgUtilities,
                "get_player",
                new=AsyncMock(return_value=alice),
            ),
            patch.object(
                MemberConverter,
                "convert",
                new=AsyncMock(return_value=mention),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            ctx = _make_ctx(mentions=[mention])
            cog.bot = MagicMock()
            cog.bot.user = MagicMock()  # Distinct from the alice mention.
            await cog.haunt.callback(
                cog, ctx, target=f"<@!{alice.user_id}>",
            )

            sent = "\n".join(
                arg for call in dispatcher.add.call_args_list
                for arg in call.args[1:] if isinstance(arg, str)
            )
            # Player-targeted pool references both actors. Alice's
            # name surfaces somewhere (via @2 / @2np / @2o / @2Np).
            assert "Alice" in sent
            # Not the ambient fall-through.
            assert not any(frag in sent for frag in _AMBIENT_FRAGMENTS)
            # Not the bot-mention reject.
            assert "figment" not in sent

    @pytest.mark.asyncio
    async def test_bot_mention_rejects_before_dispatcher(self):
        """``$haunt @bot`` is rejected by the call-site pre-check
        (the dispatcher is never reached). The "figment of your
        imagination" line surfaces — and the ambient pool does
        not."""
        cog = _cog()
        alice = _make_player("Alice", uid=111111111111111111, dead=True)
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice])

        bot_mention = MagicMock()
        bot_mention.id = 999999999999999999

        await _invoke_haunt(
            cog, game, alice,
            target=f"<@!{bot_mention.id}>",
            mentions=[bot_mention],
            bot_user=bot_mention,
        )

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        assert "figment" in sent
        assert not any(frag in sent for frag in _AMBIENT_FRAGMENTS)

    @pytest.mark.asyncio
    async def test_monster_wins_on_name_collision_with_player(self):
        """``prefer="monster"`` (the default for ``CreatureConverter``
        on ``$haunt``) means an in-scene monster beats a name-collision
        player. A cyclops + a player named "Cycelle": ``$haunt cyc``
        resolves the cyclops, not the player. Player ambient pool is
        not hit because the resolution succeeded."""
        cog = _cog()
        cycelle = _make_player(
            "Cycelle", uid=222222222222222222, dead=True,
        )
        alice = _make_player(
            "Alice", uid=111111111111111111, dead=True,
        )
        cyclops = _make_monster("cyclops")
        game = _make_game(monster=cyclops, players=[alice, cycelle])

        await _invoke_haunt(cog, game, alice, target="cyc")

        sent = "\n".join(_dispatched_strings(game._dispatcher))
        # The cyclops surfaces (targeted-pool flavor with @2 = monster).
        assert "cyclops" in sent
        # Not the ambient pool.
        assert not any(frag in sent for frag in _AMBIENT_FRAGMENTS)
        # Cycelle's name doesn't surface — the player path lost.
        assert "Cycelle" not in sent
