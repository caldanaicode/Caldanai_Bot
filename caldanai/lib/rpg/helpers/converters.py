"""Discord.py Converters for fuzzy-resolved RPG arguments.

Each converter wraps a resolver from
:mod:`caldanai.lib.rpg.helpers.resolvers` and surfaces 0/1/N results
through ``commands.BadArgument``:

- 0 matches → ``BadArgument`` with a "no match" message
- 1 match → returned directly
- N matches → ``BadArgument`` listing candidates so the player can
  re-issue with a more specific query

This module lives in :mod:`caldanai.lib.rpg.helpers` rather than
``caldanai/lib/cogs/`` because the cogs directory is the bot's
extension auto-loader — every module there is expected to expose a
``setup()`` and register itself as a discord.py Cog. Converters
are utility classes used BY cogs, not cogs themselves, so they
belong with the other helpers.

The free resolver functions live in
:mod:`caldanai.lib.rpg.helpers.resolvers` and are imported here so
the converter wrappers and resolver helpers can be reached from a
single module surface when convenient.

Underlying resolvers, by source of truth:

- :func:`resolve_monster_class` → :meth:`MonsterPlugin.find_plugin_classes`
  (registry + alias lookup, used by ``$spawn``)
- :func:`resolve_active_monster` → :meth:`Creature.matches_token`
  (single-creature targeting with ``conflict_check`` for
  ``$kill h`` part-shortcut defense, used by ``$haunt`` /
  ``$look`` / ``$kill`` / ``$creature destroy`` / ``$target``)
- :func:`resolve_player` → :func:`fuzzy_match` over
  ``game.player_manager.players`` (display_name + Discord
  username + cached player.name keys)
- :func:`resolve_part` → :meth:`Creature.find_parts`
- :func:`resolve_recipe` → :func:`fuzzy_match` over the
  ``RECIPES`` plugin registry
"""

from typing import List, Type

from discord.ext.commands import (
    BadArgument, Context, Converter, MemberConverter,
)

from caldanai.lib.rpg.crafting.recipe import RecipePlugin
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.helpers.resolvers import (
    resolve_active_monster,
    resolve_monster_class,
    resolve_part,
    resolve_passerby,
    resolve_pending_silhouette,
    resolve_player,
    resolve_recipe,
)
from caldanai.lib.rpg.helpers.utils import RpgUtilities

# Re-exported so import sites that originally landed in this module
# still work. New callers should prefer importing the resolver
# helpers directly from ``caldanai.lib.rpg.helpers.resolvers``.
__all__ = [
    "CreatureConverter",
    "FuzzyMemberConverter",
    "MonsterClassConverter",
    "MonsterConverter",
    "PartConverter",
    "PasserbyConverter",
    "PendingSilhouetteConverter",
    "PlayerConverter",
    "RecipeConverter",
    "StaticObjectConverter",
    "resolve_active_monster",
    "resolve_monster_class",
    "resolve_part",
    "resolve_passerby",
    "resolve_pending_silhouette",
    "resolve_player",
    "resolve_recipe",
]


# ---------------------------------------------------------------------------
# Discord.py Converters — annotation-driven single-arg conversion.
# ---------------------------------------------------------------------------


class MonsterConverter(Converter):
    """Resolves the active spawned monster from a fuzzy name query.

    Used by commands targeting the currently-spawned creature
    (``$haunt``, ``$look``, ``$creature destroy``). Raises
    ``BadArgument`` if no monster is spawned or the query doesn't
    match the spawned creature's name.

    For ``$spawn`` (resolving a class to instantiate, not a live
    creature), use :class:`MonsterClassConverter` instead.
    """

    async def convert(self, ctx: Context, argument: str) -> Creature:
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.monster is None:
            raise BadArgument("No monster currently spawned to target.")
        monster = resolve_active_monster(game.monster, argument)
        if monster is None:
            raise BadArgument(
                f"`{argument}` doesn't match the spawned "
                f"{game.monster.name}."
            )
        return monster


class MonsterClassConverter(Converter):
    """Resolves a monster *plugin class* from the loaded registry.

    Used by ``$spawn``: the result is a class for instantiation,
    not a live creature in the channel. Matches stem AND aliases
    via :meth:`MonsterPlugin.find_plugin_classes`. Raises
    ``BadArgument`` on no-match or ambiguous-match (with the
    candidate list so the player can re-issue more specifically).
    """

    async def convert(
        self, ctx: Context, argument: str,
    ) -> Type[MonsterPlugin]:
        # The shared resolver's exact tier already short-circuits
        # to the unique class for unique stems / aliases — no need
        # to call ``get_plugin_class`` separately. Doing so would
        # mean a query that exact-matches an alias bypasses the
        # tiered pipeline, which would re-introduce the
        # inconsistency the rework was designed to eliminate.
        results = resolve_monster_class(argument)
        if not results:
            raise BadArgument(f"Unknown monster: `{argument}`.")
        if len(results) > 1:
            names = ", ".join(
                sorted(c.__module__.rsplit(".", 1)[-1] for c in results)
            )
            raise BadArgument(
                f"`{argument}` matched multiple monsters: {names}."
            )
        return results[0]


class PlayerConverter(Converter):
    """Resolves a Player from a Discord mention OR a fuzzy username
    query.

    Mention-syntax fast path uses discord.py's :class:`MemberConverter`
    so the resolution is identical to other mention-aware commands.
    On non-mention queries, falls through to fuzzy matching by
    display name / Discord username / cached player name.

    Raises ``BadArgument`` on no-match or ambiguous-match.
    """

    async def convert(self, ctx: Context, argument: str) -> Player:
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            raise BadArgument("No active game in this channel.")

        # Mention fast path. ``<@!id>`` and ``<@id>`` both supported
        # by MemberConverter. If the mention syntax resolves to a
        # Discord member, we hit the player roster directly — and a
        # mention that *doesn't* resolve to a game player is a
        # specific, surfaceable error rather than fuzzy fallback
        # against the raw ``<@!12345>`` text (which would always
        # miss with a confusing message).
        if argument.startswith("<@") and argument.endswith(">"):
            try:
                member = await MemberConverter().convert(ctx, argument)
            except BadArgument as exc:
                raise BadArgument(
                    f"Couldn't resolve mention `{argument}`."
                ) from exc
            player = await RpgUtilities.get_player(
                member, game=game, notify=False,
            )
            if player is None:
                raise BadArgument(
                    f"{member.display_name} isn't in the game.",
                )
            return player

        results = resolve_player(game, argument)
        if not results:
            raise BadArgument(f"No player matching `{argument}`.")
        if len(results) > 1:
            names = ", ".join(
                p.member.display_name if p.member is not None and p.member.display_name
                else (p.name or "?")
                for p in results
            )
            raise BadArgument(
                f"`{argument}` matched multiple players: {names}."
            )
        return results[0]


class CreatureConverter(Converter):
    """Composer: resolves either an active monster or a player from
    a single argument.

    ``prefer="monster"`` (default) tries :class:`MonsterConverter`
    first then falls through to :class:`PlayerConverter`.
    ``prefer="player"`` flips the order.

    Use for commands where the in-fiction action targets either a
    creature kind — ``$haunt`` is the canonical example: a ghost can
    haunt an alive monster or a fellow living/dead player. The
    ``prefer=`` direction governs which interpretation wins on a
    name collision (e.g. a player named the same as a monster's
    display name).
    """

    def __init__(self, prefer: str = "monster"):
        if prefer not in ("monster", "player"):
            raise ValueError(
                f"prefer must be 'monster' or 'player', got {prefer!r}",
            )
        self.prefer = prefer

    async def convert(self, ctx: Context, argument: str) -> Creature:
        if self.prefer == "monster":
            primary, fallback = MonsterConverter(), PlayerConverter()
        else:
            primary, fallback = PlayerConverter(), MonsterConverter()
        try:
            return await primary.convert(ctx, argument)
        except BadArgument:
            pass
        return await fallback.convert(ctx, argument)


class PartConverter(Converter):
    """Resolves a list of body parts on the active spawned monster
    via fuzzy match.

    Returns the *list* of matching parts (multi-match is meaningful:
    ``leg`` matches both legs, the caller decides whether to act on
    all or pick one). Raises ``BadArgument`` only on empty match.

    For commands targeting parts on a creature OTHER than
    ``game.monster`` (player self-target, multi-monster
    disambiguation), call :func:`resolve_part(creature, query)`
    directly from the command body.
    """

    async def convert(
        self, ctx: Context, argument: str,
    ) -> List[BodyPart]:
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.monster is None:
            raise BadArgument("No creature to target.")
        results = resolve_part(game.monster, argument)
        if not results:
            raise BadArgument(
                f"No part matching `{argument}` on {game.monster.name}.",
            )
        return results


class FuzzyMemberConverter(Converter):
    """Drop-in replacement for ``Optional[Member]`` that adds fuzzy
    display-name matching alongside discord.py's standard
    :class:`MemberConverter` resolution (mention / id / name#discrim
    / exact display name).

    Returns a :class:`discord.Member`, not a Player — handlers that
    were previously typed ``Optional[Member]`` keep working unchanged.
    For the Player-returning variant, use :class:`PlayerConverter`.

    Resolution order:

    1. discord.py's :class:`MemberConverter` (mention / id /
       name#discrim / exact display_name / exact name).
    2. Fuzzy match via :func:`resolve_player` against the active
       game's player roster, returning that player's
       ``.member`` on a unique match.

    Raises ``BadArgument`` on no-match or ambiguous-match.
    """

    async def convert(self, ctx: Context, argument: str):
        # Layer 1 — discord.py's built-in. Handles mention / id /
        # name#discrim / exact display name / exact name.
        try:
            return await MemberConverter().convert(ctx, argument)
        except BadArgument:
            pass
        # Layer 2 — fuzzy game-roster lookup, return ``.member``.
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            raise BadArgument(f"No player matching `{argument}`.")
        results = resolve_player(game, argument)
        if not results:
            raise BadArgument(f"No player matching `{argument}`.")
        if len(results) > 1:
            names = ", ".join(
                p.member.display_name if p.member is not None and p.member.display_name
                else (p.name or "?")
                for p in results
            )
            raise BadArgument(
                f"`{argument}` matched multiple players: {names}.",
            )
        member = getattr(results[0], "member", None)
        if member is None:
            raise BadArgument(
                f"`{argument}` matched a player not currently on the "
                f"server roster.",
            )
        return member


class PasserbyConverter(Converter):
    """Resolves the present passerby NPC from a fuzzy name query.

    Used by commands targeting the currently-Present passerby
    (``$greet``, ``$wave``, ``$nod``, ``$kill <npc>``, etc.).
    Matches NPC name + class stem + ``ALIASES`` via the
    project-standard fuzzy_match (exact → prefix → substring →
    typo) through :meth:`PasserbyPlugin.matches_token`.

    Raises ``BadArgument`` when no passerby is present OR the
    query doesn't fuzzy-match the present NPC. Most cog call
    sites prefer to invoke :func:`resolve_passerby` directly so
    they can compose with silhouette / monster / italic-fallback
    chains without converting the no-match case to an exception
    — use this Converter only when the command genuinely REQUIRES
    a present-passerby target.
    """

    async def convert(
        self, ctx: Context, argument: str,
    ) -> PasserbyPlugin:
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.passerby is None:
            raise BadArgument("No passerby present in the clearing.")
        npc = resolve_passerby(game, argument)
        if npc is None:
            raise BadArgument(
                f"`{argument}` doesn't match the present "
                f"{game.passerby.name}."
            )
        return npc


class PendingSilhouetteConverter(Converter):
    """Resolves the at-distance silhouette NPC from a fuzzy name
    query — the slot used while combat is active.

    Same shape as :class:`PasserbyConverter` but reads
    ``game.pending_silhouette``. Used when a command needs to
    address a silhouette specifically (e.g. the ``$greet``
    silhouette-too-far branch). Raises ``BadArgument`` on no
    silhouette OR no fuzzy-match.
    """

    async def convert(
        self, ctx: Context, argument: str,
    ) -> PasserbyPlugin:
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.pending_silhouette is None:
            raise BadArgument("No silhouette at the verge.")
        npc = resolve_pending_silhouette(game, argument)
        if npc is None:
            raise BadArgument(
                f"`{argument}` doesn't match the silhouette of "
                f"{game.pending_silhouette.name}."
            )
        return npc


class StaticObjectConverter(Converter):
    """Resolves a static object present in the active room from a
    fuzzy name query.

    Used by world-verb commands (``$light``, ``$feed``, ``$gaze``,
    ``$touch``, ``$listen``) when a target argument is supplied.
    Matches name + aliases via :meth:`Area.find_static_object`'s
    fuzzy pass chain.

    Raises ``BadArgument`` on no-match. The world cog catches and
    converts to an italic fallback line so the player gets a clean
    "nothing here by that name" response rather than discord.py's
    raw error.

    By design, static objects are matched LAST in any cog whose
    verb could plausibly target multiple kinds of entity (a future
    `$gaze companion` should hit the player before a similarly-named
    object). Cogs that mix entity types should call player /
    passerby resolvers first and only fall through to this
    converter when those return nothing.
    """

    async def convert(self, ctx: Context, argument: str):
        from caldanai.lib.rpg.world.objects import StaticObjectPlugin

        game = await RpgUtilities.get_game(ctx)
        if game is None or game.room0 is None:
            raise BadArgument("No active room in this channel.")
        obj = game.room0.find_static_object(argument)
        if obj is None:
            raise BadArgument(
                f"Nothing here matching `{argument}`.",
            )
        return obj


class RecipeConverter(Converter):
    """Resolves a recipe class from a fuzzy name query.

    Used by ``$craft <recipe>``. Matches output stem AND display
    name (``leather_jerkin`` / ``leather jerkin``). Raises
    ``BadArgument`` on no-match or ambiguous-match (with display
    names so the player can re-issue).
    """

    async def convert(
        self, ctx: Context, argument: str,
    ) -> Type[RecipePlugin]:
        results = resolve_recipe(argument)
        if not results:
            raise BadArgument(f"Unknown recipe: `{argument}`.")
        if len(results) > 1:
            names = ", ".join(sorted(r.display_name() for r in results))
            raise BadArgument(
                f"`{argument}` matched multiple recipes: {names}."
            )
        return results[0]
