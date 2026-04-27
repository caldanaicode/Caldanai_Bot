"""Tests for the ``$kill`` command's monster-vs-part argument grammar.

Background: ``$kill werewolf`` used to emit "No targetable part
matching 'werewolf' found. Attacking randomly." because every token
after ``$kill`` was treated as a body-part identifier. The wanted
shape is::

    $kill <monster> [<part>...]

with the leading monster token *peeled off* before parts are parsed.
Bare-part form (``$kill arm.left``) and bare-monster form
(``$kill werewolf`` alone) both join combat without warnings.

This module covers:

- ``_strip_leading_monster_token`` — the helper that decides whether
  the first whitespace-token is the monster name. Exact / word-token
  equality only (mirrors ``$look``'s ``_monster_matches_look_target``);
  fuzzy / prefix matching is deliberately NOT applied so single-letter
  part shortcuts like ``$kill h`` (head) keep working against any
  monster whose name happens to start with the same letter.
- The ``attack`` command callback end-to-end — joining combat with /
  without a leading monster token, with / without a part token, and
  the warning-suppression contract for the bare-monster form.
- Ambiguity pin: the leading-monster check is FIRST-TOKEN ONLY.
  ``$kill arm.left werewolf`` keeps today's "trailing token is an
  unknown part, drop silently" behavior; the part target wins.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin


# Ensure the plugin registry is populated for the find_plugin_classes
# branch — this module's tests rely on real plugin classes (Werewolf,
# Goblin) being reachable through the fuzzy resolver.
MonsterPlugin.load_plugins()


def _make_monster_creature(name: str = "goblin") -> Creature:
    """Bare ``Creature`` with body parts and a name. Not a plugin
    instance — the helper's word-token branch should still fire on it
    because the plugin-class fallback is gated on ``isinstance``."""
    c = Creature(
        name=name, atk="1d4", defense=2, dodge=5, health_max=20,
    )
    c.body_parts = [
        BodyPart(name="head", health_max=10),
        BodyPart(name="torso", health_max=20),
        BodyPart(name="arm.left", health_max=8),
        BodyPart(name="arm.right", health_max=8),
        BodyPart(name="leg.left", health_max=10),
        BodyPart(name="leg.right", health_max=10),
    ]
    return c


def _cog() -> RpgUserCommands:
    return RpgUserCommands(bot=None)


class TestStripLeadingMonsterToken:
    """Word-token / plugin-class peel logic for the leading argument."""

    def test_first_token_matches_creature_name_is_consumed(self):
        m = _make_monster_creature("goblin")
        remainder, consumed = _cog()._strip_leading_monster_token("goblin", m)
        assert consumed is True
        assert remainder == ""

    def test_first_token_with_trailing_part_is_consumed(self):
        m = _make_monster_creature("goblin")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "goblin arm.left", m,
        )
        assert consumed is True
        assert remainder == "arm.left"

    def test_first_token_word_token_match_against_multi_word_name(self):
        """Mirrors ``_monster_matches_look_target`` — a player typing
        ``hydra`` against a "hexed hydra" should still peel."""
        m = _make_monster_creature("hexed hydra")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "hydra arm.left", m,
        )
        assert consumed is True
        assert remainder == "arm.left"

    def test_part_token_first_does_not_consume(self):
        """The ambiguity case — ``arm.left`` is a part, the trailing
        ``goblin`` is irrelevant. We do NOT peel anything; the whole
        string flows through to part parsing as-is."""
        m = _make_monster_creature("goblin")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "arm.left goblin", m,
        )
        assert consumed is False
        assert remainder == "arm.left goblin"

    def test_unknown_first_token_does_not_consume(self):
        m = _make_monster_creature("goblin")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "nonexistent", m,
        )
        assert consumed is False
        assert remainder == "nonexistent"

    def test_empty_input_safe(self):
        m = _make_monster_creature("goblin")
        assert _cog()._strip_leading_monster_token(None, m) == (None, False)
        assert _cog()._strip_leading_monster_token("", m) == ("", False)
        assert _cog()._strip_leading_monster_token("   ", m) == ("   ", False)

    def test_no_monster_safe(self):
        remainder, consumed = _cog()._strip_leading_monster_token(
            "goblin arm.left", None,
        )
        assert consumed is False
        assert remainder == "goblin arm.left"

    def test_case_insensitive_name_match(self):
        m = _make_monster_creature("goblin")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "GOBLIN arm.left", m,
        )
        assert consumed is True
        assert remainder == "arm.left"

    def test_real_plugin_word_token_match(self):
        """A real ``Werewolf`` plugin instance — exact word-token
        match against ``self.name`` (``"werewolf"``) peels."""
        from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
        wolf = Werewolf()
        wolf.body_parts = [
            BodyPart(name="head", health_max=12),
            BodyPart(name="torso", health_max=24),
            BodyPart(name="arm.left", health_max=10),
            BodyPart(name="arm.right", health_max=10),
        ]

        remainder, consumed = _cog()._strip_leading_monster_token(
            "werewolf arm.left", wolf,
        )
        assert consumed is True
        assert remainder == "arm.left"

    def test_short_part_prefix_does_NOT_consume(self):
        """Regression pin: fuzzy monster-name matching MUST NOT
        consume single-letter part shortcuts. ``$kill h`` against a
        monster whose name starts with ``h`` (Hydra) MUST leave the
        ``h`` for ``find_parts`` to resolve to ``head`` — otherwise
        the player tries to target the head and silently gets
        random-attack instead. Same shape for ``t`` (torso) against
        Toad / MathTeacher, ``g`` against Goblin / Golem / Giant,
        ``b`` against Bandit / Bearowl, ``do`` against Doppelganger.

        The conflict guard is the mechanism: any token that
        ``monster.find_parts`` accepts is reserved for parts and
        cannot be peeled as the monster name.
        """
        m = _make_monster_creature("hydra")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "h", m,
        )
        assert consumed is False
        assert remainder == "h"

        # And against the more specific ``hexed hydra`` form.
        m2 = _make_monster_creature("hexed hydra")
        remainder2, consumed2 = _cog()._strip_leading_monster_token(
            "h", m2,
        )
        assert consumed2 is False
        assert remainder2 == "h"

    def test_fuzzy_prefix_match_against_word_in_name(self):
        """``$kill hyd`` against a "hexed hydra" should peel via
        prefix-of-any-word fuzzy match. ``"hyd"`` doesn't resolve to
        any body part (no ``find_parts`` hit), so the conflict guard
        is silent and the prefix branch fires."""
        m = _make_monster_creature("hexed hydra")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "hyd", m,
        )
        assert consumed is True
        assert remainder == ""

    def test_fuzzy_typo_match_via_difflib(self):
        """``$kill hdra`` against a "hexed hydra" — the typo path.
        Single dropped character gets caught by
        ``difflib.get_close_matches`` at the chosen cutoff. No
        body-part conflict, so the typo branch fires."""
        m = _make_monster_creature("hexed hydra")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "hdra", m,
        )
        assert consumed is True
        assert remainder == ""

    def test_fuzzy_typo_with_trailing_part(self):
        """``$kill hdra h.1`` — fuzzy peel of the leading typo,
        remainder flows into ``_parse_part_targets`` and resolves
        the part. Spec example."""
        m = _make_monster_creature("hexed hydra")
        # Add a numbered head variant so ``h.1`` is a sensible part
        # token to leave behind. (The helper itself doesn't care
        # about the remainder beyond "is non-empty"; the assertion
        # is that we hand it back unchanged.)
        m.body_parts.append(BodyPart(name="head.1", health_max=10))
        remainder, consumed = _cog()._strip_leading_monster_token(
            "hdra h.1", m,
        )
        assert consumed is True
        assert remainder == "h.1"

    def test_fuzzy_no_plausible_match_does_not_consume(self):
        """``$kill xyz`` against any monster — neither prefix-of-word
        nor a close-enough typo. Stays unconsumed so the existing
        'No targetable part' warning still fires."""
        m = _make_monster_creature("hexed hydra")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "xyz", m,
        )
        assert consumed is False
        assert remainder == "xyz"

    def test_fuzzy_prefix_match_against_simple_name(self):
        """Pure non-conflict consume: ``"bandi"`` against a bandit.
        No body part starts with ``"bandi"``, and ``"bandit"`` starts
        with ``"bandi"`` — prefix-of-word peels."""
        m = _make_monster_creature("bandit")
        remainder, consumed = _cog()._strip_leading_monster_token(
            "bandi", m,
        )
        assert consumed is True
        assert remainder == ""


# ---------------------------------------------------------------------------
# attack-command integration tests
# ---------------------------------------------------------------------------


class TestKillCommandGrammar:
    """End-to-end tests for the four wanted-shape rows in the design memo:

    - ``$kill <monster>`` — joins combat, no targets, no warning.
    - ``$kill <monster> <part>`` — joins combat targeting that part.
    - ``$kill <part>`` — bare-part form unchanged.
    - ``$kill <unknown>`` — still warns (token wasn't the monster).
    """

    @pytest.mark.asyncio
    async def test_bare_monster_joins_combat_no_warning(self):
        cog = RpgUserCommands(bot=MagicMock())
        monster = _make_monster_creature("goblin")
        game = _make_game(monster=monster, combatants=[])
        player = _make_player("Alice")

        await _invoke_attack(cog, game, player, target="goblin")

        sent = _dispatched_strings(_dispatcher_for(game))
        assert player in game.combatants
        assert game.combat_targets[player.user_id] is None
        assert not any("No targetable part" in s for s in sent)
        assert any("prepares to attack" in s for s in sent)

    @pytest.mark.asyncio
    async def test_monster_plus_part_targets_part(self):
        cog = RpgUserCommands(bot=MagicMock())
        monster = _make_monster_creature("goblin")
        game = _make_game(monster=monster, combatants=[])
        player = _make_player("Alice")

        await _invoke_attack(cog, game, player, target="goblin arm.left")

        sent = _dispatched_strings(_dispatcher_for(game))
        assert player in game.combatants
        assert game.combat_targets[player.user_id] == ["arm.left"]
        assert not any("No targetable part" in s for s in sent)
        assert any("targeting the left arm" in s for s in sent)

    @pytest.mark.asyncio
    async def test_bare_part_targets_part(self):
        """Today's behavior — a bare part token still joins combat
        and targets the part, no monster token needed."""
        cog = RpgUserCommands(bot=MagicMock())
        monster = _make_monster_creature("goblin")
        game = _make_game(monster=monster, combatants=[])
        player = _make_player("Alice")

        await _invoke_attack(cog, game, player, target="arm.left")

        sent = _dispatched_strings(_dispatcher_for(game))
        assert player in game.combatants
        assert game.combat_targets[player.user_id] == ["arm.left"]
        assert not any("No targetable part" in s for s in sent)
        assert any("targeting the left arm" in s for s in sent)

    @pytest.mark.asyncio
    async def test_unknown_token_still_warns(self):
        """Token that's neither the monster nor a part should keep
        emitting the existing 'no targetable part' warning."""
        cog = RpgUserCommands(bot=MagicMock())
        monster = _make_monster_creature("goblin")
        game = _make_game(monster=monster, combatants=[])
        player = _make_player("Alice")

        await _invoke_attack(cog, game, player, target="nonexistent")

        sent = _dispatched_strings(_dispatcher_for(game))
        assert player in game.combatants
        assert game.combat_targets[player.user_id] is None
        assert any(
            "No targetable part matching 'nonexistent'" in s for s in sent
        )

    @pytest.mark.asyncio
    async def test_part_first_then_monster_targets_part_no_warning(self):
        """Ambiguity pin: leading-token check is FIRST-TOKEN ONLY.
        ``$kill arm.left werewolf`` keeps today's behavior — the
        leading ``arm.left`` resolves as a part, the trailing
        ``werewolf`` is an unknown token (silently dropped by
        ``_parse_part_targets``). No warning, single part target."""
        cog = RpgUserCommands(bot=MagicMock())
        # Monster name distinct from any part so the trailing token
        # genuinely *would* match the monster if the check weren't
        # first-token-only.
        monster = _make_monster_creature("werewolf")
        game = _make_game(monster=monster, combatants=[])
        player = _make_player("Alice")

        await _invoke_attack(cog, game, player, target="arm.left werewolf")

        sent = _dispatched_strings(_dispatcher_for(game))
        assert player in game.combatants
        assert game.combat_targets[player.user_id] == ["arm.left"]
        assert not any("No targetable part" in s for s in sent)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rpg_util_path():
    from caldanai.lib.rpg.helpers.utils import RpgUtilities
    return RpgUtilities


def _make_player(name: str):
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


def _make_game(monster, combatants):
    game = MagicMock()
    game.monster = monster
    game.combatants = list(combatants)
    game.combat_targets = {}
    game.channel = MagicMock()
    return game


def _make_ctx():
    ctx = MagicMock()
    ctx.message = MagicMock()
    ctx.message.mentions = []
    return ctx


async def _invoke_attack(cog, game, player, target):
    """Drive the ``attack`` command callback under patched
    Dispatcher / RpgUtilities. Stashes the dispatcher mock on
    ``game._dispatcher`` so ``_dispatcher_for`` can dig it back out."""
    ctx = _make_ctx()
    with (
        patch.object(
            _rpg_util_path(),
            "get_game_and_player",
            new=AsyncMock(return_value=(game, player)),
        ),
        patch("caldanai.lib.cogs.rpg_user_commands.Dispatcher") as dispatcher,
        # dead_invoker_guard reads ``RpgUtilities.dead_invoker_guard`` —
        # patch it at the class-attribute level so the live player
        # check (``player.is_dead()``) is bypassed for these tests
        # without needing to wire up a full Player.
        patch.object(
            _rpg_util_path(),
            "dead_invoker_guard",
            return_value=False,
        ),
    ):
        await cog.attack.callback(cog, ctx, target=target)
        game._dispatcher = dispatcher


def _dispatcher_for(game):
    return game._dispatcher


def _dispatched_strings(dispatcher_mock):
    sent = []
    for call in dispatcher_mock.add.call_args_list:
        for arg in call.args[1:]:
            if isinstance(arg, str):
                sent.append(arg)
        for key, value in call.kwargs.items():
            if isinstance(value, str):
                sent.append(value)
    return sent
