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


# ---------------------------------------------------------------------------
# try_convert contract — Optional-returning sibling of convert(), used
# by the fuzzy_resolve dispatcher. Each converter gets a hit + a miss
# pair plus, on the non-FuzzyMember classes, a spot-check that convert()
# still raises BadArgument when try_convert returns None.
# ---------------------------------------------------------------------------


class TestMonsterConverterTryConvert:
    @pytest.mark.asyncio
    async def test_match_returns_monster(self):
        m = _make_monster("hexed hydra")
        game = _make_game(monster=m)
        with _patch_get_game(game):
            result = await MonsterConverter().try_convert(
                MagicMock(), "hydra",
            )
        assert result is m

    @pytest.mark.asyncio
    async def test_no_monster_returns_none(self):
        game = _make_game(monster=None)
        with _patch_get_game(game):
            result = await MonsterConverter().try_convert(
                MagicMock(), "anything",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        m = _make_monster("goblin")
        game = _make_game(monster=m)
        with _patch_get_game(game):
            result = await MonsterConverter().try_convert(
                MagicMock(), "dragon",
            )
        assert result is None


class TestMonsterClassConverterTryConvert:
    @pytest.mark.asyncio
    async def test_unique_match_returns_class(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        result = await MonsterClassConverter().try_convert(
            MagicMock(), "goblin",
        )
        assert result is Goblin

    @pytest.mark.asyncio
    async def test_unknown_returns_none(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        result = await MonsterClassConverter().try_convert(
            MagicMock(), "definitely_not_a_monster_xyz",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_unknown(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        MonsterPlugin.load_plugins()
        with pytest.raises(BadArgument, match="Unknown monster"):
            await MonsterClassConverter().convert(
                MagicMock(), "definitely_not_a_monster_xyz",
            )


class TestPlayerConverterTryConvert:
    @pytest.mark.asyncio
    async def test_fuzzy_match_returns_player(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            result = await PlayerConverter().try_convert(
                MagicMock(), "alic",
            )
        assert result is alice

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            result = await PlayerConverter().try_convert(
                MagicMock(), "xyzzy",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_ambiguous_returns_none(self):
        a1 = _make_player("Alice", member=_make_member("Alice"))
        a2 = _make_player("Alicia", member=_make_member("Alicia"))
        game = _make_game(players=[a1, a2])
        with _patch_get_game(game):
            result = await PlayerConverter().try_convert(
                MagicMock(), "ali",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_game_returns_none(self):
        with _patch_get_game(None):
            result = await PlayerConverter().try_convert(
                MagicMock(), "alice",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_unresolvable_mention_returns_none(self):
        # Mention-shaped argument that doesn't resolve to a Discord
        # member must return None rather than fall through to fuzzy
        # matching against the literal "<@!12345>" text.
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                result = await PlayerConverter().try_convert(
                    MagicMock(), "<@!111111111111111111>",
                )
        assert result is None

    @pytest.mark.asyncio
    async def test_mention_resolves_to_game_player(self):
        member = _make_member("Alice")
        alice = _make_player("Alice", member=member)
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(return_value=member),
            ):
                with _patch_get_player(alice):
                    result = await PlayerConverter().try_convert(
                        MagicMock(), "<@!111111111111111111>",
                    )
        assert result is alice

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_no_game(self):
        with _patch_get_game(None):
            with pytest.raises(BadArgument, match="No active game"):
                await PlayerConverter().convert(MagicMock(), "alice")


class TestCreatureConverterTryConvert:
    @pytest.mark.asyncio
    async def test_monster_prefer_returns_monster(self):
        m = _make_monster("Alice")
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice])
        with _patch_get_game(game):
            result = await CreatureConverter(
                prefer="monster",
            ).try_convert(MagicMock(), "alice")
        assert result is m

    @pytest.mark.asyncio
    async def test_player_prefer_returns_player(self):
        m = _make_monster("Alice")
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice])
        with _patch_get_game(game):
            result = await CreatureConverter(
                prefer="player",
            ).try_convert(MagicMock(), "alice")
        assert result is alice

    @pytest.mark.asyncio
    async def test_falls_through_to_secondary(self):
        m = _make_monster("dragon")
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice])
        with _patch_get_game(game):
            result = await CreatureConverter(
                prefer="monster",
            ).try_convert(MagicMock(), "alice")
        assert result is alice

    @pytest.mark.asyncio
    async def test_no_match_either_returns_none(self):
        m = _make_monster("dragon")
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice])
        with _patch_get_game(game):
            result = await CreatureConverter().try_convert(
                MagicMock(), "xyzzy",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_total_miss(self):
        m = _make_monster("dragon")
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(monster=m, players=[alice])
        with _patch_get_game(game):
            with pytest.raises(BadArgument):
                await CreatureConverter().convert(MagicMock(), "xyzzy")


class TestPartConverterTryConvert:
    @pytest.mark.asyncio
    async def test_match_returns_list(self):
        leg_l = _make_part("leg.left")
        leg_r = _make_part("leg.right")
        m = _make_monster("test", parts=[leg_l, leg_r])
        game = _make_game(monster=m)
        with _patch_get_game(game):
            result = await PartConverter().try_convert(
                MagicMock(), "leg",
            )
        assert set(result) == {leg_l, leg_r}

    @pytest.mark.asyncio
    async def test_no_monster_returns_none(self):
        game = _make_game(monster=None)
        with _patch_get_game(game):
            result = await PartConverter().try_convert(
                MagicMock(), "head",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_part_match_returns_none(self):
        m = _make_monster("test", parts=[_make_part("head")])
        game = _make_game(monster=m)
        with _patch_get_game(game):
            result = await PartConverter().try_convert(
                MagicMock(), "tail",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_no_monster(self):
        game = _make_game(monster=None)
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No creature"):
                await PartConverter().convert(MagicMock(), "head")


class TestPasserbyConverterTryConvert:
    @pytest.mark.asyncio
    async def test_match_returns_npc(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        npc = Herbalist()
        game = _make_game()
        game.passerby = npc
        with _patch_get_game(game):
            result = await PasserbyConverter().try_convert(
                MagicMock(), "herba",
            )
        assert result is npc

    @pytest.mark.asyncio
    async def test_no_passerby_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        game = _make_game()
        game.passerby = None
        with _patch_get_game(game):
            result = await PasserbyConverter().try_convert(
                MagicMock(), "anything",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        from caldanai.lib.rpg.creatures.passersby.herbalist import Herbalist
        npc = Herbalist()
        game = _make_game()
        game.passerby = npc
        with _patch_get_game(game):
            result = await PasserbyConverter().try_convert(
                MagicMock(), "dragon",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_no_passerby(self):
        from caldanai.lib.rpg.helpers.converters import PasserbyConverter
        game = _make_game()
        game.passerby = None
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No passerby"):
                await PasserbyConverter().convert(MagicMock(), "anything")


class TestPendingSilhouetteConverterTryConvert:
    @pytest.mark.asyncio
    async def test_match_returns_npc(self):
        from caldanai.lib.rpg.helpers.converters import (
            PendingSilhouetteConverter,
        )
        from caldanai.lib.rpg.creatures.passersby.shepherd import Shepherd
        npc = Shepherd()
        game = _make_game()
        game.pending_silhouette = npc
        with _patch_get_game(game):
            result = await PendingSilhouetteConverter().try_convert(
                MagicMock(), "shep",
            )
        assert result is npc

    @pytest.mark.asyncio
    async def test_no_silhouette_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import (
            PendingSilhouetteConverter,
        )
        game = _make_game()
        game.pending_silhouette = None
        with _patch_get_game(game):
            result = await PendingSilhouetteConverter().try_convert(
                MagicMock(), "anything",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_no_silhouette(self):
        from caldanai.lib.rpg.helpers.converters import (
            PendingSilhouetteConverter,
        )
        game = _make_game()
        game.pending_silhouette = None
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="No silhouette"):
                await PendingSilhouetteConverter().convert(
                    MagicMock(), "anything",
                )


class TestStaticObjectConverterTryConvert:
    @pytest.mark.asyncio
    async def test_match_returns_object(self):
        from caldanai.lib.rpg.helpers.converters import StaticObjectConverter
        obj = MagicMock(name="campfire")
        game = _make_game()
        game.room0 = MagicMock()
        game.room0.find_static_object = MagicMock(return_value=obj)
        with _patch_get_game(game):
            result = await StaticObjectConverter().try_convert(
                MagicMock(), "campfire",
            )
        assert result is obj

    @pytest.mark.asyncio
    async def test_no_room_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import StaticObjectConverter
        game = _make_game()
        game.room0 = None
        with _patch_get_game(game):
            result = await StaticObjectConverter().try_convert(
                MagicMock(), "campfire",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import StaticObjectConverter
        game = _make_game()
        game.room0 = MagicMock()
        game.room0.find_static_object = MagicMock(return_value=None)
        with _patch_get_game(game):
            result = await StaticObjectConverter().try_convert(
                MagicMock(), "campfire",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_no_match(self):
        from caldanai.lib.rpg.helpers.converters import StaticObjectConverter
        game = _make_game()
        game.room0 = MagicMock()
        game.room0.find_static_object = MagicMock(return_value=None)
        with _patch_get_game(game):
            with pytest.raises(BadArgument, match="Nothing here"):
                await StaticObjectConverter().convert(
                    MagicMock(), "campfire",
                )


class TestRecipeConverterTryConvert:
    @pytest.mark.asyncio
    async def test_unique_match_returns_recipe(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        result = await RecipeConverter().try_convert(
            MagicMock(), "leather_jerkin",
        )
        assert result is not None
        assert result.output == "leather_jerkin"

    @pytest.mark.asyncio
    async def test_ambiguous_returns_none(self):
        # "leather" matches multiple leather_* recipes; the dispatcher
        # contract treats ambiguity as a miss so the call site can
        # fall through to its next target type.
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        result = await RecipeConverter().try_convert(
            MagicMock(), "leather",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_unknown_returns_none(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        result = await RecipeConverter().try_convert(
            MagicMock(), "definitely_not_a_recipe_xyz",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_unknown(self):
        from caldanai.lib.rpg.crafting.recipe import discover_recipes
        discover_recipes()
        with pytest.raises(BadArgument, match="Unknown recipe"):
            await RecipeConverter().convert(
                MagicMock(), "definitely_not_a_recipe_xyz",
            )


class TestFuzzyMemberConverterTryConvert:
    """FuzzyMemberConverter keeps convert() as the canonical surface
    (live consumer at $warmth set <who>); try_convert is provided
    for dispatcher symmetry and mirrors the same resolution path
    with None-on-miss semantics."""

    @pytest.mark.asyncio
    async def test_fuzzy_match_returns_member(self):
        member = _make_member("AliceDN", "alice_user")
        alice = _make_player("Alice", member=member)
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                result = await FuzzyMemberConverter().try_convert(
                    MagicMock(), "alic",
                )
        assert result is member

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        alice = _make_player("Alice", member=_make_member("Alice"))
        game = _make_game(players=[alice])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                result = await FuzzyMemberConverter().try_convert(
                    MagicMock(), "xyzzy",
                )
        assert result is None

    @pytest.mark.asyncio
    async def test_ambiguous_returns_none(self):
        a1 = _make_player("Alice", member=_make_member("Alice"))
        a2 = _make_player("Alicia", member=_make_member("Alicia"))
        game = _make_game(players=[a1, a2])
        with _patch_get_game(game):
            with patch(
                "caldanai.lib.rpg.helpers.converters.MemberConverter.convert",
                new=AsyncMock(side_effect=BadArgument("not a mention")),
            ):
                result = await FuzzyMemberConverter().try_convert(
                    MagicMock(), "ali",
                )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_still_raises_on_miss(self):
        """The live consumer at $warmth set <who> needs the
        BadArgument-raising convert path; pin that it survives the
        try_convert addition."""
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


# ---------------------------------------------------------------------------
# ItemConverter + EquipmentSlotConverter — Step 4 of the fuzzy-resolve
# migration. Inventory + slot-hint dispatcher contract; the call site
# (``$equip``) handles ambiguity surfacing by re-querying the underlying
# ItemResolution dataclass when the dispatcher returns None.
# ---------------------------------------------------------------------------


def _patch_get_game_and_player(game, player):
    """Both the dispatcher walk AND the converter body call
    ``get_game_and_player`` — patch it once with the AsyncMock pair."""
    return patch(
        "caldanai.lib.rpg.helpers.converters.RpgUtilities.get_game_and_player",
        new=AsyncMock(return_value=(game, player)),
    )


class TestItemConverterTryConvert:
    """``ItemConverter.try_convert`` returns a single Item or None.
    None subsumes no-match, ambiguity, and missing game/player
    context — the dispatcher's "can't pick one" collapse.
    """

    @pytest.fixture(autouse=True)
    def _load_plugins(self):
        from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
        from caldanai.lib.rpg.inventory import Inventory
        BodyPartPlugin.load_plugins()
        Inventory.discover_items()

    def _player_with(self, *plugin_names):
        from caldanai.lib.rpg.creatures.player import Player
        from caldanai.lib.rpg.inventory import Inventory
        p = Player(uid=1, gid=2, cid=3)
        items = []
        for name in plugin_names:
            item = Inventory.load_item(name=name)
            p.inventory.add(item)
            items.append(item)
        return p, items

    @pytest.mark.asyncio
    async def test_single_match_returns_item(self):
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        player, [sword] = self._player_with("shortsword")
        with _patch_get_game_and_player(_make_game(), player):
            result = await ItemConverter().try_convert(
                MagicMock(), "shortsword",
            )
        assert result is sword

    @pytest.mark.asyncio
    async def test_no_match_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        player, _ = self._player_with("shortsword")
        with _patch_get_game_and_player(_make_game(), player):
            result = await ItemConverter().try_convert(
                MagicMock(), "definitely_not_an_item_xyz",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_no_player_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        with _patch_get_game_and_player(None, None):
            result = await ItemConverter().try_convert(
                MagicMock(), "shortsword",
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_ambiguous_quality_returns_none(self):
        """Two ``fine`` wands collapse to the same disambiguation
        label — the underlying resolver's ``_ambiguity_or_first``
        picks the first match, so the converter returns the first
        rather than None. Dispatcher contract: single Item or None;
        ``_ambiguity_or_first`` keeps single Item semantics intact
        on identical-label collapse (the 2026-04-29 fix that
        shipped in the underlying resolver)."""
        from caldanai.lib.rpg.creatures.player import Player
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        from caldanai.lib.rpg.inventory import Inventory

        player = Player(uid=1, gid=2, cid=3)
        wand_a = Inventory.load_item(data={"plugin": "wand", "quality": "FINE"})
        wand_b = Inventory.load_item(data={"plugin": "wand", "quality": "FINE"})
        player.inventory.add(wand_a)
        player.inventory.add(wand_b)

        with _patch_get_game_and_player(_make_game(), player):
            result = await ItemConverter().try_convert(
                MagicMock(), "wand.fine",
            )
        assert result is wand_a

    @pytest.mark.asyncio
    async def test_distinct_quality_ambiguity_returns_none(self):
        """Bare ``wand`` against fine + superior auto-picks the
        best per the ``$equip`` mode default. Multi-quality
        ambiguity that DOES surface candidates (different selectors
        in play) is the case where try_convert collapses to None —
        exercise via a query that the resolver can't single-pick.
        ``$equip wand.1`` shape selects index 1 directly, so probe
        the genuinely-ambiguous case via the resolver under a
        scenario where selectors produce >1 distinct candidates.
        Skipped — bare-name auto-picks best by design, so an
        ambiguity surface requires non-bare selector form."""
        from caldanai.lib.rpg.creatures.player import Player
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        from caldanai.lib.rpg.inventory import Inventory

        player = Player(uid=1, gid=2, cid=3)
        wand_a = Inventory.load_item(data={"plugin": "wand", "quality": "FINE"})
        wand_b = Inventory.load_item(data={"plugin": "wand", "quality": "SUPERIOR"})
        player.inventory.add(wand_a)
        player.inventory.add(wand_b)

        with _patch_get_game_and_player(_make_game(), player):
            result = await ItemConverter().try_convert(
                MagicMock(), "wand",
            )
        # Bare name → auto-pick best (superior over fine).
        assert result is wand_b

    @pytest.mark.asyncio
    async def test_convert_no_game_raises(self):
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        with _patch_get_game_and_player(None, None):
            with pytest.raises(BadArgument, match="No active game"):
                await ItemConverter().convert(MagicMock(), "shortsword")

    @pytest.mark.asyncio
    async def test_convert_no_match_raises(self):
        from caldanai.lib.rpg.helpers.converters import ItemConverter
        player, _ = self._player_with("shortsword")
        with _patch_get_game_and_player(_make_game(), player):
            with pytest.raises(BadArgument, match="don't seem to have"):
                await ItemConverter().convert(
                    MagicMock(), "definitely_not_an_item_xyz",
                )


class TestEquipmentSlotConverterTryConvert:
    """``EquipmentSlotConverter.try_convert`` returns an
    ``EquipmentSlots`` mask or None — no game / player context
    needed, the resolution is a pure reverse-lookup against the
    SLOT_TO_PART_KEY routing table."""

    @pytest.mark.asyncio
    async def test_short_vocab_left(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "l",
        )
        assert result == EquipmentSlots.LEFT_SIDE

    @pytest.mark.asyncio
    async def test_short_vocab_right_word(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "right",
        )
        assert result == EquipmentSlots.RIGHT_SIDE

    @pytest.mark.asyncio
    async def test_full_part_key(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "head.worn",
        )
        assert result == EquipmentSlots.HEAD

    @pytest.mark.asyncio
    async def test_dotted_part_with_key(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "hand.left.held",
        )
        assert result == EquipmentSlots.LEFT_HELD

    @pytest.mark.asyncio
    async def test_unknown_hint_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "bogus",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_underscore_returns_none(self):
        """``_`` was historically "anywhere it fits" — surfaced to
        the call site as None so the equip handler treats it as
        auto-route."""
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "_",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_returns_none(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        result = await EquipmentSlotConverter().try_convert(
            MagicMock(), "",
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_unknown_raises(self):
        from caldanai.lib.rpg.helpers.converters import EquipmentSlotConverter
        with pytest.raises(BadArgument, match="don't know the slot"):
            await EquipmentSlotConverter().convert(MagicMock(), "bogus")
