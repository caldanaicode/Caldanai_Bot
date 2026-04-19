"""Tests for V2 of the social-command expansion.

Covers the nine new warmth-aware interactive commands (``$salute``,
``$comfort``, ``$poke``, ``$nod``, ``$glare``, ``$shank``, ``$tickle``,
``$taunt``, ``$wink``) and the five new self-directed commands
(``$pose``, ``$cheer``, ``$cry``, ``$wave``, ``$bow``).

Pattern mirrors ``tests/test_warmth.py``:
- ``_make_player`` / ``_make_ctx`` / ``_dispatched`` helpers.
- Parametrized pool-shape + parse sweep.
- Self-target, dead-invoker, and dead-target routing checks.

Kept in a separate file (rather than extended into ``test_warmth.py``)
so the v2 batch can grow or shrink without churning the v1 test
surface, and so a reviewer can scope their sweep to the new commands
by loading one file.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_social_commands import (
    RpgSocialCommands,
    _DEAD_INVOKER_FLAVOR,
    _DEAD_TARGET_FLAVOR,
    _NARRATION_POOLS,
    _SELF_DIRECTED_POOLS,
    _SELF_TARGET_LINES,
    _render_self_directed,
    _render_social,
)
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers import warmth
from caldanai.lib.rpg.helpers.parser import parse


# ---------------------------------------------------------------------------
# Helpers — copied from test_warmth.py so this file is self-contained.
# ---------------------------------------------------------------------------


def _make_player(name="Alice", uid=42):
    from bson.objectid import ObjectId

    p = Player(
        pid=ObjectId(),
        gid=100,
        uid=uid,
        weight_limit=100,
        clarks=0,
        defense=6,
        dodge=6,
        health=20,
        health_max=20,
        gender="female",
        pronouns="she,her,hers,her",
    )
    member = MagicMock()
    member.id = uid
    member.display_name = name
    p.member = member
    p.name = name
    return p


def _make_ctx(author, mentions=None, guild=True):
    ctx = MagicMock()
    ctx.author = author.member
    ctx.prefix = "$"
    ctx.guild = MagicMock() if guild else None
    ctx.channel = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = mentions or []
    ctx.invoked_with = "test"
    return ctx


def _dispatched(dispatcher_mock):
    pairs = []
    for call in dispatcher_mock.add.call_args_list:
        args = call.args
        channel = args[0] if args else None
        text = args[1] if len(args) > 1 else call.kwargs.get("text")
        pairs.append((channel, text))
    return pairs


def _rpg_util():
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    return RpgUtilities


# ---------------------------------------------------------------------------
# Canonical command lists — single source for the parametrize sweeps.
# ---------------------------------------------------------------------------


_V2_INTERACTIVE_COMMANDS = (
    "salute",
    "comfort",
    "poke",
    "nod",
    "glare",
    "shank",
    "tickle",
    "taunt",
    "wink",
)


_V2_SELF_DIRECTED_COMMANDS = (
    "pose",
    "cheer",
    "cry",
    "wave",
    "bow",
)


_ALL_V2_COMMANDS = _V2_INTERACTIVE_COMMANDS + _V2_SELF_DIRECTED_COMMANDS


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    """Each new command must be visible on the cog; each warmth-aware
    command must be registered in SOCIAL_COMMANDS + SYSTEM_DEFAULTS."""

    @pytest.mark.parametrize("cmd", _ALL_V2_COMMANDS)
    def test_command_is_on_social_cog(self, cmd):
        assert hasattr(RpgSocialCommands, cmd), (
            f"RpgSocialCommands is missing the {cmd!r} command"
        )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_warmth_aware_command_is_registered(self, cmd):
        """Every warmth-aware command must be in the SOCIAL_COMMANDS
        tuple (so ``$warmth set <cmd> ...`` accepts it) and have a
        SYSTEM_DEFAULTS entry (so the resolver has a fallback)."""
        assert cmd in warmth.SOCIAL_COMMANDS
        assert cmd in warmth.SYSTEM_DEFAULTS
        assert isinstance(warmth.SYSTEM_DEFAULTS[cmd], warmth.Warmth)

    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    def test_self_directed_command_not_in_warmth_registry(self, cmd):
        """Self-directed commands are not warmth-aware — they must
        not be in SOCIAL_COMMANDS (or the $warmth subcommand would
        accept them and save a setting that never fires)."""
        assert cmd not in warmth.SOCIAL_COMMANDS
        assert cmd not in warmth.SYSTEM_DEFAULTS

    def test_system_defaults_match_spec(self):
        """Pin the exact system defaults per the v2 brief. Catches
        accidental re-tunes in a future PR."""
        expected = {
            "salute":  warmth.Warmth.NEUTRAL,
            "comfort": warmth.Warmth.WARM,
            "poke":    warmth.Warmth.COOL,
            "nod":     warmth.Warmth.NEUTRAL,
            "glare":   warmth.Warmth.COLD,
            "shank":   warmth.Warmth.COLD,
            "tickle":  warmth.Warmth.COOL,
            "taunt":   warmth.Warmth.COLD,
            "wink":    warmth.Warmth.NEUTRAL,
        }
        for cmd, level in expected.items():
            assert warmth.SYSTEM_DEFAULTS[cmd] == level, (
                f"{cmd} should default to {level}, got "
                f"{warmth.SYSTEM_DEFAULTS[cmd]}"
            )

    def test_v1_defaults_unchanged(self):
        """Regression: the v1 hug/high_five/fistbump defaults must not
        have drifted while we added v2."""
        assert warmth.SYSTEM_DEFAULTS["hug"] == warmth.Warmth.COOL
        assert warmth.SYSTEM_DEFAULTS["high_five"] == warmth.Warmth.NEUTRAL
        assert warmth.SYSTEM_DEFAULTS["fistbump"] == warmth.Warmth.NEUTRAL


# ---------------------------------------------------------------------------
# Pool shape
# ---------------------------------------------------------------------------


class TestInteractivePoolShape:
    """Every warmth-aware command's pools must cover all five levels
    with 3+ unique variants and parse cleanly."""

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_narration_pools_exist(self, cmd):
        assert cmd in _NARRATION_POOLS, (
            f"{cmd} missing from _NARRATION_POOLS"
        )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_intent_pool_has_all_levels(self, cmd):
        intent_pool, _ = _NARRATION_POOLS[cmd]
        for level in warmth.Warmth:
            assert level in intent_pool, (
                f"{cmd} intent pool missing {level}"
            )
            assert len(intent_pool[level]) >= 3, (
                f"{cmd} intent {level} needs >=3 variants"
            )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_acceptance_pool_has_all_levels(self, cmd):
        _, acc_pool = _NARRATION_POOLS[cmd]
        for level in warmth.Warmth:
            assert level in acc_pool, (
                f"{cmd} acceptance pool missing {level}"
            )
            assert len(acc_pool[level]) >= 3, (
                f"{cmd} acceptance {level} needs >=3 variants"
            )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_every_line_parses_cleanly(self, cmd):
        """Narration lines must resolve all @1/@2 tokens — no stray
        unparsed tokens in the rendered output. Catches typos like
        @2n (missing form) or @1ss."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        intent_pool, acc_pool = _NARRATION_POOLS[cmd]
        for level, lines in intent_pool.items():
            for line in lines:
                rendered = parse(line, actor, target)
                assert "@1" not in rendered, (
                    f"{cmd} intent {level} stray @1 in: {rendered!r}"
                )
                assert "@2" not in rendered, (
                    f"{cmd} intent {level} stray @2 in: {rendered!r}"
                )
        for level, lines in acc_pool.items():
            for line in lines:
                rendered = parse(line, actor, target)
                assert "@1" not in rendered, (
                    f"{cmd} acceptance {level} stray @1 in: {rendered!r}"
                )
                assert "@2" not in rendered, (
                    f"{cmd} acceptance {level} stray @2 in: {rendered!r}"
                )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_dead_invoker_pool_exists(self, cmd):
        assert cmd in _DEAD_INVOKER_FLAVOR, (
            f"{cmd} missing from _DEAD_INVOKER_FLAVOR"
        )
        assert len(_DEAD_INVOKER_FLAVOR[cmd]) >= 3

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_dead_invoker_lines_parse(self, cmd):
        actor = _make_player("Alice", uid=1)
        for line in _DEAD_INVOKER_FLAVOR[cmd]:
            rendered = parse(line, actor)
            assert "@1" not in rendered, (
                f"{cmd} dead-invoker stray @1 in: {rendered!r}"
            )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_dead_target_pool_exists(self, cmd):
        assert cmd in _DEAD_TARGET_FLAVOR, (
            f"{cmd} missing from _DEAD_TARGET_FLAVOR"
        )
        assert len(_DEAD_TARGET_FLAVOR[cmd]) >= 2

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_dead_target_lines_parse(self, cmd):
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        for line in _DEAD_TARGET_FLAVOR[cmd]:
            rendered = parse(line, actor, target)
            assert "@1" not in rendered, (
                f"{cmd} dead-target stray @1 in: {rendered!r}"
            )
            assert "@2" not in rendered, (
                f"{cmd} dead-target stray @2 in: {rendered!r}"
            )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_self_target_line_exists_and_parses(self, cmd):
        actor = _make_player("Alice", uid=1)
        line = _SELF_TARGET_LINES.get(cmd)
        assert line, f"{cmd} missing from _SELF_TARGET_LINES"
        rendered = parse(line, actor)
        assert "@1" not in rendered


# ---------------------------------------------------------------------------
# Self-directed pool shape
# ---------------------------------------------------------------------------


class TestSelfDirectedPoolShape:
    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    def test_pool_exists(self, cmd):
        assert cmd in _SELF_DIRECTED_POOLS
        # Brief calls for 6-10 variants; assert >=6 as the lower bound.
        assert len(_SELF_DIRECTED_POOLS[cmd]) >= 6

    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    def test_lines_parse(self, cmd):
        actor = _make_player("Alice", uid=1)
        for line in _SELF_DIRECTED_POOLS[cmd]:
            rendered = parse(line, actor)
            assert "@1" not in rendered, (
                f"{cmd} self-directed stray @1 in: {rendered!r}"
            )
            # Self-directed lines must not reference @2 at all.
            assert "@2" not in line, (
                f"{cmd} self-directed line references @2: {line!r}"
            )

    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    def test_dead_invoker_pool_exists(self, cmd):
        assert cmd in _DEAD_INVOKER_FLAVOR
        assert len(_DEAD_INVOKER_FLAVOR[cmd]) >= 3

    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    def test_dead_invoker_lines_parse(self, cmd):
        actor = _make_player("Alice", uid=1)
        for line in _DEAD_INVOKER_FLAVOR[cmd]:
            rendered = parse(line, actor)
            assert "@1" not in rendered


# ---------------------------------------------------------------------------
# Cold-acceptance asymmetry — non-negotiable invariant.
# ---------------------------------------------------------------------------


class TestColdAcceptanceAsymmetry:
    """For every warmth-aware command, cold-acceptance must always
    read as rejection regardless of actor intent. The reviewer will
    sweep this specifically — cold-accept is the load-bearing asymmetry
    pool."""

    # Rejection-keyword dictionary: each cold-acceptance line for a
    # given command must contain at least one of these markers. Small
    # deliberate overlap (``step``, ``not``, etc.) so each line doesn't
    # have to pick a specific word, but the overall pool still signals
    # refusal loud and clear.
    _REJECTION_MARKERS = {
        "salute": (
            "not return", "unacknowledged", "looks away",
            "refuses", "disinterested",
        ),
        "comfort": (
            "stiffens", "steps out", "don't", "declines",
            "withdraws",
        ),
        "poke": (
            "swats", "drops it", "stops",
            "step", "unamused", "out of",
        ),
        "nod": (
            # Markers match POST-substitution text (``@2a`` → "her"/"his").
            # "head away" is the distinctive cold-accept phrase;
            # other levels don't use it.
            "straight past", "dies on the air",
            "does not reciprocate", "head away",
        ),
        "glare": (
            "right through", "ignores", "bored", "walks",
            "yawn", "declines",
        ),
        "shank": (
            "not find", "out of reach", "kills the bit",
            "shakes", "declines",
        ),
        "tickle": (
            # Bare "not" was too loose — substring-matches innocuous
            # words like "notion" or "nothing". Scoped to specific
            # rejection phrases that appear only in cold-accept.
            "catches", "out of range", "ice", "blocks",
            "absolutely not",
        ),
        "taunt": (
            "not take", "bored", "ignores", "stares",
            "walks away",
        ),
        "wink": (
            "not return", "straight through", "declines",
            "unanswered", "glacial", "stare",
        ),
    }

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_cold_accept_reads_as_rejection(self, cmd):
        _, acc_pool = _NARRATION_POOLS[cmd]
        markers = self._REJECTION_MARKERS[cmd]
        for line in acc_pool[warmth.Warmth.COLD]:
            lower = line.lower()
            assert any(m in lower for m in markers), (
                f"cold-accept {cmd} line lacks rejection marker: {line!r}"
            )

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_warm_intent_cold_accept_still_refuses(self, cmd):
        """Under the worst-case asymmetry (warm intent + cold accept),
        the rendered narration must still contain a rejection marker
        from the cold-acceptance pool. Pins the invariant end-to-end
        rather than just pool-side."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        warmth.set_default(actor, cmd, warmth.Warmth.WARM)
        warmth.set_default(target, cmd, warmth.Warmth.COLD)

        markers = self._REJECTION_MARKERS[cmd]
        # Sample several rolls so the determinism doesn't hide a pool
        # line that quietly softened.
        for _ in range(20):
            out = _render_social(cmd, actor, target)
            lower = out.lower()
            assert any(m in lower for m in markers), (
                f"{cmd} warm-intent/cold-accept missing rejection: {out!r}"
            )


# ---------------------------------------------------------------------------
# _render_social routing — self-target, live-target, dead-target.
# ---------------------------------------------------------------------------


class TestRenderSocialRouting:
    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_self_target_short_circuits(self, cmd):
        """Self-targeting a warmth-aware command must render the
        per-command self-target line instead of running through the
        resolver."""
        p = _make_player("Alice", uid=1)
        out = _render_social(cmd, p, p)
        # Rendered line must reference Alice.
        assert "alice" in out.lower()
        # No stray tokens.
        assert "@1" not in out
        assert "@2" not in out
        # Must match one of the self-target templates for this command
        # rendered with Alice. Redundant with the explicit
        # _SELF_TARGET_LINES check, but pins the dispatch.
        expected = parse(_SELF_TARGET_LINES[cmd], p)
        assert out == expected

    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    def test_live_target_produces_two_clause_output(self, cmd):
        """A non-self, live target routes through the resolver and
        produces an intent-beat + acceptance-beat sentence."""
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        out = _render_social(cmd, actor, target)
        assert "@1" not in out
        assert "@2" not in out
        # Both actor names should appear somewhere (most beats use
        # @1 and @2 at least once; pronouns cover the rest).
        # We can't strictly assert "Alice" and "Bob" both appear
        # because acceptance beats sometimes use only pronouns for @1,
        # but at minimum one name must be present.
        assert "alice" in out.lower() or "bob" in out.lower()


class TestRenderSelfDirected:
    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    def test_renders_from_pool(self, cmd):
        actor = _make_player("Alice", uid=1)
        out = _render_self_directed(cmd, actor)
        assert "@1" not in out
        assert "alice" in out.lower()


# ---------------------------------------------------------------------------
# No duplicate lines across any pool.
# ---------------------------------------------------------------------------


class TestNoDuplicateLines:
    """Collect every V2-owned flavor line and assert uniqueness. A
    duplicate across pools defeats variety; a duplicate within a pool
    makes the random pick feel broken."""

    def _collect_v2_lines(self):
        lines = []
        # Warmth-aware pools for each v2 interactive command.
        for cmd in _V2_INTERACTIVE_COMMANDS:
            intent_pool, acc_pool = _NARRATION_POOLS[cmd]
            for level_lines in intent_pool.values():
                lines.extend(level_lines)
            for level_lines in acc_pool.values():
                lines.extend(level_lines)
            lines.extend(_DEAD_TARGET_FLAVOR.get(cmd, []))
            lines.extend(_DEAD_INVOKER_FLAVOR.get(cmd, []))
            self_line = _SELF_TARGET_LINES.get(cmd)
            if self_line:
                lines.append(self_line)
        # Self-directed pools.
        for cmd in _V2_SELF_DIRECTED_COMMANDS:
            lines.extend(_SELF_DIRECTED_POOLS[cmd])
            lines.extend(_DEAD_INVOKER_FLAVOR.get(cmd, []))
        return lines

    def test_all_v2_lines_unique(self):
        lines = self._collect_v2_lines()
        seen = set()
        duplicates = []
        for line in lines:
            if line in seen:
                duplicates.append(line)
            else:
                seen.add(line)
        assert not duplicates, (
            f"Found duplicate narration line(s): {duplicates}"
        )


# ---------------------------------------------------------------------------
# Command dispatch — dead invoker, dead target, self-target, live.
# ---------------------------------------------------------------------------


class TestInteractiveCommandDispatch:
    """Smoke tests per interactive command: dead-invoker fires the
    dead pool + short-circuits; dead-target uses the dead-target pool;
    live target goes through _render_social."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    async def test_dead_invoker_short_circuits(self, cmd):
        """Dead-invoker path must NOT reach the warmth resolver. The
        dispatched flavor line goes out via ``RpgUtilities`` (which
        imports ``Dispatcher`` from its own module, not this cog's),
        so we patch both to keep this assertion about routing rather
        than dispatcher internals."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        actor.health = 0
        assert actor.is_dead()
        target = _make_player("Bob", uid=2)
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
            patch("caldanai.lib.rpg.helpers.utils.Dispatcher") as util_disp,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        render_mock.assert_not_called()
        # Dead-invoker pool fires through RpgUtilities → utils.Dispatcher.
        pairs = _dispatched(util_disp)
        assert pairs, f"{cmd} dead-invoker path produced no output"
        # The emitted line should be one of this command's dead-invoker
        # templates, rendered against the actor.
        emitted = [t for _, t in pairs if t]
        candidates = {
            parse(line, actor) for line in _DEAD_INVOKER_FLAVOR[cmd]
        }
        assert any(e in candidates for e in emitted), (
            f"{cmd} dead-invoker emission not from pool: {emitted}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    async def test_dead_target_uses_dead_target_pool(self, cmd):
        cog = RpgSocialCommands(bot=MagicMock())
        cog.bot.user = MagicMock()  # distinct from any mention
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        target.health = 0
        assert target.is_dead()
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        # Warmth path must NOT fire for a dead target.
        render_mock.assert_not_called()
        # Output should come from the dead-target pool. We can't match
        # an exact line (rng) but at minimum one line was emitted.
        pairs = _dispatched(dispatcher)
        assert pairs, f"{cmd} dead-target path produced no output"
        # The emitted text should be one of the dead-target templates
        # (rendered through parse). Reconstruct each candidate and
        # check membership.
        emitted = [t for _, t in pairs if t]
        candidates = {
            parse(line, actor, target)
            for line in _DEAD_TARGET_FLAVOR[cmd]
        }
        assert any(e in candidates for e in emitted), (
            f"{cmd} dead-target emission did not match pool: "
            f"emitted={emitted}, candidates={candidates}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    async def test_live_target_routes_through_render_social(self, cmd):
        cog = RpgSocialCommands(bot=MagicMock())
        cog.bot.user = MagicMock()
        actor = _make_player("Alice", uid=1)
        target = _make_player("Bob", uid=2)
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch.object(
                _rpg_util(), "get_player",
                new=AsyncMock(return_value=target),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
                return_value="rendered",
            ) as render_mock,
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        render_mock.assert_called_once()
        call_cmd, call_actor, call_target = render_mock.call_args.args
        assert call_cmd == cmd
        assert call_actor is actor
        assert call_target is target

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    async def test_no_mention_emits_italicized_fallback(self, cmd):
        """No mention → italicized "no target" fallback line. The
        resolver must not fire."""
        cog = RpgSocialCommands(bot=MagicMock())
        cog.bot.user = MagicMock()
        actor = _make_player("Alice", uid=1)
        ctx = _make_ctx(actor, mentions=[])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        render_mock.assert_not_called()
        pairs = _dispatched(dispatcher)
        assert pairs
        # Fallback lines are italicized (surrounded by asterisks).
        texts = [t for _, t in pairs if t]
        assert any(
            t.startswith("*") and t.endswith("*")
            for t in texts
        ), f"{cmd} no-target line not italicized: {texts}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_INTERACTIVE_COMMANDS)
    async def test_bot_mention_emits_scripted_reply(self, cmd):
        """Mentioning the bot short-circuits to a scripted reply; the
        resolver must not fire (warmth against the bot is never
        consulted)."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        # Mention the bot itself.
        ctx = _make_ctx(actor, mentions=[cog.bot.user])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        render_mock.assert_not_called()
        pairs = _dispatched(dispatcher)
        assert pairs, f"{cmd} bot-mention path produced no output"


class TestSelfDirectedCommandDispatch:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    async def test_emits_self_directed_flavor(self, cmd):
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        ctx = _make_ctx(actor, mentions=[])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        pairs = _dispatched(dispatcher)
        assert pairs, f"{cmd} produced no output"
        emitted = [t for _, t in pairs if t]
        # The emitted line must come from this command's pool
        # (rendered with actor's name).
        candidates = {parse(line, actor) for line in _SELF_DIRECTED_POOLS[cmd]}
        assert any(e in candidates for e in emitted), (
            f"{cmd} emitted line not from pool: emitted={emitted}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    async def test_dead_invoker_fires_dead_pool(self, cmd):
        """Same routing note as the interactive case: the dead-invoker
        flavor line dispatches through ``RpgUtilities`` → utils'
        own ``Dispatcher`` import, so we patch both."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        actor.health = 0
        assert actor.is_dead()
        ctx = _make_ctx(actor, mentions=[])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch("caldanai.lib.cogs.rpg_social_commands.Dispatcher"),
            patch("caldanai.lib.rpg.helpers.utils.Dispatcher") as util_disp,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        pairs = _dispatched(util_disp)
        assert pairs, f"{cmd} dead-invoker produced no output"
        emitted = [t for _, t in pairs if t]
        candidates = {
            parse(line, actor) for line in _DEAD_INVOKER_FLAVOR[cmd]
        }
        assert any(e in candidates for e in emitted), (
            f"{cmd} dead-invoker line not from pool: emitted={emitted}"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", _V2_SELF_DIRECTED_COMMANDS)
    async def test_mention_is_ignored_not_crash(self, cmd):
        """Self-directed commands tolerate (but ignore) a passed
        mention. No crash, no render-social dispatch, still emits
        one self-directed line."""
        cog = RpgSocialCommands(bot=MagicMock())
        actor = _make_player("Alice", uid=1)
        mention = MagicMock()
        mention.display_name = "Bob"
        ctx = _make_ctx(actor, mentions=[mention])
        ctx.invoked_with = cmd
        game = MagicMock()
        game.channel = MagicMock()

        with (
            patch.object(
                _rpg_util(), "get_game_and_player",
                new=AsyncMock(return_value=(game, actor)),
            ),
            patch(
                "caldanai.lib.cogs.rpg_social_commands._render_social",
            ) as render_mock,
            patch(
                "caldanai.lib.cogs.rpg_social_commands.Dispatcher",
            ) as dispatcher,
        ):
            handler = getattr(cog, cmd)
            await handler.callback(cog, ctx)

        # render_social is for two-actor commands; must not fire here.
        render_mock.assert_not_called()
        # Output still came through.
        pairs = _dispatched(dispatcher)
        assert pairs
        # And is a self-directed line, not a two-actor line.
        emitted = [t for _, t in pairs if t]
        candidates = {parse(line, actor) for line in _SELF_DIRECTED_POOLS[cmd]}
        assert any(e in candidates for e in emitted)
