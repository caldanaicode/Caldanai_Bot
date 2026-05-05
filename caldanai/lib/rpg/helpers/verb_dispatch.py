"""Cog-side expressive-verb dispatcher.

Sits between Discord-cog command bodies and the entity-side
:class:`VerbResponder` Protocol. One function — :func:`dispatch_expressive_verb`
— handles dead-invoker guarding, target resolution, chain
fallthrough, dispatch, and the various italic-fallback cases
(bare invocation → self-directed pool; bad token → italic miss).

Cog command bodies become two lines:

.. code-block:: python

    @command(name="hug", aliases=["snuggle", "cuddle"])
    async def hug(self, ctx, *, target: str = None):
        await dispatch_expressive_verb(ctx, "hug", target_token=target)

The dispatcher delegates the *what does this verb mean* question
to each :class:`VerbResponder`'s ``handle_verb`` method. The cog
just routes; the entity decides.

Lives in ``helpers/`` rather than ``cogs/`` because the cogs
directory is the bot's auto-extension-loader (every ``*.py``
there gets loaded as a Discord cog with a ``setup()``). This
module is a function, not a cog.
"""

from random import choice
from typing import Any, Callable, Dict, List, Optional

from discord.ext.commands import Context

from caldanai.dispatcher import Dispatcher
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.helpers.verbs import (
    VerbResponder,
    walk_token_chain,
    resolve_verb_target,
)


# Per-verb italic fallback when the player invokes bare with no
# target AND the cog hasn't supplied a self-directed pool. Cog
# can override per-call via the ``self_directed_pool`` argument.
_GENERIC_BARE_FALLBACK: Dict[str, str] = {
    # Most verbs reasonable as bare-action italics.
    "lean":     "*{name} leans against the air, which holds.*",
    "sit":      "*{name} sits down where they stand.*",
    "rest":     "*{name} rests for a moment, eyes half-closing.*",
    "ponder":   "*{name} ponders the middle distance.*",
    "thank":    "*{name} murmurs a quiet thanks to no one in particular.*",
    "tend":     "*{name} tends to themselves a moment.*",
    "bite":     "*{name} bites at nothing in particular.*",
    "bow":      "*{name} bows to the empty clearing.*",
}


async def dispatch_expressive_verb(
    ctx: Context,
    verb: str,
    *,
    target_token: Optional[str] = None,
    mention: Optional[Any] = None,
    self_directed_pool: Optional[List[str]] = None,
    dead_invoker_pool: Optional[List[str]] = None,
    require_target: bool = False,
    bad_token_template: Optional[str] = None,
    include_passerby: bool = True,
    include_silhouette: bool = False,
    include_monster: bool = True,
    include_static_object: bool = True,
    include_player_fuzzy: bool = True,
    **kwargs,
) -> None:
    """Run the full expressive-verb pipeline:

    1. Resolve game + actor.
    2. Dead-invoker guard (single check; per-verb flavor via
       ``dead_invoker_pool``).
    3. Mention path (with doppelganger-disguise) OR token-chain
       walk.
    4. For each token-matching responder, call ``handle_verb``;
       first non-``None`` result wins. ``""`` means "consumed
       silent" (responder claimed the verb but produced no
       narration — dispatch nothing, do not fall through).
    5. Bare invocation (no token, no mention) → self-directed
       pool if supplied, else generic bare-action italic from
       :data:`_GENERIC_BARE_FALLBACK`, else a shrug.
    6. Bad token (token given, no responder claimed) → italic
       miss line.

    ``**kwargs`` are forwarded to ``handle_verb`` for verb-specific
    extras ($feed's ``fuel_arg``, future verbs' parameters).

    No return value — this function dispatches output via
    :class:`Dispatcher` directly.
    """
    game, player = await RpgUtilities.get_game_and_player(ctx)
    if game is None or player is None:
        return

    # Dead-invoker guard fires only when the cog provides a flavor
    # pool — opt-in per verb. World verbs ($touch, $light, $gaze,
    # etc.) don't gate at this layer because individual entities
    # handle dead-actor cases themselves (e.g. campfire's $touch
    # has its own is_dead block). Social verbs ($hug, $glare, etc.)
    # provide a pool here so the corpse-tries-to-hug case renders
    # appropriately at the cog layer.
    if dead_invoker_pool and RpgUtilities.dead_invoker_guard(
        game.channel, player, dead_invoker_pool,
    ):
        return

    # Mention path. Three resolution branches in priority order:
    #
    # 1. Bot-mention → BotResponder. The narrator handles its own
    #    scripted replies per verb. Co-located in
    #    ``creatures/bot_responder.py``.
    # 2. Doppelganger-disguise → active monster. If the mentioned
    #    player's display_name matches the active monster's name,
    #    the monster receives the gesture (the disguise is real
    #    all the way down to who responds).
    # 3. Otherwise → in-game Player via the canonical async
    #    ``RpgUtilities.get_player``.
    if mention is not None:
        target = None
        bot_user = (
            getattr(getattr(ctx, "bot", None), "user", None)
        )
        # Identity check by id, not by ``is``: Discord delivers
        # @-mentions as fresh ``Member`` objects each message, while
        # ``ctx.bot.user`` is the cached ``User`` — same Discord
        # account, different Python objects.
        if (
            bot_user is not None
            and getattr(mention, "id", None) == getattr(bot_user, "id", None)
        ):
            from caldanai.lib.rpg.creatures.bot_responder import BotResponder
            target = BotResponder(channel=game.channel)
        elif include_monster and getattr(game, "monster", None) is not None:
            try:
                if game.monster.name.lower() == mention.display_name.lower():
                    target = game.monster
            except AttributeError:
                pass
        if target is None and include_player_fuzzy:
            target = await RpgUtilities.get_player(
                mention, game=game, notify=False,
            )
        if target is None:
            Dispatcher.add(
                game.channel,
                f"*{player.name} {verb}s — but the mention didn't catch.*",
            )
            return
        result = target.handle_verb(
            verb, game, player,
            invocation=ctx.invoked_with or verb,
            **kwargs,
        )
        if result:
            Dispatcher.add(game.channel, result)
        return

    # Token path.
    if target_token:
        for candidate in walk_token_chain(
            game, target_token,
            include_passerby=include_passerby,
            include_silhouette=include_silhouette,
            include_monster=include_monster,
            include_static_object=include_static_object,
            include_player_fuzzy=include_player_fuzzy,
        ):
            result = candidate.handle_verb(
                verb, game, player,
                invocation=ctx.invoked_with or verb,
                **kwargs,
            )
            if result is None:
                # This responder doesn't handle the verb. Try
                # the next one in the chain.
                continue
            # Result is "" (consumed silent) or non-empty (render).
            if result:
                Dispatcher.add(game.channel, result)
            return

        # No responder in the chain claimed the verb.
        miss_line = (bad_token_template or
                     f"*{player.name} sees nothing here to {verb} by the name `{target_token}`.*"
                     ).format(
                         name=player.name, verb=verb, target=target_token,
                     )
        Dispatcher.add(game.channel, miss_line)
        return

    # Bare invocation — no token, no mention.
    if require_target:
        # Active verbs ($touch, $light, $feed) want an explicit
        # "what?" prompt rather than a self-directed beat — they're
        # meaningless without a target and the prompt nudges the
        # player toward correct usage.
        Dispatcher.add(
            game.channel,
            f"*{player.name} {verb}s — but at what?*",
        )
        return

    if self_directed_pool:
        Dispatcher.add(
            game.channel,
            parse(choice(self_directed_pool), player),
        )
        return

    fallback = _GENERIC_BARE_FALLBACK.get(verb)
    if fallback:
        Dispatcher.add(
            game.channel,
            fallback.format(name=player.name),
        )
        return

    Dispatcher.add(
        game.channel,
        f"*{player.name} {verb}s, vaguely.*",
    )
