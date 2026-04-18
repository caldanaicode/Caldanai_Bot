"""Tests for the ``$target`` command handler in ``RpgUserCommands``.

Two behavior surfaces pinned here:

1. Flavor pools for ``$target @someone`` — the self/other/bot
   flavor-only branches added alongside body-part targeting. Each pool
   must be non-empty and each line must be parseable by the narration
   engine (no stray tokens, no empty strings).
2. Guard ordering inside ``target_part`` — when no monster is active,
   the handler emits "nothing to target" regardless of whether the
   player happens to also be outside the combatants list. The old
   order surfaced the misleading "use $kill to join" prompt in idle
   channels where there was nothing to join.
3. Player-mention routing — the command should reach the self /
   other-player / bot / doppelganger-disguise branches based on who
   the mention resolves to.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
from caldanai.lib.rpg.helpers.parser import parse


class TestTargetFlavorPools:
    """Class-level attributes on ``RpgUserCommands`` carry the flavor
    text pools. Pool shape is part of the contract — an empty pool
    would silently produce an empty Dispatcher message."""

    def test_self_pool_non_empty(self):
        assert RpgUserCommands._TARGET_SELF_FLAVOR
        assert all(isinstance(line, str) and line for line in RpgUserCommands._TARGET_SELF_FLAVOR)

    def test_other_pool_non_empty(self):
        assert RpgUserCommands._TARGET_OTHER_FLAVOR
        assert all(isinstance(line, str) and line for line in RpgUserCommands._TARGET_OTHER_FLAVOR)

    def test_bot_pool_non_empty(self):
        assert RpgUserCommands._TARGET_BOT_FLAVOR
        assert all(isinstance(line, str) and line for line in RpgUserCommands._TARGET_BOT_FLAVOR)

    def test_self_pool_parses_against_one_actor(self):
        """Self-flavor lines receive only @1 (the invoking player) —
        an @2 token would render as literal '@2' and stick out."""
        player = _make_player(name="Alice")
        for line in RpgUserCommands._TARGET_SELF_FLAVOR:
            rendered = parse(line, player)
            assert "@1" not in rendered and "@2" not in rendered, (
                f"unresolved token in: {rendered!r}"
            )

    def test_other_pool_parses_against_two_actors(self):
        """Other-flavor lines receive @1 (invoker) and @2 (target)."""
        actor = _make_player(name="Alice")
        target = _make_player(name="Bob")
        for line in RpgUserCommands._TARGET_OTHER_FLAVOR:
            rendered = parse(line, actor, target)
            assert "@1" not in rendered and "@2" not in rendered, (
                f"unresolved token in: {rendered!r}"
            )

    def test_bot_pool_parses_against_one_actor(self):
        player = _make_player(name="Alice")
        for line in RpgUserCommands._TARGET_BOT_FLAVOR:
            rendered = parse(line, player)
            assert "@1" not in rendered and "@2" not in rendered, (
                f"unresolved token in: {rendered!r}"
            )


class TestTargetGuardOrder:
    """When there's nothing to target *and* the player isn't in the
    combatants list, the 'nothing to target' branch must win — the old
    ordering surfaced 'use $kill to join' which is nonsense when there
    is no combat to join."""

    @pytest.mark.asyncio
    async def test_no_monster_wins_over_not_in_combatants(self):
        cog = RpgUserCommands(bot=MagicMock())
        ctx = _make_ctx(mentions=[])
        game = _make_game(monster=None, combatants=[])
        player = _make_player(name="Alice")

        with (
            patch.object(
                _rpg_util_path(),
                "get_game_and_player",
                new=AsyncMock(return_value=(game, player)),
            ),
            patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
        ):
            await cog.target_part.callback(cog, ctx, part=None)

        sent = _dispatched_strings(dispatcher)
        assert any("nothing to target" in s.lower() for s in sent)
        assert not any("$kill" in s.lower() for s in sent)


class TestTargetPlayerMentionRouting:
    @pytest.mark.asyncio
    async def test_self_mention_uses_self_pool(self):
        cog = RpgUserCommands(bot=MagicMock())
        player = _make_player(name="Alice")
        mention = _mention_of(player)
        ctx = _make_ctx(mentions=[mention])
        game = _make_game(monster=None, combatants=[])

        with (
            patch.object(
                _rpg_util_path(),
                "get_game_and_player",
                new=AsyncMock(return_value=(game, player)),
            ),
            patch.object(
                _rpg_util_path(),
                "get_player",
                new=AsyncMock(return_value=player),
            ),
            patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
            patch(
                "caldanai.lib.cogs.rpg_user_commands.choice",
                side_effect=lambda pool: pool[0],
            ),
        ):
            await cog.target_part.callback(cog, ctx, part=None)

        sent = _dispatched_strings(dispatcher)
        # First line of the self pool with @1/@1a resolved.
        expected = parse(RpgUserCommands._TARGET_SELF_FLAVOR[0], player)
        assert expected in sent

    @pytest.mark.asyncio
    async def test_other_mention_uses_other_pool(self):
        cog = RpgUserCommands(bot=MagicMock())
        player = _make_player(name="Alice")
        target = _make_player(name="Bob")
        mention = _mention_of(target)
        ctx = _make_ctx(mentions=[mention])
        game = _make_game(monster=None, combatants=[])

        with (
            patch.object(
                _rpg_util_path(),
                "get_game_and_player",
                new=AsyncMock(return_value=(game, player)),
            ),
            patch.object(
                _rpg_util_path(),
                "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
            patch(
                "caldanai.lib.cogs.rpg_user_commands.choice",
                side_effect=lambda pool: pool[0],
            ),
        ):
            await cog.target_part.callback(cog, ctx, part=None)

        sent = _dispatched_strings(dispatcher)
        expected = parse(RpgUserCommands._TARGET_OTHER_FLAVOR[0], player, target)
        assert expected in sent

    @pytest.mark.asyncio
    async def test_bot_mention_uses_bot_pool(self):
        """Mentioning the bot itself short-circuits to the bot pool."""
        bot = MagicMock()
        bot.user = MagicMock()
        cog = RpgUserCommands(bot=bot)
        player = _make_player(name="Alice")
        ctx = _make_ctx(mentions=[bot.user])
        game = _make_game(monster=None, combatants=[])

        with (
            patch.object(
                _rpg_util_path(),
                "get_game_and_player",
                new=AsyncMock(return_value=(game, player)),
            ),
            patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
            patch(
                "caldanai.lib.cogs.rpg_user_commands.choice",
                side_effect=lambda pool: pool[0],
            ),
        ):
            await cog.target_part.callback(cog, ctx, part="@TheBot")

        sent = _dispatched_strings(dispatcher)
        expected = parse(RpgUserCommands._TARGET_BOT_FLAVOR[0], player)
        assert expected in sent

    @pytest.mark.asyncio
    async def test_dead_invoker_hits_dead_pool_regardless_of_mention_type(self):
        """Regression: the bot-mention / doppelganger / self /
        other-player branches used to run before the death check,
        so a dead player targeting any of them would see the
        target-specific flavor instead of the dead-invoker pool.
        Dead-invoker must fire first — a corpse can't meaningfully
        aim at anything, so the mention target is immaterial."""
        cog = RpgUserCommands(bot=MagicMock())
        cog.bot.user = MagicMock()
        player = _make_player(name="Alice")
        player.health = 0  # dead
        assert player.is_dead()

        cases = [
            # (description, mention, expect-get_player-to-be-called)
            ("bot mention", cog.bot.user, False),
            ("self mention", _mention_of(player), True),
            ("doppelganger mention", _dopp_mention(name="Alice"), False),
        ]

        for label, mention, _ in cases:
            ctx = _make_ctx(mentions=[mention])
            monster = (
                _make_monster("Alice")
                if label == "doppelganger mention" else None
            )
            game = _make_game(monster=monster, combatants=[])

            with (
                patch.object(
                    _rpg_util_path(),
                    "get_game_and_player",
                    new=AsyncMock(return_value=(game, player)),
                ),
                patch.object(
                    _rpg_util_path(),
                    "get_player",
                    new=AsyncMock(return_value=player),
                ),
                patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher"),
                patch(
                    "caldanai.lib.rpg.helpers.utils.Dispatcher",
                ) as dispatcher,
                patch(
                    "caldanai.lib.rpg.helpers.utils.choice",
                    side_effect=lambda pool: pool[0],
                ),
            ):
                await cog.target_part.callback(cog, ctx, part=None)

            sent = _dispatched_strings(dispatcher)
            expected = parse(RpgUserCommands._TARGET_DEAD_INVOKER_FLAVOR[0], player)
            assert expected in sent, (
                f"{label}: dead-invoker line did not fire; got {sent}"
            )

    @pytest.mark.asyncio
    async def test_doppelganger_disguise_routes_to_body_part_nudge(self):
        """If the mentioned player's display_name matches the current
        monster's name, that's the doppelganger wearing their face.
        We nudge toward the body-part flow rather than emit player
        flavor, since the mention resolves to 'the monster' in-world."""
        cog = RpgUserCommands(bot=MagicMock())
        player = _make_player(name="Alice")
        # The "player" being mentioned is actually the doppelganger
        # masquerading as a player named Bob — same display_name as
        # monster.name.
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(mentions=[mention])
        game = _make_game(
            monster=_make_monster("Bob"),
            combatants=[],
        )

        with (
            patch.object(
                _rpg_util_path(),
                "get_game_and_player",
                new=AsyncMock(return_value=(game, player)),
            ),
            patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
        ):
            await cog.target_part.callback(cog, ctx, part=None)

        sent = _dispatched_strings(dispatcher)
        assert any("$target <part>" in s for s in sent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rpg_util_path():
    """Import path for the patched ``RpgUtilities`` class. Pulled into
    a helper so a rename lands in one place."""
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    return RpgUtilities


def _make_player(name: str):
    """Minimal player-like actor: a real ``Creature`` (so the parser's
    pronoun / verb-agreement accessors work) with a ``member``
    attribute patched on for the in-handler ``.member == .member``
    self-identity check."""
    from caldanai.lib.rpg.creatures import Creature

    member = MagicMock()
    member.id = id(member)
    member.display_name = name
    p = Creature(
        name=name, atk="1d4", defense=0, dodge=5, health_max=20,
        gender="female", pronouns="she, her, hers, her, herself",
    )
    p.member = member
    p.user_id = member.id
    return p


def _mention_of(player):
    m = MagicMock()
    m.display_name = player.name
    m.id = player.member.id
    return m


def _dopp_mention(name: str):
    """Stand-in mention for a doppelganger-masquerading-as-player
    case: a Discord user whose display_name matches a monster
    ``name`` string. Exists so the dead-invoker cross-mention-type
    test can construct the doppelganger branch without a second
    real player."""
    m = MagicMock()
    m.display_name = name
    m.id = id(m)
    return m


def _make_monster(name: str):
    """Bare creature with a matching ``.name`` — enough for the
    doppelganger check. Full monster construction would drag in
    plugin discovery."""
    from caldanai.lib.rpg.creatures import Creature
    return Creature(
        name=name, atk="1d4", defense=0, dodge=5, health_max=10,
    )


def _make_game(monster, combatants):
    game = MagicMock()
    game.monster = monster
    game.combatants = combatants
    game.combat_targets = {}
    game.channel = MagicMock()
    return game


def _make_ctx(mentions):
    ctx = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = mentions
    return ctx


def _dispatched_strings(dispatcher_mock):
    """Flatten every string argument the handler handed to
    ``Dispatcher.add`` across all calls."""
    sent = []
    for call in dispatcher_mock.add.call_args_list:
        for arg in call.args[1:]:
            if isinstance(arg, str):
                sent.append(arg)
        for key, value in call.kwargs.items():
            if isinstance(value, str):
                sent.append(value)
    return sent
