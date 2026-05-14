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
from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import EquipmentSlots
from caldanai.lib.rpg.helpers.fuzzy import fuzzy_match
from caldanai.lib.rpg.inventory.item import Item


def resolve_monster_class(query: str) -> List[Type[MonsterPlugin]]:
    """Fuzzy-match ``query`` against the loaded monster plugin
    registry. Returns the candidate plugin classes — empty on no
    match, more than one on ambiguity.

    Used at spawn time (``$spawn <name>``) where the result is a
    class to instantiate, not a live creature in the channel."""
    return MonsterPlugin.find_plugin_classes(query)


def resolve_passerby(game, query: str) -> Optional[PasserbyPlugin]:
    """Returns ``game.passerby`` if its identity fuzzy-matches
    ``query``, else ``None``. Mirrors :func:`resolve_active_monster`'s
    single-target shape — single-passerby slot today; multi-passerby
    will extend this to scan the slot list when that lands.

    Uses :meth:`PasserbyPlugin.matches_token` for the fuzzy logic
    (project-standard fuzzy_match: exact → prefix → substring →
    typo). Empty query or absent passerby returns ``None``.
    """
    npc = getattr(game, "passerby", None)
    if npc is None or not query:
        return None
    if npc.matches_token(query):
        return npc
    return None


def resolve_pending_silhouette(game, query: str) -> Optional[PasserbyPlugin]:
    """Same shape as :func:`resolve_passerby`, but matches against
    ``game.pending_silhouette`` (the at-distance NPC slot used while
    combat is active). Returns the silhouetted NPC or ``None``."""
    npc = getattr(game, "pending_silhouette", None)
    if npc is None or not query:
        return None
    if npc.matches_token(query):
        return npc
    return None


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


def resolve_item(player: Player, query: str) -> Optional[Item]:
    """Resolve a single-item ``$equip``-shaped query against the
    player's inventory. Returns the matching :class:`Item` or
    ``None`` on no-match OR ambiguity — the dispatcher contract.

    Thin wrapper around :meth:`Player.resolve_item_query` in
    ``equip`` mode (item-first, excludes already-equipped items,
    ``.best`` falls back to the next-best unequipped). Honours
    every query selector the underlying resolver supports:
    ``wand.b`` / ``wand.best``, ``wand.fine``, ``wand.fine.1``,
    ``wand.1``. The full ``<name>.<quality>.<index>`` shape is
    treated as deliberate intent in the underlying mode logic.

    Empty query or absent player short-circuits to ``None``. The
    dispatcher's contract collapses ambiguity to ``None``; callers
    that need to surface the candidate list (``$equip`` does, for
    the "did you mean: ..." UX) should call
    :meth:`Player.resolve_item_query` directly to inspect the
    full :class:`ItemResolution` rather than going through this
    wrapper.
    """
    if player is None or not query:
        return None
    resolution = player.resolve_item_query(query, "equip")
    if len(resolution.items) != 1:
        return None
    return resolution.items[0]


# Short-vocabulary slot hints — kept compact because the binding
# shape is high-frequency typing during dual-wield setup
# (``$equip sword@l mace@r``). Underscore is the historical
# "anywhere it fits" wildcard; preserved as a no-op hint so the
# call site treats it as "no specific placement, auto-route."
_SHORT_SLOT_HINTS = {
    "l":     EquipmentSlots.LEFT_SIDE,
    "left":  EquipmentSlots.LEFT_SIDE,
    "r":     EquipmentSlots.RIGHT_SIDE,
    "right": EquipmentSlots.RIGHT_SIDE,
}


def resolve_equipment_slot(hint: str) -> Optional[EquipmentSlots]:
    """Resolve an ``$equip``-style placement hint (the post-``@``
    portion of ``wand@h.l``) to an :class:`EquipmentSlots` mask.

    Resolution order:

    1. Short-vocabulary: ``l`` / ``left`` → ``LEFT_SIDE``,
       ``r`` / ``right`` → ``RIGHT_SIDE``.
    2. Full ``part.key`` reverse lookup against
       :data:`SLOT_TO_PART_KEY` and :data:`SLOT_PAIR`
       (``head.worn`` → ``HEAD``, ``hand.left.held`` →
       ``LEFT_HELD``). Multi-segment parts split is greedy on the
       right — ``hand.left.held`` tries the split at
       ``hand.left | held`` first, then ``hand | left.held``.
    3. Bare-key match: ``worn`` / ``held`` etc. when exactly one
       slot uses that key.

    Returns ``None`` on no-match or the wildcard ``_`` (which
    historically meant "anywhere it fits" — handled at the call
    site as auto-route). Empty hint short-circuits to ``None``.
    """
    if not hint:
        return None

    h = hint.strip().lower()
    if not h or h == "_":
        return None

    short = _SHORT_SLOT_HINTS.get(h)
    if short is not None:
        return short

    from caldanai.lib.rpg.creatures.equipment_routing import (
        SLOT_PAIR, SLOT_TO_PART_KEY,
    )

    tokens = h.split(".")
    if len(tokens) >= 2:
        for split in range(len(tokens) - 1, 0, -1):
            p = ".".join(tokens[:split])
            k = ".".join(tokens[split:])
            for slot, (sp, sk) in SLOT_TO_PART_KEY.items():
                if sp == p and sk == k:
                    return slot
            for slot, pair in SLOT_PAIR.items():
                if any(sp == p and sk == k for (sp, sk) in pair):
                    return slot

    for slot, (_, k) in SLOT_TO_PART_KEY.items():
        if k == h:
            return slot
    for slot, pair in SLOT_PAIR.items():
        if any(k == h for (_, k) in pair):
            return slot

    return None
