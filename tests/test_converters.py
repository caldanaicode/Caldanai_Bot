"""Tests for the discord.py Converter family in
:mod:`caldanai.lib.rpg.helpers.converters`.

Covers each converter's no-match / single-match / ambiguous-match
paths and the underlying free resolver helpers. Each converter is
exercised through ``.convert(ctx, argument)`` with mocked context.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from discord.ext.commands import BadArgument

from caldanai.lib.rpg.helpers.converters import (
    CreatureConverter,
    FuzzyMemberConverter,
    MonsterClassConverter,
    MonsterConverter,
    PartConverter,
    PlayerConverter,
    RecipeConverter,
)
from caldanai.lib.rpg.helpers.resolvers import (
    resolve_active_monster,
    resolve_monster_class,
    resolve_part,
    resolve_player,
    resolve_recipe,
)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_monster(name: str, *, parts=None) -> Creature:
    """Real ``Creature`` so ``matches_token`` / ``find_parts`` work
    against it without further mocking."""
    c = Creature(
        name=name,
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=20,
        health=20,
        gender="male",
    )
    c.body_parts = list(parts or [])
    return c


def _make_part(name: str, health_max: int = 10) -> BodyPart:
    return BodyPart(name=name, health_max=health_max)


def _make_player(name: str, *, member=None):
    """Player stand-in. Uses SimpleNamespace because tests don't need
    the full Player constructor and :func:`resolve_player` only reads
    ``.name`` and ``.member.{display_name,name}``."""
    return SimpleNamespace(name=name, member=member)


def _make_member(display_name: str, username: str = None):
    m = MagicMock()
    m.display_name = display_name
    m.name = username or display_name
    return m


def _make_game(*, monster=None, players=None):
    g = MagicMock()
    g.monster = monster
    g.player_manager = MagicMock()
    g.player_manager.players = {
        i: p for i, p in enumerate(players or [])
    }
    return g


def _patch_get_game(game):
    return patch(
        "caldanai.lib.rpg.helpers.converters.RpgUtilities.get_game",
        new=AsyncMock(return_value=game),
    )


def _patch_get_player(player):
    return patch(
        "caldanai.lib.rpg.helpers.converters.RpgUtilities.get_player",
        new=AsyncMock(return_value=player),
    )


# ---------------------------------------------------------------------------
# Free resolver helpers
# ---------------------------------------------------------------------------


class TestResolveMonsterClass:
    def test_known_monster_resolves(self):
        # Real registry — goblin is a known plugin.
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        assert resolve_monster_class("goblin") == [Goblin]

    def test_unknown_monster_returns_empty(self):
        assert resolve_monster_class("definitely_not_a_monster_xyz") == []


class TestResolveActiveMonster:
    def test_matching_query_returns_monster(self):
        m = _make_monster("hexed hydra")
        assert resolve_active_monster(m, "hydra") is m

    def test_non_matching_query_returns_none(self):
        m = _make_monster("goblin")
        assert resolve_active_monster(m, "dragon") is None

    def test_none_monster_returns_none(self):
        assert resolve_active_monster(None, "anything") is None

    def test_empty_query_returns_none(self):
        m = _make_monster("goblin")
        assert resolve_active_monster(m, "") is None

    def test_conflict_check_blocks_fuzzy(self):
        # ``conflict_check`` truthy short-circuits the fuzzy passes
        # but exact still wins. ``$kill h`` against a hydra: conflict
        # check is ``hydra.find_parts``, which returns [head]. Fuzzy
        # ``h`` -> ``hydra`` is suppressed.
        head = _make_part("head")
        m = _make_monster("hydra", parts=[head])
        # Without conflict_check, ``h`` matches via fuzzy prefix.
        assert resolve_active_monster(m, "h") is m
        # With conflict_check (find_parts returns [head]), ``h`` is
        # interpreted as the part shortcut and NOT a monster match.
        assert resolve_active_monster(
            m, "h", conflict_check=m.find_parts,
        ) is None


class TestResolvePlayer:
    def test_fuzzy_matches_display_name(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        bob = _make_player("Bob", member=_make_member("Bob"))
        game = _make_game(players=[alice, bob])
        assert resolve_player(game, "alic") == [alice]

    def test_fuzzy_matches_username(self):
        alice = _make_player(
            "Alice", member=_make_member("AliceDN", "alice_user"),
        )
        game = _make_game(players=[alice])
        assert resolve_player(game, "alice_user") == [alice]

    def test_returns_multiple_on_ambiguity(self):
        a1 = _make_player("Alice", member=_make_member("Alice"))
        a2 = _make_player("Alicia", member=_make_member("Alicia"))
        game = _make_game(players=[a1, a2])
        # SimpleNamespace fixtures aren't hashable (defines __eq__);
        # compare as a list and check both members are present.
        result = resolve_player(game, "ali")
        assert len(result) == 2
        assert a1 in result and a2 in result

    def test_no_member_falls_back_to_player_name(self):
        # Player without an attached Discord Member (cached/offline
        # session) still resolvable by their cached ``name``.
        alice = _make_player("Alice", member=None)
        game = _make_game(players=[alice])
        assert resolve_player(game, "alice") == [alice]

    def test_empty_query_returns_empty(self):
        game = _make_game(players=[_make_player("Alice")])
        assert resolve_player(game, "") == []

    def test_none_game_returns_empty(self):
        assert resolve_player(None, "alice") == []


class TestResolvePart:
    def test_matches_dot_segments(self):
        leg_l = _make_part("leg.left")
        leg_r = _make_part("leg.right")
        m = _make_monster("test", parts=[leg_l, leg_r])
        assert resolve_part(m, "leg.r") == [leg_r]

    def test_returns_multiple_for_ambiguous(self):
        leg_l = _make_part("leg.left")
        leg_r = _make_part("leg.right")
        m = _make_monster("test", parts=[leg_l, leg_r])
        assert set(resolve_part(m, "leg")) == {leg_l, leg_r}

    def test_no_match_returns_empty(self):
        m = _make_monster("test", parts=[_make_part("head")])
        assert resolve_part(m, "tail") == []

    def test_none_creature_returns_empty(self):
        assert resolve_part(None, "head") == []


class TestResolveRecipe:
    def test_known_recipe_resolves(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        # ``leather_jerkin`` is a stem-unique armor recipe.
        results = resolve_recipe("leather_jerkin")
        assert results, "expected leather_jerkin recipe to be loaded"
        assert len(results) == 1
        assert results[0].output == "leather_jerkin"

    def test_returns_multiple_on_ambiguity(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        # Bare ``leather`` matches every leather_* recipe — by design,
        # so the converter can list candidates.
        results = resolve_recipe("leather")
        assert len(results) > 1

    def test_unknown_recipe_returns_empty(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        assert resolve_recipe("definitely_not_a_recipe_xyz") == []


# ---------------------------------------------------------------------------
# MonsterConverter
# ---------------------------------------------------------------------------


class TestMonsterConverter:
    @pytest.mark.asyncio
    async def test_no_game_raises(self):
        with _patch_get_game(None):
            with pytest.raises(BadArgument, match="No monster"):
                await MonsterConverter().convert(MagicMock(), "anything")

    @pytest.mark.asyncio
    async def test_no_monster_raises(self):
        game = _make_game(monster=None)
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No monster"):
                await MonsterConverter().convert(MagicMock(), "anything")

    @pytest.mark.asyncio
    async def test_match_returns_monster(self):
        m = _make_monster("hexed hydra")
        game = _make_game(monster=m)
        with _patch_get_game(game):
            result = await MonsterConverter().convert(MagicMock(), "hydra")
        assert result is m

    @pytest.mark.asyncio
    async def test_no_match_raises_with_name(self):
        m = _make_monster("goblin")
        game = _make_game(monster=m)
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="dragon.*goblin"):
                await MonsterConverter().convert(MagicMock(), "dragon")


# ---------------------------------------------------------------------------
# MonsterClassConverter
# ---------------------------------------------------------------------------


class TestMonsterClassConverter:
    @pytest.mark.asyncio
    async def test_exact_stem_returns_class(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        result = await MonsterClassConverter().convert(MagicMock(), "goblin")
        assert result is Goblin

    @pytest.mark.asyncio
    async def test_fuzzy_unique_match_returns_class(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        result = await MonsterClassConverter().convert(MagicMock(), "gobl")
        assert result is Goblin

    @pytest.mark.asyncio
    async def test_unknown_raises(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        with pytest.raises(BadArgument, match="Unknown monster"):
            await MonsterClassConverter().convert(
                MagicMock(), "definitely_not_a_monster_xyz",
            )


# ---------------------------------------------------------------------------
# PlayerConverter
# ---------------------------------------------------------------------------


class TestPlayerConverter:
    @pytest.mark.asyncio
    async def test_no_game_raises(self):
        with _patch_get_game(None):
            with pytest.raises(BadArgument, match="No active game"):
                await PlayerConverter().convert(MagicMock(), "alice")

    @pytest.mark.asyncio
    async def test_fuzzy_unique_match(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            result = await PlayerConverter().convert(MagicMock(), "alic")
        assert result is alice

    @pytest.mark.asyncio
    async def test_no_match_raises(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No player"):
                await PlayerConverter().convert(MagicMock(), "xyzzy")

    @pytest.mark.asyncio
    async def test_ambiguous_raises_with_names(self):
        a1 = _make_player("Alice", member=_make_member("Alice"))
        a2 = _make_player("Alicia", member=_make_member("Alicia"))
        game = _make_game(players=[a1, a2])
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="multiple players"):
                await PlayerConverter().convert(MagicMock(), "ali")


# ---------------------------------------------------------------------------
# CreatureConverter
# ---------------------------------------------------------------------------


class TestCreatureConverter:
    def test_invalid_prefer_raises_at_construction(self):
        with pytest.raises(ValueError, match="prefer"):
            CreatureConverter(prefer="alien")

    @pytest.mark.asyncio
    async def test_prefer_monster_picks_monster_first(self):
        # Both a monster named "Alice" AND a player named "Alice"
        # could match. ``prefer="monster"`` returns the monster.
        m = _make_monster("Alice")
        alice_player = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice_player])
        with _patch_get_game(game):
            result = await CreatureConverter(prefer="monster").convert(
                MagicMock(), "alice",
            )
        assert result is m

    @pytest.mark.asyncio
    async def test_prefer_player_picks_player_first(self):
        m = _make_monster("Alice")
        alice_player = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice_player])
        with _patch_get_game(game):
            result = await CreatureConverter(prefer="player").convert(
                MagicMock(), "alice",
            )
        assert result is alice_player

    @pytest.mark.asyncio
    async def test_falls_through_to_secondary(self):
        # Monster doesn't match, but player does — composer falls
        # through to the player branch even with ``prefer="monster"``.
        m = _make_monster("dragon")
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice])
        with _patch_get_game(game):
            result = await CreatureConverter(prefer="monster").convert(
                MagicMock(), "alice",
            )
        assert result is alice


# ---------------------------------------------------------------------------
# PartConverter
# ---------------------------------------------------------------------------


class TestPartConverter:
    @pytest.mark.asyncio
    async def test_no_monster_raises(self):
        game = _make_game(monster=None)
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No creature"):
                await PartConverter().convert(MagicMock(), "head")

    @pytest.mark.asyncio
    async def test_match_returns_list_of_parts(self):
        leg_l = _make_part("leg.left")
        leg_r = _make_part("leg.right")
        m = _make_monster("test", parts=[leg_l, leg_r])
        game = _make_game(monster=m)
        with _patch_get_game(game):
            result = await PartConverter().convert(MagicMock(), "leg")
        assert set(result) == {leg_l, leg_r}

    @pytest.mark.asyncio
    async def test_no_part_match_raises(self):
        m = _make_monster("test", parts=[_make_part("head")])
        game = _make_game(monster=m)
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="tail"):
                await PartConverter().convert(MagicMock(), "tail")


# ---------------------------------------------------------------------------
# RecipeConverter
# ---------------------------------------------------------------------------


class TestRecipeConverter:
    @pytest.mark.asyncio
    async def test_known_recipe_resolves(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        result = await RecipeConverter().convert(MagicMock(), "leather_jerkin")
        assert result.output == "leather_jerkin"

    @pytest.mark.asyncio
    async def test_ambiguous_recipe_raises_with_names(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        with pytest.raises(BadArgument, match="multiple recipes"):
            await RecipeConverter().convert(MagicMock(), "leather")

    @pytest.mark.asyncio
    async def test_unknown_recipe_raises(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        with pytest.raises(BadArgument, match="Unknown recipe"):
            await RecipeConverter().convert(
                MagicMock(), "definitely_not_a_recipe_xyz",
            )

    @pytest.mark.asyncio
    async def test_ambiguous_message_lists_candidate_names(self):
        """The ambiguity-error message must include the candidate
        recipe display names — the player's only signal for how to
        re-issue with a more specific query."""
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        with pytest.raises(BadArgument) as excinfo:
            await RecipeConverter().convert(MagicMock(), "leather")
        # At minimum, two of the leather_* recipes should be named
        # in the error message.
        msg = str(excinfo.value)
        assert "leather jerkin" in msg or "leather cap" in msg, msg


# ---------------------------------------------------------------------------
# PasserbyConverter / PendingSilhouetteConverter
# ---------------------------------------------------------------------------


class TestPasserbyConverter:
    @pytest.mark.asyncio
    async def test_no_passerby_raises(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        game = _make_game()
        game.passerby = None
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No passerby"):
                await PasserbyConverter().convert(MagicMock(), "wagoneer")

    @pytest.mark.asyncio
    async def test_fuzzy_prefix_resolves(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        npc = Herbalist()
        game = _make_game()
        game.passerby = npc
        with _patch_get_game(game):
            result = await PasserbyConverter().convert(MagicMock(), "herba")
            assert result is npc

    @pytest.mark.asyncio
    async def test_no_match_raises_with_npc_name(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        npc = Herbalist()
        game = _make_game()
        game.passerby = npc
        with _patch_get_game(game):
            with pytest.raises(BadArgument) as excinfo:
                await PasserbyConverter().convert(MagicMock(), "dragon")
            assert "herbalist" in str(excinfo.value)


class TestPendingSilhouetteConverter:
    @pytest.mark.asyncio
    async def test_no_silhouette_raises(self):
        from caldanai.lib.rpg.helpers.converters import (
            PendingSilhouetteConverter,
        )
        game = _make_game()
        game.pending_silhouette = None
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No silhouette"):
                await PendingSilhouetteConverter().convert(
                    MagicMock(), "wagoneer",
                )

    @pytest.mark.asyncio
    async def test_silhouette_fuzzy_resolves(self):
        from caldanai.lib.rpg.helpers.converters import (
            PendingSilhouetteConverter,
        )
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        npc = Shepherd()
        game = _make_game()
        game.pending_silhouette = npc
        with _patch_get_game(game):
            result = await PendingSilhouetteConverter().convert(
                MagicMock(), "shep",
            )
            assert result is npc


# ---------------------------------------------------------------------------
# FuzzyMemberConverter
# ---------------------------------------------------------------------------


class TestFuzzyMemberConverter:
    """FuzzyMemberConverter returns Member, not Player — drop-in
    replacement for ``Optional[Member]`` annotations on commands
    like ``$warmth set <cmd> <level> [@player]``."""

    @pytest.mark.asyncio
    async def test_fuzzy_username_returns_member(self):
        # Build a Player with attached Member — fuzzy resolution
        # against the player roster returns the Member.
        member = _make_member("AliceDN", "alice_user")
        alice = _make_player("Alice", member=member)
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                result = await FuzzyMemberConverter().convert(
                    MagicMock(), "alic",
                )
        assert result is member

    @pytest.mark.asyncio
    async def test_no_game_raises(self):
        with _patch_get_game(None):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                with pytest.raises(BadArgument, match="No player"):
                    await FuzzyMemberConverter().convert(
                        MagicMock(), "alice",
                    )

    @pytest.mark.asyncio
    async def test_no_match_raises(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                with pytest.raises(BadArgument, match="No player"):
                    await FuzzyMemberConverter().convert(
                        MagicMock(), "xyzzy",
                    )

    @pytest.mark.asyncio
    async def test_ambiguous_raises_with_names(self):
        a1 = _make_player("Alice", member=_make_member("Alice"))
        a2 = _make_player("Alicia", member=_make_member("Alicia"))
        game = _make_game(players=[a1, a2])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                with pytest.raises(BadArgument, match="multiple players"):
                    await FuzzyMemberConverter().convert(
                        MagicMock(), "ali",
                    )

    @pytest.mark.asyncio
    async def test_player_without_member_raises(self):
        # Cached Player with no attached Member (offline, etc.) —
        # fuzzy match still finds the player but FuzzyMemberConverter
        # can't return a Member, so it surfaces a specific error
        # rather than crashing on attribute access.
        alice = _make_player("Alice", member=None)
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                with pytest.raises(BadArgument, match="not currently"):
                    await FuzzyMemberConverter().convert(
                        MagicMock(), "alice",
                    )
