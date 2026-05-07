"""Routing-shape tests for the rpg_presence_commands cog.

Covers the wiring contract — each of the 6 presence verbs ($lean
/ $sit / $rest / $ponder / $tend / $bite) reaches the unified
verb dispatcher in both bare and target modes, and dispatches a
non-empty line. Flavor-content authoring is the writer agent's
job; these tests intentionally don't assert on pool contents so
they keep passing as the writer fills the WRITER TODO stubs.

Static-object hook smoke-tests live at the bottom — verify that
the new presence-verb branches in Campfire / StoneField return
non-empty strings so the on_verb dispatch chain stays honest.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_presence_commands import RpgPresenceCommands


_PRESENCE_VERBS = ("lean", "sit", "rest", "ponder", "tend", "bite")


def _rpg_util():
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    return RpgUtilities


def _make_actor(name="Alice", uid=1):
    """Build a parser-friendly mock actor. The parser uses the
    ``Pronouns`` enum to look up pronoun forms — a real Player
    builds this dict via GenderMixin; here we use a defaultdict
    so any enum key resolves to "they" without us enumerating
    every form."""
    from collections import defaultdict
    actor = MagicMock()
    actor.name = name
    actor.user_id = uid
    actor.is_dead = lambda: False
    actor.pronouns = defaultdict(lambda: "they")
    actor.uses_article = False
    return actor


def _make_ctx():
    ctx = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = []
    ctx.invoked_with = "test"
    ctx.guild = MagicMock()
    ctx.channel = MagicMock()
    return ctx


def _dispatched(dispatcher_mock):
    """Extract (channel, text) pairs from a Dispatcher mock's add()
    call list — same convention used in test_social_v2 / test_warmth."""
    pairs = []
    for call in dispatcher_mock.add.call_args_list:
        args = call.args
        if len(args) >= 2:
            pairs.append((args[0], args[1]))
        elif len(args) == 1 and "file" not in call.kwargs:
            # Some dispatch sites call with one positional + content
            # in kwargs; skip the file-only ones.
            pairs.append((args[0], None))
    return pairs


# ---------------------------------------------------------------------------
# Cog registration
# ---------------------------------------------------------------------------


class TestPresenceCogRegistration:
    @pytest.mark.parametrize("cmd", _PRESENCE_VERBS)
    def test_command_attached_to_cog(self, cmd):
        cog = RpgPresenceCommands(bot=MagicMock())
        # Each presence verb must exist as a discord.py Command on
        # the cog instance — discovered via the @command decorator.
        handler = getattr(cog, cmd, None)
        assert handler is not None, f"{cmd} not registered on cog"
        assert callable(getattr(handler, "callback", None)), (
            f"{cmd} doesn't expose .callback"
        )


# ---------------------------------------------------------------------------
# Bare-invocation routing
# ---------------------------------------------------------------------------


class TestBareInvocationDispatches:
    """Each presence verb, called with no target, must dispatch the
    self-directed pool line through the unified verb dispatcher.
    Pool content is the writer's job — this test only pins that
    *something* lands."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _PRESENCE_VERBS)
    async def test_bare_dispatch(self, cmd):
        cog = RpgPresenceCommands(bot=MagicMock())
        actor = _make_actor()
        ctx = _make_ctx()
        ctx.bot = cog.bot
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()
        game.passerby = None
        game.pending_silhouette = None
        game.monster = None
        game.player_manager = SimpleNamespace(players={})
        game.room0 = None

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        pairs = _dispatched(dispatcher)
        assert pairs, f"{cmd} bare invocation dispatched nothing"
        texts = [t for _, t in pairs if t]
        assert any(t for t in texts), (
            f"{cmd} bare invocation dispatched no text content"
        )


# ---------------------------------------------------------------------------
# Bad-token routing
# ---------------------------------------------------------------------------


class TestBadTokenDispatches:
    """Each presence verb, called with a target token nothing
    matches, must dispatch the per-verb bad-token italic miss line.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _PRESENCE_VERBS)
    async def test_unmatched_token_dispatches_miss(self, cmd):
        cog = RpgPresenceCommands(bot=MagicMock())
        actor = _make_actor()
        ctx = _make_ctx()
        ctx.bot = cog.bot
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()
        # Empty room — nothing for the token chain to match.
        game.passerby = None
        game.pending_silhouette = None
        game.monster = None
        game.player_manager = SimpleNamespace(players={})
        game.room0 = None

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx, target="nonexistentthing")

        pairs = _dispatched(dispatcher)
        assert pairs, f"{cmd} unmatched-token invocation dispatched nothing"
        texts = [t for _, t in pairs if t]
        assert any(
            "nonexistentthing" in t.lower() or "*" in t
            for t in texts
        ), f"{cmd} miss line didn't reference the bad token: {texts}"


# ---------------------------------------------------------------------------
# Bot-mention scripted reply (V2 warmth-aware presence verbs)
# ---------------------------------------------------------------------------


class TestBotMentionScriptedReply:
    """V2 (2026-05-06): presence verbs are warmth-aware via
    `_NARRATION_POOLS` in `rpg_social_commands.py`. The dispatcher's
    mention path routes `$lean @bot` → BotResponder.handle_verb →
    _BOT_MENTION_REPLIES["lean"]. Pin that the scripted reply
    actually lands so a future regression to the warmth-resolver
    accidentally swallowing bot-mentions would fail loudly.

    Mirrors `test_social_v2.py::TestInteractiveCommandDispatch::
    test_bot_mention_emits_scripted_reply` — same shape, presence-
    cog-side commands.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _PRESENCE_VERBS)
    async def test_bot_mention_emits_scripted_reply(self, cmd):
        cog = RpgPresenceCommands(bot=MagicMock())
        cog.bot.user.id = 99999
        actor = _make_actor()
        bot_mention = MagicMock()
        bot_mention.id = 99999
        ctx = _make_ctx()
        ctx.message.mentions = [bot_mention]
        ctx.bot = cog.bot
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
            ) as dispatcher,
            patch(
                "caldanai.lib.rpg.creatures.bot_responder.Dispatcher",
            ) as bot_dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        pairs = _dispatched(dispatcher) + _dispatched(bot_dispatcher)
        assert pairs, f"{cmd} bot-mention dispatched nothing"
        texts = [t for _, t in pairs if t]
        # Scripted replies all reference "narrator" in the canonical
        # voice register set in BotResponder._BOT_MENTION_REPLIES.
        assert any(
            "narrator" in t.lower() for t in texts
        ), f"{cmd} bot-mention reply didn't reference the narrator: {texts}"


# ---------------------------------------------------------------------------
# Mention path — `$verb @player` lands a with-target template
# ---------------------------------------------------------------------------


class TestMentionDispatchesWithTargetTemplate:
    """``$lean @player`` was a regression after the presence cog
    shipped without mention extraction — Player.handle_verb returns
    ``None`` for verbs not in ``_NARRATION_POOLS``, and the
    dispatcher silently swallowed. Caels caught it in playtest
    2026-05-06 (Discord rendered the bad-token miss line on the
    raw ``<@id>`` text). Fix: presence cog extracts the mention
    and the dispatcher renders a per-verb ``with_target_template``
    when the responder didn't claim. This test pins both halves —
    a mention-shaped invocation must dispatch a with-target line
    that names the mentioned player by ``@2``.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _PRESENCE_VERBS)
    async def test_mention_target_dispatches(self, cmd):
        from collections import defaultdict

        cog = RpgPresenceCommands(bot=MagicMock())
        actor = _make_actor(name="Alice", uid=1)

        # Mentioned target — a Player-shaped mock with name + pronouns
        # so the parser can render @2 lines without crashing.
        target_player = MagicMock()
        target_player.name = "Vael"
        target_player.user_id = 99
        target_player.is_dead = lambda: False
        target_player.pronouns = defaultdict(lambda: "they")
        target_player.uses_article = False
        # Player.handle_verb on presence verbs returns None
        # (verb not in _NARRATION_POOLS); pin that here so the
        # test covers the actual fall-through path.
        target_player.handle_verb = MagicMock(return_value=None)

        # Discord-shape mention object — distinct Python identity
        # from any cached User, with a matching id field.
        mention = MagicMock()
        mention.id = 99
        mention.display_name = "Vael"

        ctx = _make_ctx()
        ctx.message.mentions = [mention]
        ctx.bot = cog.bot
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()
        game.passerby = None
        game.pending_silhouette = None
        game.monster = None
        game.player_manager = SimpleNamespace(players={99: target_player})
        game.room0 = None

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            # The dispatcher's mention path resolves via
            # ``RpgUtilities.get_player`` for non-bot, non-monster
            # mentions. Return our shaped Player.
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target_player),
            ),
            patch(
                "caldanai.lib.rpg.helpers.verb_dispatch.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        pairs = _dispatched(dispatcher)
        assert pairs, f"{cmd} mention-path dispatched nothing"
        texts = [t for _, t in pairs if t]
        # The with-target template uses @2 = mentioned player.
        # Confirm Vael's name appears in the rendered line — the
        # bug was the line saying "finds nothing to lean on" with
        # the raw `<@id>` text instead of the player's name.
        assert any(
            "vael" in t.lower() for t in texts
        ), f"{cmd} mention dispatch didn't reference @2: {texts}"
        # Italic asterisks confirm the with-target render path
        # (consistent with the pool's italic convention).
        assert any(
            t.startswith("*") and t.endswith("*") for t in texts
        ), f"{cmd} mention dispatch wasn't italicized: {texts}"


# ---------------------------------------------------------------------------
# Static-object branch smoke tests
# ---------------------------------------------------------------------------


class TestStaticObjectPresenceBranches:
    """Each new presence-verb branch on Campfire / StoneField must
    return a non-empty rendered string when called directly — pins
    the on_verb dispatch addition without asserting flavor content.
    """

    _CAMPFIRE_VERBS = ("sit", "rest", "lean", "tend", "ponder", "bite")
    _STONE_FIELD_VERBS = ("lean", "sit", "rest", "ponder", "tend")

    def _make_actor_with_pronouns(self):
        actor = _make_actor()
        actor.name = "Alice"
        return actor

    def _make_game(self):
        game = MagicMock()
        game.game_clock = MagicMock()
        game.game_clock.get_time_of_day.return_value = "morning"
        return game

    @pytest.mark.parametrize("verb", _CAMPFIRE_VERBS)
    def test_campfire_returns_string(self, verb):
        from caldanai.lib.rpg.world.objects.campfire import Campfire
        fire = Campfire()
        out = fire.on_verb(verb, self._make_game(), self._make_actor_with_pronouns())
        assert out, f"campfire.on_verb({verb!r}) returned empty: {out!r}"
        assert isinstance(out, str)

    @pytest.mark.parametrize("verb", _STONE_FIELD_VERBS)
    def test_stone_field_returns_string(self, verb):
        from caldanai.lib.rpg.world.objects.stone_field import StoneField
        stones = StoneField()
        out = stones.on_verb(verb, self._make_game(), self._make_actor_with_pronouns())
        assert out, f"stone_field.on_verb({verb!r}) returned empty: {out!r}"
        assert isinstance(out, str)

    def test_stone_field_no_bite(self):
        """$bite intentionally omitted from stone field — the on_verb
        chain returns None for it (falls through to bad-token italic
        in the cog dispatcher)."""
        from caldanai.lib.rpg.world.objects.stone_field import StoneField
        stones = StoneField()
        assert stones.on_verb(
            "bite", self._make_game(), self._make_actor_with_pronouns(),
        ) is None
