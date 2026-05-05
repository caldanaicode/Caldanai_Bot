"""World-verb cog — generic interaction commands for static
objects, passersby, monsters, and any other :class:`VerbResponder`
in the room.

Five verbs registered:

- ``$light <target>`` — ignite something (campfire, future
  torch / lantern / pyre)
- ``$feed <target> [fuel]`` — provide consumable to an object
  (campfire takes sticks; future pets, shrines, livestock)
- ``$gaze [target]`` — visual fixation. Bare invocation is
  self-directed; with target, dispatches via the unified verb
  dispatcher
- ``$touch <target>`` — physical contact. May have consequences
  (fire damage; future shrine effects, stone warmth)
- ``$listen [target]`` — auditory attention. Bare invocation is
  self-directed; with target, dispatches via the unified verb
  dispatcher

Each command body is two lines: validate context, then call
:func:`dispatch_expressive_verb` with the verb name + optional
target. The dispatcher walks the unified resolution chain
(passerby → silhouette → monster → static_object → player_fuzzy
by default; cogs can opt out of entity types via flags) and the
matching responder's ``handle_verb`` decides how to respond.

Sensory verbs (``$gaze`` / ``$listen``) without a target fall
through to a self-directed pool — the player gazes at the world
generally rather than at a specific object. Active verbs without
a target (``$touch`` / ``$light``) get the dispatcher's
generic-bare fallback ("X verbs, vaguely.") which is fine for
edge cases — a player who types bare ``$touch`` probably typo'd.
"""

from typing import Optional

from discord.ext.commands import (
    BucketType, Cog, Context, command, cooldown, guild_only,
)

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.verb_dispatch import dispatch_expressive_verb


_log = get_logger(__name__)


# Self-directed pools for bare sensory verbs.
_GAZE_SELF_DIRECTED = [
    "*@1np gaze settles somewhere in the middle distance, soft and unfocused.*",
    "*@1 lets the eye wander the clearing — nothing in particular, just the texture of the place.*",
    "*@1 stares off, watching the world keep being itself.*",
    "*@1 takes the clearing in slowly, the way you read a familiar room.*",
]

_LISTEN_SELF_DIRECTED = [
    "*@1 listens to the world for a long moment — wind, distant water, the small sounds of being.*",
    "*@1 stops, listens. The clearing holds its quiet.*",
    "*@1 tilts an ear to the world. The world is not in a hurry to answer.*",
    "*@1 goes still and listens. Something settles in the listening itself.*",
]


class RpgWorldCommands(Cog):
    """Cog for world-verb dispatch. Each command delegates to
    :func:`dispatch_expressive_verb` which walks the unified
    :class:`VerbResponder` chain and routes to whichever entity
    type matches the token (or to a self-directed pool if the
    verb is bare)."""

    def __init__(self, bot):
        self.bot = bot

    @command(name="light", brief="Light something flammable.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def light(self, ctx: Context, *, target: str = None):
        """
        Light something flammable in the area — a campfire, a
        torch, whatever's around. Requires a target.

        (5-second cool-down)

        :param target: The object to light (e.g. ``$light campfire``).
        """
        await dispatch_expressive_verb(
            ctx, "light",
            target_token=target,
            require_target=True,
        )

    @command(name="feed", brief="Feed something with fuel from your inventory.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def feed(self, ctx: Context, *, target: str = None):
        """
        Feed an object with appropriate consumable from your
        inventory. ``$feed campfire`` finds the most-abundant fuel
        you have; ``$feed campfire stick`` picks a specific fuel.
        Requires a target.

        (5-second cool-down)

        :param target: The object to feed (optionally followed by
            an explicit fuel name).
        """
        # Special-case parse for $feed: trailing token after the
        # object is the optional explicit fuel name. Forward via
        # kwargs so the receiving entity (campfire) gets it as
        # ``fuel_arg`` in handle_verb's **kwargs (currently lands
        # as args[0] for back-compat with the existing on_verb
        # signature).
        target_token = None
        fuel_arg = None
        if target:
            tokens = target.split(None, 1)
            target_token = tokens[0] if tokens else None
            fuel_arg = tokens[1] if len(tokens) > 1 else None
        await dispatch_expressive_verb(
            ctx, "feed",
            target_token=target_token,
            require_target=True,
            fuel_arg=fuel_arg,
        )

    @command(name="gaze", aliases=["stare"], brief="Gaze at something — or at the world generally.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def gaze(self, ctx: Context, *, target: str = None):
        """
        Gaze at an object (campfire, stone field, etc.) or — with
        no target — at the world generally.

        (5-second cool-down)

        :param target: The object to gaze at. Omit for a self-
            directed beat.
        """
        await dispatch_expressive_verb(
            ctx, "gaze",
            target_token=target,
            self_directed_pool=_GAZE_SELF_DIRECTED,
        )

    @command(name="touch", brief="Reach out and touch something — perhaps unwisely.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def touch(self, ctx: Context, *, target: str = None):
        """
        Touch a physical feature of the room. Some respond
        gently; some bite back. Requires a target.

        (5-second cool-down)

        :param target: The object to touch.
        """
        await dispatch_expressive_verb(
            ctx, "touch",
            target_token=target,
            require_target=True,
        )

    @command(name="listen", brief="Listen — to something specific, or to the world.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def listen(self, ctx: Context, *, target: str = None):
        """
        Listen to a specific object's sound, or — with no target —
        to the world generally.

        (5-second cool-down)

        :param target: The object to listen to. Omit for a self-
            directed beat.
        """
        await dispatch_expressive_verb(
            ctx, "listen",
            target_token=target,
            self_directed_pool=_LISTEN_SELF_DIRECTED,
        )

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgWorldCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgWorldCommands(bot))
