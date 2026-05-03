"""Free fuzzy-resolution helpers — the layer that knows which
candidate pool to feed :func:`fuzzy_match` for each
domain object (monster, player, part, recipe).

These helpers live here (not under ``caldanai/lib/cogs/``) so cog
modules that need fuzzy lookups can import them without crossing
into another cog's namespace. The discord.py Converter wrappers
live in :mod:`caldanai.lib.rpg.helpers.converters` and call into these
helpers.

API contract: every helper takes a ``query`` string plus whatever
context object holds the candidate pool (``game`` for players,
``creature`` for parts, etc.) and returns a ``List[T]``. Empty
list means no match; one element means unique match; more than
one means ambiguous and the caller decides whether to surface the
list or auto-resolve.
"""

from typing import List, Optional, Type

from caldanai.lib.rpg.crafting.recipe import RecipePlugin, list_recipes
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.fuzzy import fuzzy_match


def resolve_monster_class(query: str) -> List[Type[MonsterPlugin]]:
    """Fuzzy-match ``query`` against the loaded monster plugin
    registry. Returns the candidate plugin classes — empty on no
    match, more than one on ambiguity.

    Used at spawn time (``$spawn <name>``) where the result is a
    class to instantiate, not a live creature in the channel."""
    return MonsterPlugin.find_plugin_classes(query)


def resolve_active_monster(
    monster: Optional[Creature],
    query: str,
    *,
    conflict_check=None,
) -> Optional[Creature]:
    """Returns ``monster`` if its name fuzzy-matches ``query``, else
    ``None``. Single-creature world today; multi-monster will extend
    this to scan a creature list.

    ``conflict_check`` mirrors :meth:`Creature.matches_token` —
    ``$kill`` passes its ``find_parts`` so single-letter part
    shortcuts (``h`` / ``t``) shadow fuzzy name matches on the
    spawned creature.

    Uses the unbound :meth:`Creature.matches_token` form so duck-
    typed test fixtures (``SimpleNamespace(name=...)``) work
    alongside real Creature instances — the test surface only needs
    a ``.name`` attribute."""
    if monster is None or not query:
        return None
    if Creature.matches_token(monster, query, conflict_check=conflict_check):
        return monster
    return None


def resolve_player(game, query: str) -> List[Player]:
    """Fuzzy-match ``query`` against the active game's player roster.

    Per-player keys, in order: cached ``player.name`` (survives
    disconnect-state members), ``player.member.display_name``, and
    ``player.member.name`` (Discord username). Any of the three can
    match; the resolver dedupes on player identity.

    Mention syntax (``<@!id>``) is not handled here — callers route
    that through :class:`PlayerConverter` (which uses discord.py's
    :class:`MemberConverter` first) or strip mentions and pass the
    remaining text."""
    if not query or game is None:
        return []
    pool = list(game.player_manager.players.values())

    def keys_for(p: Player) -> List[str]:
        ks = [p.name] if p.name else []
        if p.member is not None:
            if p.member.display_name:
                ks.append(p.member.display_name)
            if p.member.name:
                ks.append(p.member.name)
        return ks

    return fuzzy_match(query, pool, keys=keys_for, strategy="unordered").tightest


def resolve_part(
    creature: Optional[Creature], query: str,
) -> List[BodyPart]:
    """Fuzzy-match a body-part name on ``creature``. Wraps
    :meth:`Creature.find_parts` so callers get a single import for
    the resolver family, plus a graceful empty-list response when
    the creature is ``None`` (no monster spawned, etc.)."""
    if creature is None:
        return []
    return creature.find_parts(query)


def resolve_recipe(query: str) -> List[Type[RecipePlugin]]:
    """Fuzzy-match a query against loaded recipe classes. Matches
    against both the output stem (``leather_jerkin``) and the
    display name (``leather jerkin``) — :func:`whitespace_tokens`
    treats both as equivalent token streams."""
    pool = list_recipes()  # Lazy-discovers if registry is empty.
    return fuzzy_match(
        query,
        pool,
        keys=lambda r: [r.output, r.display_name()],
        strategy="unordered",
    ).tightest
