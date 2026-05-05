"""Unified expressive-verb dispatch.

The verb system that grew up across multiple cogs (world for
$light/$feed/$gaze/$touch/$listen, social for $hug/$greet/$nod/etc.,
combat for $kill flee-to-passerby) had one routing chain per cog and
three per-entity dispatch shapes (StaticObjectPlugin's ``on_verb``,
PasserbyPlugin's ``SOCIAL_REACTIONS`` cog-side dict reads, Creature's
``on_social``). Adding a new verb meant touching ~6 places.

This module collapses that into one shape:

- :class:`VerbResponder` — the Protocol every targetable entity
  implements. ``matches_token`` (already on every entity type via
  the resolver work) plus ``handle_verb(verb, game, actor, *,
  invocation, **kwargs) -> Optional[str]``. The entity decides
  whether the verb is combat / flavor / consequence based on what
  it is. ``None`` return = "I don't handle this verb" (caller
  walks to the next responder in the chain).

- :func:`resolve_verb_target` — the unified resolution chain.
  Mention path (with doppelganger-disguise) for direct @-targeting,
  text-token path (passerby → silhouette → monster → static_object
  → player_fuzzy) for everything else. Cogs can opt out of entity
  types via ``include_*`` flags.

- :func:`walk_token_chain` — generator yielding token-matching
  responders in priority order so the dispatcher can try each
  until one returns a non-None ``handle_verb`` result. Preserves
  today's "passerby falls through to monster when the NPC has no
  reaction for the verb" behavior.

Cog-side dispatch helpers (the ``dispatch_expressive_verb``
function) live alongside the cog mixin in ``cogs/_verb_dispatch.py``
since they need ``Dispatcher`` + cog ``Context``. This module is
the entity-side contract + resolution; cog-side composition is
elsewhere.

What's NOT here: a ``WarmthAwareResponder`` mixin. Player and
Passerby both think about warmth, but Player's two-layer
intent+acceptance compose (via ``warmth.resolve``) and Passerby's
single-pool render with side-effects (mark_encounter / credits /
acquaintance cue) share zero concrete lines of code. Extract a
mixin only if a third entity type emerges with genuinely shared
logic.
"""

from typing import Any, Iterable, Optional, Protocol, runtime_checkable


@runtime_checkable
class VerbResponder(Protocol):
    """Anything that can be the target of an expressive verb.

    Implementations live on the entity types — ``StaticObjectPlugin``,
    ``PasserbyPlugin``, ``Creature`` (monster), ``Player``. The
    runtime-checkable Protocol shape means duck-typed test fixtures
    and real instances both pass ``isinstance(x, VerbResponder)``
    when they expose the right method names.
    """

    def matches_token(self, token: str) -> bool:
        """Fuzzy / exact match for the cog's token-driven resolution
        chain. Already implemented across ``Creature.matches_token``,
        ``PasserbyPlugin.matches_token``, and (via ``Area.find_static_object``)
        the static-object lookup. Players use display_name + cached
        ``player.name`` matching via the project ``resolve_player``
        helper.
        """
        ...

    def handle_verb(
        self,
        verb: str,
        game: Any,
        actor: Any,
        *,
        invocation: str = "",
        **kwargs,
    ) -> Optional[str]:
        """Dispatch ``verb`` against this responder.

        Returns rendered narration string for the cog to dispatch,
        or ``None`` if this responder doesn't handle the verb (the
        cog falls through to the next responder in the chain, or
        renders a "no response" italic line if no one handles it).

        **Side effects belong here, not in the cog.** Passerby's
        ``mark_encounter`` / ``apply_*_credits`` / ``mark_acquainted``
        / acquaintance-cue dispatch all live inside the passerby's
        ``handle_verb`` so the cog's job stays "find target, call
        handle_verb, dispatch result."

        ``invocation`` carries the literal alias the player typed
        (``"hug"`` / ``"snuggle"`` / ``"cuddle"`` for $hug). Used
        by some flavor lines that quote the verb. ``**kwargs``
        carries verb-specific extras (e.g. $feed's ``fuel_arg``).
        """
        ...


def resolve_verb_target(
    game,
    *,
    token: Optional[str] = None,
    mention: Optional[Any] = None,
    include_passerby: bool = True,
    include_silhouette: bool = False,
    include_monster: bool = True,
    include_static_object: bool = True,
    include_player_fuzzy: bool = True,
) -> Optional[VerbResponder]:
    """Resolve a single target via mention or token.

    Mention path (``mention`` is a Discord ``Member``): unambiguous,
    with one exception — **doppelganger-disguise**. If the active
    monster's name matches the mentioned player's display_name,
    return the monster instead. The disguise is real all the way
    down; whoever bears the name receives the verb.

    Token path: walks priority order (passerby → silhouette →
    monster → static_object → player_fuzzy), returning the FIRST
    entity whose ``matches_token`` accepts. Use
    :func:`walk_token_chain` instead if the caller needs to try
    multiple responders (e.g. when the first match doesn't handle
    the verb and the dispatcher should fall through).

    ``include_*`` flags let cogs exclude entity types — combat
    cogs exclude static_object, world cogs may exclude player_fuzzy
    to keep $touch from accidentally matching player names, etc.

    Returns ``None`` if no responder matched.
    """
    if mention is not None:
        if include_monster and game.monster is not None:
            try:
                if game.monster.name.lower() == mention.display_name.lower():
                    return game.monster
            except AttributeError:
                pass
        if include_player_fuzzy:
            return _player_from_mention(game, mention)
        return None

    if not token:
        return None

    for candidate in walk_token_chain(
        game, token,
        include_passerby=include_passerby,
        include_silhouette=include_silhouette,
        include_monster=include_monster,
        include_static_object=include_static_object,
        include_player_fuzzy=include_player_fuzzy,
    ):
        return candidate
    return None


def walk_token_chain(
    game,
    token: str,
    *,
    include_passerby: bool = True,
    include_silhouette: bool = False,
    include_monster: bool = True,
    include_static_object: bool = True,
    include_player_fuzzy: bool = True,
) -> Iterable[VerbResponder]:
    """Yield every token-matching responder in chain priority.

    Used by the cog's expressive-verb dispatcher to walk past
    responders that match the token but return ``None`` from
    ``handle_verb`` (e.g. the wagoneer matches "wagoneer" but
    doesn't handle ``$touch``; chain falls through to whatever's
    next).

    Today's chain order: passerby → silhouette → monster →
    static_object → player_fuzzy. Static objects match LAST per
    Caels' design rule (omnipresent matches lose to transient
    ones). Players via fuzzy LAST so name collisions don't
    accidentally pick a player when an NPC was meant.

    Each entity type only yields when (a) it's included via the
    flag and (b) the resolver finds a match. ``walk_*`` semantics
    rather than ``return one`` lets the caller drive fallthrough
    on a verb-by-verb basis.
    """
    if include_passerby:
        from caldanai.lib.rpg.helpers.resolvers import resolve_passerby
        npc = resolve_passerby(game, token)
        if npc is not None:
            yield npc

    if include_silhouette:
        from caldanai.lib.rpg.helpers.resolvers import (
            resolve_pending_silhouette,
        )
        sil = resolve_pending_silhouette(game, token)
        if sil is not None:
            yield sil

    if include_monster:
        from caldanai.lib.rpg.helpers.resolvers import resolve_active_monster
        monster = resolve_active_monster(getattr(game, "monster", None), token)
        if monster is not None:
            yield monster

    if include_static_object:
        room0 = getattr(game, "room0", None)
        if room0 is not None:
            obj = room0.find_static_object(token)
            if obj is not None:
                yield obj

    if include_player_fuzzy:
        from caldanai.lib.rpg.helpers.resolvers import resolve_player
        results = resolve_player(game, token)
        if len(results) == 1:
            yield results[0]


def _player_from_mention(game, mention) -> Optional[Any]:
    """Resolve a Discord mention to the in-game ``Player`` instance.
    Returns ``None`` if the mention isn't a registered player in
    this game's player_manager.
    """
    pm = getattr(game, "player_manager", None)
    if pm is None:
        return None
    players = getattr(pm, "players", {}) or {}
    mention_id = getattr(mention, "id", None)
    if mention_id is None:
        return None
    return players.get(mention_id)
