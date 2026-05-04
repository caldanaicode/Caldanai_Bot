"""World-verb cog — generic interaction commands for static
objects in the room.

Five verbs registered:

- ``$light <target>`` — ignite something (campfire, future
  torch / lantern / pyre)
- ``$feed <target> [fuel]`` — provide consumable to an object
  (campfire takes sticks; future pets, shrines, livestock)
- ``$gaze [target]`` — visual fixation. Bare invocation is
  self-directed; with target, dispatches to the matching object
- ``$touch <target>`` — physical contact. May have consequences
  (fire damage; future shrine effects, stone warmth)
- ``$listen [target]`` — auditory attention. Bare invocation is
  self-directed; with target, dispatches to the matching object

Resolution order (per Caels 2026-05-03): static objects match
**last** in any verb that could plausibly target multiple kinds
of entity. The current room's passerby (if any) is checked first
for the verbs they handle; static objects are the omnipresent
fallback. This file's resolver currently only knows about static
objects (passersby own their own social-verb routing in
``rpg_social_commands.py``); future cross-cog verb sharing would
extend the chain here.

Sensory verbs (``$gaze`` / ``$listen``) without a target fall
through to a self-directed pool — the player gazes at the world
generally rather than at a specific object. Active verbs
(``$touch`` / ``$light`` / ``$feed``) without a target return
"X what?" italic prompts — they're meaningless without a target.
"""

from random import choice
from typing import Optional

from discord.ext.commands import (
    BucketType, Cog, Context, command, cooldown, guild_only,
)

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.parser import parse
from caldanai.lib.rpg.helpers.utils import RpgUtilities


_log = get_logger(__name__)


# Self-directed pools for bare sensory verbs. Lightweight — these
# only fire when the player typed the bare verb and we want to
# return *something* in-character rather than a parser error.
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
    """Cog for world-verb dispatch. Each command resolves an
    optional target against the active room's static objects and
    routes to the object's :meth:`on_verb` handler. Plugins opt
    into verbs via :attr:`SUPPORTED_VERBS`."""

    def __init__(self, bot):
        self.bot = bot

    # -----------------------------------------------------------------
    # Verb commands
    # -----------------------------------------------------------------

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
        await self._dispatch_active(ctx, "light", target)

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
        await self._dispatch_feed(ctx, target)

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
        await self._dispatch_sensory(
            ctx, "gaze", target, _GAZE_SELF_DIRECTED,
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
        await self._dispatch_active(ctx, "touch", target)

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
        await self._dispatch_sensory(
            ctx, "listen", target, _LISTEN_SELF_DIRECTED,
        )

    # -----------------------------------------------------------------
    # Dispatch helpers
    # -----------------------------------------------------------------

    async def _dispatch_active(
        self, ctx: Context, verb: str, target: Optional[str],
    ) -> None:
        """Active-verb dispatch ($touch, $light, $feed). Requires
        a target; bare invocation prints a "X what?" italic prompt."""
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        if not target:
            Dispatcher.add(
                game.channel,
                f"*{player.name} {verb}s — but at what?*",
            )
            return
        obj = self._find_target(game, target, verb)
        if obj is None:
            Dispatcher.add(
                game.channel,
                f"*{player.name} sees nothing here to {verb} by the name `{target}`.*",
            )
            return
        line = obj.on_verb(verb, game, player)
        if line:
            Dispatcher.add(game.channel, line)

    async def _dispatch_sensory(
        self,
        ctx: Context,
        verb: str,
        target: Optional[str],
        self_directed_pool: list,
    ) -> None:
        """Sensory-verb dispatch ($gaze, $listen). Bare invocation
        falls through to a self-directed pool — the player engages
        the world generally rather than a specific object."""
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        if not target:
            Dispatcher.add(
                game.channel,
                parse(choice(self_directed_pool), player),
            )
            return
        obj = self._find_target(game, target, verb)
        if obj is None:
            Dispatcher.add(
                game.channel,
                f"*{player.name} {verb}s — but `{target}` doesn't catch on anything here.*",
            )
            return
        line = obj.on_verb(verb, game, player)
        if line:
            Dispatcher.add(game.channel, line)

    async def _dispatch_feed(
        self, ctx: Context, raw_target: Optional[str],
    ) -> None:
        """Special-case dispatch for $feed: target is the FIRST
        whitespace-separated token; everything after is the
        explicit fuel name passed through to the object's handler.
        ``$feed campfire`` — implicit-most-abundant.
        ``$feed campfire stick`` — explicit fuel."""
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return
        if not raw_target:
            Dispatcher.add(
                game.channel,
                f"*{player.name} feeds — but what, and to what?*",
            )
            return
        tokens = raw_target.split(None, 1)
        target = tokens[0]
        fuel_arg = tokens[1] if len(tokens) > 1 else None
        obj = self._find_target(game, target, "feed")
        if obj is None:
            Dispatcher.add(
                game.channel,
                f"*{player.name} sees nothing here to feed by the name `{target}`.*",
            )
            return
        line = obj.on_verb("feed", game, player, fuel_arg)
        if line:
            Dispatcher.add(game.channel, line)

    @staticmethod
    def _find_target(game, target: str, verb: str):
        """Walk the resolution chain for a verb target. Static
        objects match LAST (per design — they're omnipresent and
        more transient matches should win)."""
        if game.room0 is None:
            return None
        # Future: insert passerby + monster + player checks here
        # for any verbs that those entity types want to handle.
        # Today only static objects respond to the world-verb set.
        obj = game.room0.find_static_object(target)
        if obj is None:
            return None
        # Final filter: the matched object must declare the verb.
        if verb not in (obj.SUPPORTED_VERBS or []):
            return None
        return obj

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgWorldCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgWorldCommands(bot))
