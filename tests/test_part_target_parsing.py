"""Tests for fuzzy body-part target parsing in ``RpgUserCommands``.

Covers ``_parse_part_targets`` — the command-layer adapter that turns
``$kill leg.r`` into a canonical list of part-name strings for
``Game.combat_targets`` and downstream ``do_attack`` resolution.

Post-Step-3 of the fuzzy-resolve dispatcher migration, per-token
resolution flows through :func:`fuzzy_resolve` against
:class:`PartConverter`. The dispatcher consults
``RpgUtilities.get_game(ctx)`` to reach the spawned monster, so each
test patches that helper to return a stub game with the wanted
monster — the asserted behaviour (canonicalisation, dedup, ambiguous
expansion, destroyed-part skip) is unchanged from the pre-dispatcher
shape.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.cogs.rpg_user_commands import RpgUserCommands
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart


def _make_monster() -> Creature:
    c = Creature(
        name="goblin", atk="1d4", defense=2, dodge=5, health_max=20,
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


def _stub_game(monster):
    game = MagicMock()
    game.monster = monster
    return game


async def _parse(target_str, monster):
    """Drive ``_parse_part_targets`` against a patched
    ``RpgUtilities.get_game`` so the dispatcher's ``PartConverter``
    sees the test-supplied monster. The ``ctx`` is a bare MagicMock
    — the converter only uses it as a key for ``get_game``."""
    from caldanai.lib.rpg.helpers.utils import RpgUtilities

    ctx = MagicMock()
    with patch.object(
        RpgUtilities,
        "get_game",
        new=AsyncMock(return_value=_stub_game(monster)),
    ):
        return await _cog()._parse_part_targets(ctx, target_str)


class TestParsePartTargets:
    @pytest.mark.asyncio
    async def test_exact_dotted_name_canonical(self):
        assert await _parse("leg.right", _make_monster()) == ["leg.right"]

    @pytest.mark.asyncio
    async def test_fuzzy_abbreviation_canonicalises(self):
        """``leg.r`` must resolve to ``leg.right`` so display renders
        as 'the right leg' rather than 'the r leg'."""
        assert await _parse("leg.r", _make_monster()) == ["leg.right"]
        assert await _parse("leg.l", _make_monster()) == ["leg.left"]

    @pytest.mark.asyncio
    async def test_ambiguous_token_expands_to_canonical_names(self):
        """``leg`` matches both legs — expand to both canonical names
        so display renders cleanly and ``do_attack`` can distribute one
        name per source slot."""
        assert await _parse("leg", _make_monster()) == [
            "leg.left", "leg.right",
        ]

    @pytest.mark.asyncio
    async def test_short_ambiguous_token_expands_all_matches(self):
        """``h`` matches head and anything else containing 'h' — every
        match contributes a canonical entry. Guards against the
        regression where ambiguous tokens rendered as 'the h'."""
        m = _make_monster()
        m.body_parts.append(BodyPart(name="hand.left", health_max=6))
        m.body_parts.append(BodyPart(name="hand.right", health_max=6))

        result = await _parse("h", m)
        assert result == ["head", "hand.left", "hand.right"]

    @pytest.mark.asyncio
    async def test_multiple_tokens(self):
        result = await _parse("arm.l leg.r", _make_monster())
        assert result == ["arm.left", "leg.right"]

    @pytest.mark.asyncio
    async def test_unknown_tokens_are_skipped(self):
        """Monster name or gibberish should silently drop out."""
        result = await _parse("goblin arm.l", _make_monster())
        assert result == ["arm.left"]

    @pytest.mark.asyncio
    async def test_duplicate_canonicalised_targets_deduped(self):
        """``leg.r leg.right`` both resolve to ``leg.right`` — keep one."""
        result = await _parse("leg.r leg.right", _make_monster())
        assert result == ["leg.right"]

    @pytest.mark.asyncio
    async def test_empty_input(self):
        assert await _parse("", _make_monster()) == []
        assert await _parse(None, _make_monster()) == []

    @pytest.mark.asyncio
    async def test_monster_without_body_parts(self):
        partless = Creature(name="slime", atk="1d4", defense=0, dodge=0, health_max=10)
        assert await _parse("anything", partless) == []

    @pytest.mark.asyncio
    async def test_destroyed_part_is_skipped(self):
        """A fuzzy abbreviation that would resolve to a destroyed part
        must drop out so the 'no targetable part' warning can fire."""
        m = _make_monster()
        left_leg = next(p for p in m.body_parts if p.name == "leg.left")
        left_leg.health = 0
        assert left_leg.is_destroyed()

        assert await _parse("leg.l", m) == []
        # Sibling on the same base still resolves via fuzzy.
        assert await _parse("leg.r", m) == ["leg.right"]

    @pytest.mark.asyncio
    async def test_bare_part_alongside_dotted_siblings_prefers_exact(self):
        """With a bare ``tail`` part plus ``tail.tip``, typing ``tail``
        must hit only the bare part (exact-match precedence)."""
        m = _make_monster()
        m.body_parts.append(BodyPart(name="tail", health_max=10))
        m.body_parts.append(BodyPart(name="tail.tip", health_max=5))

        assert await _parse("tail", m) == ["tail"]
        # Dotted abbreviation still reaches the child.
        assert await _parse("tail.t", m) == ["tail.tip"]

    @pytest.mark.asyncio
    async def test_whitespace_only_input(self):
        assert await _parse("   ", _make_monster()) == []


class TestDisplayTargets:
    """``_display_targets`` resolves codified names back to the owning
    :class:`BodyPart` so label rendering goes through the canonical
    ``_display_with_article`` logic. Falls back to string-only rendering
    when resolution fails (destroyed / missing / no monster)."""

    def test_dotted_directional_renders_with_article(self):
        assert _cog()._display_targets(["arm.left"], _make_monster()) == "the left arm"

    def test_bare_name_renders_with_article(self):
        assert _cog()._display_targets(["torso"], _make_monster()) == "the torso"

    def test_numeric_qualifier_omits_article(self):
        m = _make_monster()
        m.body_parts.append(BodyPart(name="head.2", health_max=10))
        assert _cog()._display_targets(["head.2"], m) == "head 2"

    def test_multiple_joined_with_and(self):
        assert (
            _cog()._display_targets(["arm.left", "leg.right"], _make_monster())
            == "the left arm and the right leg"
        )

    def test_mixed_numeric_and_directional(self):
        m = _make_monster()
        m.body_parts.append(BodyPart(name="head.2", health_max=10))
        assert (
            _cog()._display_targets(["head.2", "torso"], m)
            == "head 2 and the torso"
        )

    def test_destroyed_part_falls_back_to_string_logic(self):
        """If the named part is gone (e.g. destroyed between parse and
        display), ``find_parts`` won't return it — degrade gracefully."""
        m = _make_monster()
        left_arm = next(p for p in m.body_parts if p.name == "arm.left")
        left_arm.health = 0
        assert _cog()._display_targets(["arm.left"], m) == "the left arm"

    def test_no_monster_falls_back_to_string_logic(self):
        assert _cog()._display_targets(["arm.left"], None) == "the left arm"
        assert _cog()._display_targets(["head.2"], None) == "head 2"
        assert _cog()._display_targets(["torso"], None) == "the torso"

    def test_empty_list_renders_empty_string(self):
        assert _cog()._display_targets([], _make_monster()) == ""
