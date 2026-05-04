import io
import pprint
from enum import Enum
from typing import Any, Optional

from discord import Embed, File as DiscordFile, Guild
from discord.ext.commands import (
    BucketType,
    Cog,
    Context,
    check_any,
    command,
    cooldown,
    group,
    guild_only,
    has_permissions,
    is_owner,
)

from caldanai.db import DB
from caldanai.dispatcher import Dispatcher
from caldanai.lib.bot import Bot
from caldanai.lib.rpg import Roles, parse
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.utils import RpgUtilities
from caldanai.lib.rpg.inventory import Inventory
from caldanai.logger import get_logger


_log = get_logger(__name__)


# Static plugin data that's identical across every spawn of a creature —
# pruned in `compact` mode to keep dumps legible during playtesting.
_COMPACT_SKIP_KEYS = {"debuffs", "flavor"}


def _to_plain(
    obj: Any,
    depth: int = 0,
    seen: Optional[set] = None,
    skip_keys: Optional[set] = None,
) -> Any:
    """Recursively convert an object to primitive types for pprint.

    Handles cycles (via id tracking), caps depth to avoid runaway dumps,
    and unwraps dataclasses/objects via their ``__dict__``. Enums render
    as their str() form; everything exotic falls back to repr().

    ``skip_keys`` is applied to dict and ``__dict__`` traversal alike so
    noisy static fields (e.g., per-injury debuff tables) can be pruned
    in compact mode.
    """
    MAX_DEPTH = 8
    if seen is None:
        seen = set()
    if skip_keys is None:
        skip_keys = set()

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Enum):
        return str(obj)
    if depth >= MAX_DEPTH:
        return repr(obj)

    oid = id(obj)
    if oid in seen:
        return f"<cycle: {type(obj).__name__}>"
    seen = seen | {oid}

    if isinstance(obj, dict):
        return {
            _to_plain(k, depth + 1, seen, skip_keys):
                _to_plain(v, depth + 1, seen, skip_keys)
            for k, v in obj.items()
            if k not in skip_keys
        }
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [_to_plain(v, depth + 1, seen, skip_keys) for v in obj]
    if hasattr(obj, "__dict__") and vars(obj):
        return {
            "__class__": type(obj).__name__,
            **{
                k: _to_plain(v, depth + 1, seen, skip_keys)
                for k, v in vars(obj).items()
                if k not in skip_keys
            },
        }
    return repr(obj)


class RpgAdminCommands(Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @group(aliases=["rpg"], brief="Groups the various Game commands.", case_insensitive=True)
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def game_cmd(self, ctx: Context):
        """
        Groups the various game commands for administrators. This command cannot be used on its own.
        """

        if ctx.invoked_subcommand is None:
            Dispatcher.add(ctx, "This command cannot be used on its own.")
            return

        if ctx.guild is None:
            Dispatcher.add(ctx, "A game cannot be started or ended from a direct message or a group message.")
            return

    @game_cmd.command(brief="Begins an RPG game on the server in the current channel.")
    async def create(self, ctx: Context) -> bool:
        """
        Begins an RPG game on the server in the current channel. Only a single game per server is supported.
        """

        try:
            if DB.get_game(ctx.guild.id, ctx.channel.id) is not None:
                Dispatcher.add(ctx, "There is already a game running in this channel.")

            else:
                DB.insert_game(ctx.guild.id, ctx.channel.id)
                await RpgUtilities.add_game(gid=ctx.guild.id, chid=ctx.channel.id)
                Dispatcher.add(ctx, "A new game has been started in this channel!")
                return True
        except Exception as e:
            Dispatcher.add(ctx, "There appears to be an error with the database connection. Please try again later.")
            _log.error(e)

        return False

    @game_cmd.command(brief="Removes the RPG game for this server. WARNING: Cannot be undone.")
    async def remove(self, ctx: Context) -> None:
        """
        Removes the RPG game for this server. WARNING: Cannot be undone.
        Upon removal, a new game may be created but data from the removed game is not recoverable.
        """

        if not await RpgUtilities.check_game_exists(ctx):
            return

        await RpgUtilities.remove_game(ctx.guild.id, ctx.channel.id)
        Dispatcher.add(ctx, "The game has been removed.")

    @group(brief="Role settings for the game.", case_insensitive=True)
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def roles(self, ctx: Context):
        """
        This command cannot be used on its own, and requires a subcommand.
        """
        pass

    @roles.command(brief="Adds roles for the game, if the bot has the permissions.", aliases=["add"])
    async def add_roles(self, ctx: Context):
        """
        Adds roles for the game, if the bot has the permissions.

        This command is only necessary for games which existed before roles were added, or if the bot's permissions
        have changed to allow the management of roles.
        """
        if game := await RpgUtilities.get_game(ctx):
            if game.player_manager.roles[Roles.ALL] is None:
                Dispatcher.add(ctx, "Adding roles may take a moment. Please wait...")
                await RpgUtilities.create_roles(game)
                if game.player_manager.roles[Roles.ALL]:
                    Dispatcher.add(ctx, "Roles added!")
                else:
                    Dispatcher.add(ctx, "There was a problem adding the roles. I may not have permission to do that.")
            else:
                Dispatcher.add(ctx, "The roles already exist.")

        else:
            Dispatcher.add(ctx, "There is no game running on this server.")

    @roles.command(brief="Removes roles for the game, if the bot has the permissions.", aliases=["remove"])
    async def remove_roles(self, ctx: Context):
        """
        Removes roles for the game, if the bot has the permissions.

        This command is only necessary for games which existed before roles were added, or if the bot's permissions
        have changed to allow the management of roles.
        """
        if (
            (game := await RpgUtilities.get_game(ctx))
            and Roles.ALL in game.player_manager.roles.keys()
            and game.player_manager.roles[Roles.ALL] is not None
        ):
            Dispatcher.add(ctx, "Removing roles may take a moment. Please wait...")
            await RpgUtilities.delete_roles(game)
            if game.player_manager.roles[Roles.ALL]:
                Dispatcher.add(ctx, "There was a problem removing the roles. I may not have permission to do that.")
            else:
                Dispatcher.add(ctx, "Roles removed!")

    @command(brief="Pass in a mention to call down the wrath of the Divine upon some hapless player.")
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def smite(self, ctx: Context):
        """
        Pass in a mention to call down the wrath of the Divine upon some hapless player.

        (5-second cool-down server-wide)
        """
        if game := await RpgUtilities.get_game(ctx):
            if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
                msg = (
                    "An angry scar tears across the sky and an ominous red light pours out. Fire begins to rain "
                    "upon the land, burning everything it touches..."
                )

                for mention in ctx.message.mentions:
                    target = await RpgUtilities.get_player(mention, game=game, notify=False)
                    if target:
                        target.apply_damage(target.health)
                        msg += parse(
                            "\n\n@1 cannot escape the righteous fire, and an enormous ball of molten lava consumes "
                            "@1o. @1ac screams last but a moment, before all that remains is a burnt skeleton, "
                            "and cinders lapping away at the cracks.",
                            target,
                        )

                msg += "\n\nThe hole in the sky vanishes, and the strange light with it."
                msgs = Dispatcher.split_message(msg)
                for m in msgs:
                    Dispatcher.add(game.channel, m)

    @command(brief="Resurrects a dead player, because maybe someone feels guilty.")
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def unsmite(self, ctx: Context):
        """
        Resurrects a dead player, because maybe someone feels guilty.

        (5-second cool-down server-wide)
        """
        if game := await RpgUtilities.get_game(ctx):
            if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
                msg = (
                    f"A radiant light bursts forth from the bod{'ies' if len(ctx.message.mentions) > 1 else 'y'} "
                    f"of "
                )

                corpses = []
                for mention in ctx.message.mentions:
                    target = await RpgUtilities.get_player(mention, game=game, notify=False)
                    if target is None:
                        continue
                    # "Needs healing" covers both body-HP damage and
                    # any non-full body part — a player with a
                    # destroyed arm but full body HP should still be
                    # restored by unsmite, since the parts and the
                    # body HP are parallel accounting under Model D.
                    if not target.is_injured():
                        continue

                    # Full restore: body HP, every part, regen reset,
                    # dirty flag. Divine light is total — no selective
                    # half-measures on an unsmite.
                    target.heal_fully()
                    corpses.append(target.name)

                if corpses:
                    if len(corpses) > 1:
                        c = ", ".join(corpses[:-1]) + " and " + corpses[-1]
                    else:
                        c = corpses[0]
                    msg += f"{c}, who now appear{'' if len(corpses) > 1 else 's'} whole."
                    Dispatcher.add(game.channel, msg)
                else:
                    Dispatcher.add(game.channel, "Everyone mentioned appears to already be in good health.")

    @command(brief="Test-only: force-pray with a specific d20 result, bypassing cooldown.")
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def forcepray(self, ctx: Context, *args: str):
        """Run pray's resolution flow with a forced d20 result,
        bypassing the 60s pray cooldown and the d20 RNG.

        Useful for branch-testing pray narration deterministically:
        ``$forcepray 17`` lands the d20-17 heal branch every time;
        ``$forcepray 1`` lands the lightning sacrifice; ``$forcepray
        20`` lands the party-wide miracle (and the hidden 1d6 smite
        roll still rolls live).

        Mention a player to drive their pray (e.g. ``$forcepray
        @Vael 17`` if the invoker is dead and needs the healthy
        kin to do the praying); without a mention, the invoker is
        the praying player. The mention and the d20 value can
        appear in either order — the d20 is found by scanning args
        for the first integer 1-20.

        Owner / manage_guild only.
        """
        d20_value: Optional[int] = None
        for arg in args:
            try:
                v = int(arg)
            except ValueError:
                continue
            if 1 <= v <= 20:
                d20_value = v
                break

        if d20_value is None:
            Dispatcher.add(
                ctx,
                "Usage: `$forcepray [@target] <d20-value>` — d20 must be 1-20.",
            )
            return

        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        if ctx.message.mentions:
            target_member = ctx.message.mentions[0]
        else:
            target_member = ctx.author

        praying_player = await RpgUtilities.get_player(
            target_member, game=game, notify=False
        )
        if praying_player is None:
            Dispatcher.add(ctx, "Praying player not found.")
            return

        if praying_player.is_dead():
            Dispatcher.add(
                ctx,
                f"{praying_player.name} is dead — pray's dead-player "
                f"flavor short-circuits the heal flow. Pick an alive "
                f"praying player.",
            )
            return

        user_cog = self.bot.get_cog("RpgUserCommands")
        if user_cog is None:
            Dispatcher.add(ctx, "User commands cog not loaded.")
            return

        await user_cog._execute_pray(game, praying_player, d20_value=d20_value)

    @group(brief="Admin operations on creatures (players or monsters).", case_insensitive=True)
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def creature(self, ctx: Context):
        """Admin operations that target creatures — players via
        mention, the current monster via fuzzy name match, or the
        currently spawned monster as default. Subcommands cover
        per-creature state changes (destroy parts, future heal /
        inspect / etc.).

        Use ``$help creature <subcommand>`` for details.
        """
        if ctx.invoked_subcommand is None:
            Dispatcher.add(
                ctx,
                "Usage: `$creature <subcommand> [args]`. "
                "See `$help creature` for available subcommands.",
            )

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @creature.command(
        name="destroy",
        brief="Force-destroys named body parts on a player or monster.",
    )
    async def creature_destroy(self, ctx: Context, *args: str):
        """Force-destroys named body parts on a target creature.

        Target resolution:

        - ``$creature destroy @player <part> [<part>...]`` —
          targets the mentioned player.
        - ``$creature destroy <monster-name> <part> [<part>...]``
          — targets the currently-spawned monster if its name
          contains the provided substring (fuzzy match).
        - ``$creature destroy <part> [<part>...]`` — defaults to
          the currently-spawned monster (legacy ``$spawn destroy``
          behavior).

        Part names use fuzzy match — ``h.1`` resolves to ``head.1``,
        ``arm.l`` to ``arm.left``, etc.

        Each destruction fires the part's ``on_destroyed`` hook so
        side effects (gear drops, debuff applies, narrative beats)
        proceed exactly as they would on a normal kill — but does
        NOT itself end-of-state the target, so part-driven death
        rules (hydra zero-heads, critical-part destruction) still
        flow through their normal detection paths in the next combat
        round.

        Intended for playtest / admin use only.
        """
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        args_list = list(args)
        target = None

        # Mention-first resolution. Mention text in args is the
        # raw ``<@!id>`` token — strip it from the parts list.
        if ctx.message.mentions:
            target_member = ctx.message.mentions[0]
            target = await RpgUtilities.get_player(
                target_member, game=game, notify=False
            )
            args_list = [a for a in args_list if not a.startswith("<@")]

        # Fuzzy monster-name match if no mention. Routes through
        # ``resolve_active_monster`` (the shared spawned-monster
        # resolver under all targeting commands) instead of an
        # ad-hoc substring ``in`` check, so ``$creature destroy
        # hyd head.1`` resolves a hexed hydra the same way ``$kill
        # hyd`` does.
        if target is None and args_list:
            from caldanai.lib.rpg.helpers.resolvers import resolve_active_monster
            matched = resolve_active_monster(game.monster, args_list[0])
            if matched is not None:
                target = matched
                args_list = args_list[1:]

        # Default to the spawned monster.
        if target is None:
            target = game.monster

        if target is None:
            Dispatcher.add(
                ctx,
                "No target found — mention a player, name a monster, "
                "or have a monster spawned.",
            )
            return

        if not args_list:
            Dispatcher.add(
                ctx,
                "Usage: `$creature destroy [@target | <monster-name>] "
                "<part> [<part>...]`",
            )
            return

        target_name = target.name
        # Players don't have ``uses_article``; monsters do (default
        # True). ``getattr`` with a False default cleanly produces
        # no article for players and the right one for monsters
        # without needing an isinstance check.
        article = "the " if getattr(target, "uses_article", False) else ""

        destroyed = []
        unmatched = []
        for name in args_list:
            matches = target.find_parts(name)
            if not matches:
                unmatched.append(name)
                continue
            for part in matches:
                if part.is_destroyed():
                    continue
                # Route through ``apply_damage`` with the part as
                # target so the canonical critical-part safety sweep
                # fires (zeros body HP when a critical part destroys)
                # and gear placements on the destroyed part clear via
                # the standard pipeline. Caels 2026-05-01 caught the
                # "is_dead with body HP at 20" oddity that the prior
                # direct ``part.health = 0`` mutation produced — pure
                # ``is_dead`` returned True correctly but downstream
                # displays still showed the body-HP number, reading
                # as inconsistent. The apply_damage return is
                # discarded; we render our own admin announcement
                # below to keep the admin output clean.
                target.apply_damage(
                    part.health_max,
                    dmg_type=None,
                    target_part=part,
                )
                destroyed.append(part)
                hook_msg = part.on_destroyed(target)
                if hook_msg:
                    Dispatcher.add(game.channel, parse(hook_msg, target))

        if destroyed:
            part_labels = ", ".join(p.display_name for p in destroyed)
            Dispatcher.add(
                game.channel,
                f"*An unseen force crushes {article}{target_name}'s "
                f"{part_labels}.*",
            )
        if unmatched:
            unmatched_str = ", ".join(f"`{n}`" for n in unmatched)
            Dispatcher.add(
                ctx,
                f"No body part matched: {unmatched_str}",
            )

    @group(brief="Displays or sets monster + passerby spawning options.", case_insensitive=True)
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def spawn(self, ctx: Context):
        """
        Used alone, displays current state + tunables for both
        monster and passerby spawners. See the subcommands to force
        a spawn / depart, or ``$spawn config`` to tune timing.

        (5-second cool-down server-wide)
        """

        if not await RpgUtilities.check_game_exists(ctx):
            return

        if ctx.invoked_subcommand is None:
            guild: Guild = ctx.guild
            game = self.bot.games.get(ctx.channel.id)
            embed = self._build_spawn_overview_embed(game, guild)
            Dispatcher.add(ctx, embed=embed)

    def _build_spawn_overview_embed(self, game, guild: Guild) -> Embed:
        """Compose the bare-``$spawn`` overview: monster + passerby
        live state and current tunables in one embed."""
        embed = Embed(title="Spawn Overview")
        embed.set_thumbnail(url=guild.icon.url)

        # Monster column.
        embed.add_field(
            name="Monster Timing",
            value=f"{' - '.join(map(str, game.spawn_timer_range))} seconds",
            inline=True,
        )
        embed.add_field(
            name="Monster Duration",
            value=f"{int(game.spawn_duration / 60)} minutes",
            inline=True,
        )
        embed.add_field(
            name="Loot Duration",
            value=f"{int(game.loot_duration / 60)} minutes",
            inline=True,
        )
        embed.add_field(
            name="Monster Spawning",
            value="enabled" if game.use_spawn_timer else "disabled",
            inline=True,
        )
        m_routine = self._find_routine_remaining(game, game.do_spawn)
        if m_routine is not None:
            embed.add_field(
                name="Next Monster",
                value=f"{int(m_routine / 60)} minutes",
                inline=True,
            )
        embed.add_field(
            name="Present Monster",
            value=str(game.monster.name) if game.monster else "—",
            inline=True,
        )

        # Passerby column.
        embed.add_field(
            name="Passerby Timing",
            value=f"{' - '.join(map(str, game.passerby_spawn_range))} seconds",
            inline=True,
        )
        embed.add_field(
            name="Passerby Stay",
            value=f"{int(game.passerby_depart_after / 60)} minutes",
            inline=True,
        )
        embed.add_field(
            name="Passerby Spawning",
            value="enabled" if game.use_passerby_timer else "disabled",
            inline=True,
        )
        p_routine = self._find_routine_remaining(game, game.do_passerby_spawn)
        if p_routine is not None:
            embed.add_field(
                name="Next Passerby",
                value=f"{int(p_routine / 60)} minutes",
                inline=True,
            )
        present = (
            game.passerby.name if game.passerby is not None
            else (
                f"{game.pending_silhouette.name} (silhouette)"
                if game.pending_silhouette is not None else "—"
            )
        )
        embed.add_field(name="Present Passerby", value=present, inline=True)
        return embed

    @staticmethod
    def _find_routine_remaining(game, routine_method):
        """Return seconds remaining until ``routine_method`` next
        fires on the game clock, or ``None`` if it isn't scheduled.
        Mirrors the lookup in the legacy ``$spawn`` overview."""
        r, i = game.game_clock.find_routine(routine_method.__qualname__)
        if not r:
            return None
        routine = r[i]
        return (
            routine.time_added - game.game_clock.get_tick_time()
            + routine.seconds
        )

    # -----------------------------------------------------------------
    # Top-level action verbs: force-spawn / kill / depart / item
    # -----------------------------------------------------------------

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Forces a monster to spawn.")
    async def monster(self, ctx: Context, monster: Optional[str] = None):
        """
        Forces a monster to spawn.

        :param monster: the filename of the monster to spawn. If not provided, randomly chooses an available monster.
        """

        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if game.monster is None:
            game.game_clock.remove_routine(game.do_spawn)
            await game.do_spawn(monster)
            return

        Dispatcher.add(game.channel, f"There is already a {game.monster.name} present!")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Forces a passerby NPC to arrive.")
    async def passerby(self, ctx: Context, name: Optional[str] = None):
        """
        Forces a passerby NPC to arrive in the present (not silhouette)
        state, regardless of combat. Skips if a passerby or silhouette
        is already present.

        :param name: The plugin stem (e.g. ``wagoneer``) or alias of
            the NPC to spawn. If omitted, picks one at random from
            the time-of-day-eligible pool.
        """
        from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
        from caldanai.lib.rpg.creatures.passersby.spawn import pick_npc
        from caldanai.lib.rpg.creatures.passersby.rendering import render_npc_only
        from random import choice as _choice

        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if game.passerby is not None:
            Dispatcher.add(
                game.channel,
                f"A {game.passerby.name} is already present.",
            )
            return
        if game.pending_silhouette is not None:
            Dispatcher.add(
                game.channel,
                f"A {game.pending_silhouette.name} is already in silhouette.",
            )
            return

        # Resolve NPC class — exact match, then fuzzy, then random.
        npc_cls = None
        if name:
            npc_cls = PasserbyPlugin.get_plugin_class(name)
            if npc_cls is None:
                candidates = PasserbyPlugin.find_plugin_classes(name)
                if len(candidates) == 1:
                    npc_cls = candidates[0]
                elif len(candidates) > 1:
                    display = ", ".join(
                        sorted(c.__module__.rsplit(".", 1)[-1] for c in candidates)
                    )
                    Dispatcher.add(
                        ctx,
                        f"Did you mean one of: {display}? "
                        f"(`{name}` matched {len(candidates)} passersby.)"
                    )
                    return
                else:
                    Dispatcher.add(ctx, f"No passerby matching `{name}`.")
                    return
        else:
            npc_cls = pick_npc(game)
            if npc_cls is None:
                Dispatcher.add(
                    ctx,
                    "No passersby are eligible for the current time of day.",
                )
                return

        npc = npc_cls()
        game.passerby = npc

        # Dispatch arrival from the present-arrival pool. Force-spawn
        # always uses ARRIVAL_POOL even if combat is active —
        # silhouette mode is reachable via the natural timer; this
        # command is for testing the present-state interaction surface.
        if npc.ARRIVAL_POOL:
            Dispatcher.add(
                game.channel,
                render_npc_only(_choice(npc.ARRIVAL_POOL), npc),
            )
        # Schedule depart so the test NPC doesn't linger forever.
        game.game_clock.add_routine(
            game.do_passerby_depart, game.passerby_depart_after, True,
        )

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Forces the current monster to die.")
    async def kill(self, ctx: Context):
        """
        Forces the current monster to die.
        """

        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if game.monster is None:
            Dispatcher.add(game.channel, "There is no monster present!")
            return

        await game.kill_monster()

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Forces the present passerby to depart.")
    async def depart(self, ctx: Context):
        """
        Forces the present passerby to walk off via their
        DEPARTURE_POOL. No-op if no passerby is present.
        """
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if game.passerby is None:
            Dispatcher.add(game.channel, "There is no passerby present.")
            return
        await game.do_passerby_depart()

    # -----------------------------------------------------------------
    # $spawn config — tunables sub-group, split monster vs passerby
    # -----------------------------------------------------------------

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.group(name="config", brief="Tune monster or passerby spawn timings.", invoke_without_command=True, case_insensitive=True)
    async def config(self, ctx: Context):
        """
        Tunable settings for the spawn pipelines. See the
        ``monster`` and ``passerby`` sub-groups for the actual
        knobs. Bare ``$spawn config`` echoes the same overview
        as bare ``$spawn``.
        """
        if ctx.invoked_subcommand is None:
            game = self.bot.games.get(ctx.channel.id)
            if not game:
                return
            embed = self._build_spawn_overview_embed(game, ctx.guild)
            Dispatcher.add(ctx, embed=embed)

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config.group(name="monster", brief="Monster spawn-timing tunables.", invoke_without_command=True, case_insensitive=True)
    async def config_monster(self, ctx: Context):
        """Subcommand group for monster timing tunables.
        ``min`` / ``max`` / ``duration`` / ``loot`` / ``set``."""
        if ctx.invoked_subcommand is None:
            game = self.bot.games.get(ctx.channel.id)
            if not game:
                return
            Dispatcher.add(
                game.channel,
                f"Monster: spawn `{' - '.join(map(str, game.spawn_timer_range))}` "
                f"seconds | duration `{int(game.spawn_duration / 60)}` min | "
                f"loot `{int(game.loot_duration / 60)}` min | "
                f"{'enabled' if game.use_spawn_timer else 'disabled'}",
            )

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_monster.command(name="min", aliases=["minimum"], brief="Min minutes between monster spawns.")
    async def config_monster_min(self, ctx: Context, minutes: int = None):
        """:param minutes: Minimum minutes before another monster can spawn."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Minimum spawn time is {game.spawn_timer_range[0] / 60} minutes.")
            return
        if minutes <= 1:
            Dispatcher.add(game.channel, "Minimum spawn time must be more than 1 minute.")
            return
        if minutes >= game.spawn_timer_range[1] / 60:
            Dispatcher.add(
                game.channel,
                f"Minimum spawn time must be less than the maximum spawn time of {game.spawn_timer_range[1] / 60} minutes.",
            )
            return
        game.spawn_timer_range = (minutes * 60, game.spawn_timer_range[1])
        game.save()
        Dispatcher.add(game.channel, "Minimum spawn time has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_monster.command(name="max", aliases=["maximum"], brief="Max minutes between monster spawns.")
    async def config_monster_max(self, ctx: Context, minutes: int = None):
        """:param minutes: Maximum minutes before another monster can spawn."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Maximum spawn time is {game.spawn_timer_range[1] / 60} minutes.")
            return
        if minutes <= 1:
            Dispatcher.add(game.channel, "Maximum spawn time must be more than 1 minute.")
            return
        if minutes <= game.spawn_timer_range[0] / 60:
            Dispatcher.add(
                game.channel,
                f"Maximum spawn time must be greater than the minimum spawn time of {game.spawn_timer_range[0] / 60} minutes.",
            )
            return
        game.spawn_timer_range = (game.spawn_timer_range[0], minutes * 60)
        game.save()
        Dispatcher.add(game.channel, "Maximum spawn time has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_monster.command(name="duration", aliases=["dur", "d"], brief="Minutes a monster waits before combat triggers.")
    async def config_monster_duration(self, ctx: Context, minutes: int = None):
        """:param minutes: Minutes a monster waits before combat triggers (halved on subsequent rounds)."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Spawn duration is {int(game.spawn_duration / 60)} minutes.")
            return
        if minutes <= 1:
            Dispatcher.add(game.channel, "Spawn duration must be more than 1 minute.")
            return
        game.spawn_duration = minutes * 60
        game.save()
        Dispatcher.add(game.channel, "Spawn duration has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_monster.command(name="loot", brief="Minutes that loot remains on the ground.")
    async def config_monster_loot(self, ctx: Context, minutes: int = None):
        """:param minutes: Minutes loot stays before sweep."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Loot duration is {int(game.loot_duration / 60)} minutes.")
            return
        if minutes <= 1:
            Dispatcher.add(game.channel, "Loot duration must be more than 1 minute.")
            return
        game.loot_duration = minutes * 60
        game.save()
        Dispatcher.add(game.channel, "Loot duration has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_monster.command(name="set", brief="Enable / disable monster spawning.")
    async def config_monster_set(self, ctx: Context, msg: str = None):
        """:param msg: ``on`` / ``off`` (also accepts 1/0/true/false/enabled/disabled)."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if msg is None:
            Dispatcher.add(game.channel, f"Monster spawning is currently {'en' if game.use_spawn_timer else 'dis'}abled.")
            return
        msg = msg.lower()
        if msg in ("1", "on", "true", "enabled"):
            if not game.use_spawn_timer:
                game.use_spawn_timer = True
                await game.set_spawn_timer()
            else:
                Dispatcher.add(game.channel, "Monster spawning is already enabled.")
                return
        elif msg in ("0", "off", "false", "disabled"):
            if game.use_spawn_timer:
                game.use_spawn_timer = False
                game.game_clock.remove_routine(game.do_spawn)
            else:
                Dispatcher.add(game.channel, "Monster spawning is already disabled.")
                return
        else:
            return
        game.save()
        Dispatcher.add(game.channel, "Monster spawning has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config.group(name="passerby", brief="Passerby spawn-timing tunables.", invoke_without_command=True, case_insensitive=True)
    async def config_passerby(self, ctx: Context):
        """Subcommand group for passerby timing tunables.
        ``min`` / ``max`` / ``duration`` / ``set``."""
        if ctx.invoked_subcommand is None:
            game = self.bot.games.get(ctx.channel.id)
            if not game:
                return
            Dispatcher.add(
                game.channel,
                f"Passerby: spawn `{' - '.join(map(str, game.passerby_spawn_range))}` "
                f"seconds | stay `{int(game.passerby_depart_after / 60)}` min | "
                f"{'enabled' if game.use_passerby_timer else 'disabled'}",
            )

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_passerby.command(name="min", aliases=["minimum"], brief="Min minutes between passerby spawns.")
    async def config_passerby_min(self, ctx: Context, minutes: int = None):
        """:param minutes: Minimum minutes between passerby spawn attempts."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Minimum passerby spawn time is {game.passerby_spawn_range[0] / 60} minutes.")
            return
        if minutes < 1:
            Dispatcher.add(game.channel, "Minimum passerby spawn time must be at least 1 minute.")
            return
        if minutes >= game.passerby_spawn_range[1] / 60:
            Dispatcher.add(
                game.channel,
                f"Minimum passerby spawn time must be less than the maximum of {game.passerby_spawn_range[1] / 60} minutes.",
            )
            return
        game.passerby_spawn_range = (minutes * 60, game.passerby_spawn_range[1])
        game.save()
        Dispatcher.add(game.channel, "Minimum passerby spawn time has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_passerby.command(name="max", aliases=["maximum"], brief="Max minutes between passerby spawns.")
    async def config_passerby_max(self, ctx: Context, minutes: int = None):
        """:param minutes: Maximum minutes between passerby spawn attempts."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Maximum passerby spawn time is {game.passerby_spawn_range[1] / 60} minutes.")
            return
        if minutes <= game.passerby_spawn_range[0] / 60:
            Dispatcher.add(
                game.channel,
                f"Maximum passerby spawn time must be greater than the minimum of {game.passerby_spawn_range[0] / 60} minutes.",
            )
            return
        game.passerby_spawn_range = (game.passerby_spawn_range[0], minutes * 60)
        game.save()
        Dispatcher.add(game.channel, "Maximum passerby spawn time has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_passerby.command(name="duration", aliases=["dur", "d"], brief="Minutes an arrived passerby lingers before departing.")
    async def config_passerby_duration(self, ctx: Context, minutes: int = None):
        """:param minutes: Real minutes an arrived passerby stays before timer-driven departure."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if minutes is None:
            Dispatcher.add(game.channel, f"Passerby stay duration is {int(game.passerby_depart_after / 60)} minutes.")
            return
        if minutes < 1:
            Dispatcher.add(game.channel, "Passerby stay duration must be at least 1 minute.")
            return
        game.passerby_depart_after = minutes * 60
        game.save()
        Dispatcher.add(game.channel, "Passerby stay duration has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @config_passerby.command(name="set", brief="Enable / disable passerby spawning.")
    async def config_passerby_set(self, ctx: Context, msg: str = None):
        """:param msg: ``on`` / ``off`` (also accepts 1/0/true/false/enabled/disabled)."""
        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        if msg is None:
            Dispatcher.add(game.channel, f"Passerby spawning is currently {'en' if game.use_passerby_timer else 'dis'}abled.")
            return
        msg = msg.lower()
        if msg in ("1", "on", "true", "enabled"):
            if not game.use_passerby_timer:
                game.use_passerby_timer = True
                await game.set_passerby_timer()
            else:
                Dispatcher.add(game.channel, "Passerby spawning is already enabled.")
                return
        elif msg in ("0", "off", "false", "disabled"):
            if game.use_passerby_timer:
                game.use_passerby_timer = False
                game.game_clock.remove_routine(game.do_passerby_spawn)
            else:
                Dispatcher.add(game.channel, "Passerby spawning is already disabled.")
                return
        else:
            return
        game.save()
        Dispatcher.add(game.channel, "Passerby spawning has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Spawns the requested item to the given player's inventory.")
    async def item(self, ctx: Context, item_name: str):
        """
        Spawns the requested item to the given player's inventory.

        :param item_name: The item name.
        """

        game = self.bot.games.get(ctx.channel.id)
        if not game:
            return
        target: Player = None

        if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
            target = await RpgUtilities.get_player(ctx.message.mentions[0], game=game, notify=False)

        if target is None:
            target = await RpgUtilities.get_player(ctx, game=game, notify=False)

        if target is None or item_name is None:
            return

        item = Inventory.load_item(item_name)
        if item:
            target.give_item(item)
            Dispatcher.add(game.channel, f"{item.get_full_name().capitalize()} was given to {target.name}.")
            return

        Dispatcher.add(game.channel, "Unable to spawn item. Please check the spelling of the item name.")

    # Accepted boolean strings for the ambience on/off commands.
    _AMBIENCE_TRUTHY = {"1", "on", "true", "enabled"}
    _AMBIENCE_FALSY = {"0", "off", "false", "disabled"}

    @staticmethod
    def _parse_ambience_bool(value: Optional[str]) -> Optional[bool]:
        """Map a user-supplied value to a bool, or ``None`` if the
        value isn't recognized. Accepts the existing truthy/falsy
        aliases so the split toggles speak the same vocabulary as the
        legacy ``$ambience set`` command."""
        if value is None:
            return None
        v = value.lower()
        if v in RpgAdminCommands._AMBIENCE_TRUTHY:
            return True
        if v in RpgAdminCommands._AMBIENCE_FALSY:
            return False
        return None

    @group(brief="Displays or sets ambience options.", invoke_without_command=True, case_insensitive=True)
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def ambience(self, ctx: Context, value: str = None):
        """
        Displays or toggles ambience settings.

        ``$ambience`` — show every subsystem's current state.
        ``$ambience on/off`` — master kill-switch across all
        subsystems.
        ``$ambience <subsystem> on/off`` — toggle one subsystem
        (``local``, ``celestial``, ``weather``). Master ANDs with
        each subsystem: both must be on for a subsystem to emit.

        (5-second cool-down server-wide)
        """

        # ``invoke_without_command=True`` means this body only runs
        # when no subcommand matched (the parent's ``value`` arg
        # would otherwise greedily consume ``"local"``/``"celestial"``
        # etc. before the subcommand dispatcher got a chance to
        # see them).
        if not await RpgUtilities.check_game_exists(ctx):
            return

        game = self.bot.games.get(ctx.channel.id)
        if game is None:
            return

        if value is not None:
            # Bare on/off sets the master flag — lets ``$ambience
            # on`` stand in for the legacy ``$ambience set on``
            # without requiring the intermediate word.
            parsed = self._parse_ambience_bool(value)
            if parsed is None:
                Dispatcher.add(game.channel, f"I'm afraid I didn't understand that.")
                return
            self._apply_ambience_flag(game, "enable_ambience", parsed, label="Ambience")
            return

        self._dispatch_ambience_status(ctx, game)

    def _dispatch_ambience_status(self, ctx, game) -> None:
        """Render the per-subsystem state embed."""
        guild: Guild = ctx.guild
        embed = Embed(title="Current Ambience Settings")
        if guild.icon is not None:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(
            name="Master",
            value=f"{game.enable_ambience}",
            inline=False,
        )
        for subsystem in game.AMBIENCE_SUBSYSTEMS:
            flag = getattr(game, f"enable_ambience_{subsystem}", True)
            effective = game.ambience_enabled(subsystem)
            value = f"{flag}" if flag == effective else f"{flag} (suppressed by master)"
            embed.add_field(name=subsystem.capitalize(), value=value, inline=True)
        Dispatcher.add(ctx, embed=embed)

    @ambience.command(aliases=["set"], brief="Toggles the master ambience flag.")
    async def ambience_set(self, ctx: Context, value: str = None):
        """Legacy alias for the master toggle. ``$ambience set on/off``
        or simply ``$ambience on/off`` both drive the master flag."""
        game = self.bot.games.get(ctx.channel.id)
        if game is None:
            return
        if value is None:
            Dispatcher.add(
                game.channel,
                f"Ambience is currently {'en' if game.enable_ambience else 'dis'}abled.",
            )
            return
        parsed = self._parse_ambience_bool(value)
        if parsed is None:
            Dispatcher.add(game.channel, f"I'm afraid I didn't understand that.")
            return
        self._apply_ambience_flag(game, "enable_ambience", parsed, label="Ambience")

    @ambience.command(brief="Toggles the local (random flavor) ambience subsystem.")
    async def local(self, ctx: Context, value: str = None):
        """Toggle the ``local`` subsystem — random wildlife / breeze /
        distant-sounds flavor lines. Gated behind the master flag."""
        await self._handle_subsystem_toggle(ctx, "local", value)

    @ambience.command(brief="Toggles the celestial (sunrise/sunset) ambience subsystem.")
    async def celestial(self, ctx: Context, value: str = None):
        """Toggle the ``celestial`` subsystem — sunrise and sunset
        narration. Gated behind the master flag."""
        await self._handle_subsystem_toggle(ctx, "celestial", value)

    @ambience.command(brief="Toggles the weather ambience subsystem.")
    async def weather(self, ctx: Context, value: str = None):
        """Toggle the ``weather`` subsystem — weather-pattern
        narration. Gated behind the master flag."""
        await self._handle_subsystem_toggle(ctx, "weather", value)

    async def _handle_subsystem_toggle(
        self, ctx: Context, subsystem: str, value: Optional[str],
    ) -> None:
        """Shared body for the three per-subsystem toggle commands.
        With no ``value``, reports the current state; otherwise parses
        on/off and applies it via :meth:`_apply_ambience_flag`."""
        game = self.bot.games.get(ctx.channel.id)
        if game is None:
            return
        attr = f"enable_ambience_{subsystem}"
        if value is None:
            Dispatcher.add(
                game.channel,
                f"{subsystem.capitalize()} ambience is currently "
                f"{'en' if getattr(game, attr) else 'dis'}abled.",
            )
            return
        parsed = self._parse_ambience_bool(value)
        if parsed is None:
            Dispatcher.add(game.channel, f"I'm afraid I didn't understand that.")
            return
        self._apply_ambience_flag(game, attr, parsed, label=f"{subsystem.capitalize()} ambience")

    @staticmethod
    def _apply_ambience_flag(game, attr: str, new_value: bool, *, label: str) -> None:
        """Set ``attr`` on ``game`` if it changed, resync the daemons,
        persist, and announce. No-op (with an already-enabled message)
        when the flag is already in the requested state. Covers both
        the master and subsystem flags so the state-change message
        stays consistent."""
        current = getattr(game, attr)
        if current == new_value:
            Dispatcher.add(
                game.channel,
                f"{label} is already {'en' if current else 'dis'}abled.",
            )
            return
        setattr(game, attr, new_value)
        game.sync_ambience_daemons()
        game.save()
        Dispatcher.add(game.channel, f"{label} has been {'en' if new_value else 'dis'}abled.")

    @is_owner()
    @command(name="inspect_monster", aliases=["im"], brief="DM a recursive dump of the current monster. Owner only.")
    async def inspect_monster(self, ctx: Context, *flags: str):
        """
        DMs the invoking owner a pretty-printed recursive dump of the currently
        spawned monster. Intended for debugging only; output goes to DM to avoid
        leaking internals into player channels.

        Flags (order-independent, positional):
            compact     Omit noisy static plugin data (debuff tables, flavor text).
            inline      Send as inline code-fence messages instead of a .py attachment (the default).
            stats       Include only top-level creature attributes (no body_parts / attack_sources).
            parts       Include only body_parts.
            attacks     Include only attack_sources.

        Section flags are exclusive — passing more than one falls back to the full dump.
        """
        game = self.bot.games.get(ctx.channel.id) if ctx.guild else None
        if not game or game.monster is None:
            Dispatcher.add(ctx, "There is no monster present to inspect.")
            return

        flagset = {f.lower() for f in flags}
        compact = "compact" in flagset
        as_file = "inline" not in flagset
        sections = flagset & {"stats", "parts", "attacks"}

        skip = _COMPACT_SKIP_KEYS if compact else set()
        monster = game.monster

        # Build the dump dict based on section flags. A single section flag
        # returns just that slice; zero or multiple section flags return the
        # full dump.
        if len(sections) == 1:
            section = next(iter(sections))
            if section == "stats":
                # Top-level scalars only — strip body_parts and any
                # monster-specific list/dict containers to keep the view flat.
                state = _to_plain(monster, skip_keys=skip)
                if isinstance(state, dict):
                    state = {
                        k: v for k, v in state.items()
                        if k == "__class__" or not isinstance(v, (list, dict, set))
                    }
                dump: Any = {"class": type(monster).__name__, "stats": state}
            elif section == "parts":
                dump = {
                    "class": type(monster).__name__,
                    "body_parts": _to_plain(monster.body_parts, skip_keys=skip),
                }
            else:  # attacks
                try:
                    sources = [_to_plain(s, skip_keys=skip) for s in monster.get_attack_sources()]
                except Exception as e:
                    sources = f"<get_attack_sources failed: {e!r}>"
                dump = {
                    "class": type(monster).__name__,
                    "attack_sources": sources,
                }
        else:
            try:
                sources = [_to_plain(s, skip_keys=skip) for s in monster.get_attack_sources()]
            except Exception as e:
                sources = f"<get_attack_sources failed: {e!r}>"
            dump = {
                "class": type(monster).__name__,
                "state": _to_plain(monster, skip_keys=skip),
                "attack_sources": sources,
            }

        text = pprint.pformat(dump, width=100, sort_dicts=False)

        try:
            if as_file:
                # `.py` extension so Discord's inline preview applies Python
                # syntax highlighting — closest thing to a Slack-style snippet.
                filename = f"{type(monster).__name__.lower()}_dump.py"
                buf = io.BytesIO(text.encode("utf-8"))
                await ctx.author.send(file=DiscordFile(buf, filename=filename))
            else:
                chunks = Dispatcher.split_message(text, sep="\n", limit=1900)
                for chunk in chunks:
                    await ctx.author.send(f"```python\n{chunk}\n```")
            suffix = " (compact)" if compact else ""
            Dispatcher.add(ctx, f"Sent {type(monster).__name__} dump{suffix} to your DMs.")
        except Exception as e:
            _log.error(f"inspect_monster DM failed: {e}")
            Dispatcher.add(ctx, "Unable to DM you — check that DMs from server members are enabled.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @command(name="reload_plugins", aliases=["rp"], brief="Reloads monster and item plugins.")
    async def reload_plugins(self, ctx: Context, target: str = None):
        """
        Reloads monster, passerby, static-object, and/or item plugins from disk.

        :param target: 'monsters', 'passersby', 'objects', 'items', or omit for all.
        """
        from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
        from caldanai.lib.rpg.world.objects import StaticObjectPlugin

        reloaded = []
        if target is None or target.lower() == "monsters":
            MonsterPlugin.load_plugins()
            reloaded.append("monsters")
        if target is None or target.lower() in ("passersby", "passerbys"):
            PasserbyPlugin.load_plugins()
            reloaded.append("passersby")
        if target is None or target.lower() in ("objects", "static_objects", "static-objects"):
            StaticObjectPlugin.load_plugins()
            reloaded.append("objects")
        if target is None or target.lower() == "items":
            Inventory.ITEMS.clear()
            Inventory.discover_items()
            reloaded.append("items")

        if reloaded:
            Dispatcher.add(ctx, f"Reloaded: {', '.join(reloaded)}.")
        else:
            Dispatcher.add(ctx, f"Unknown target '{target}'. Use 'monsters', 'passersby', 'objects', 'items', or omit for all.")

    # Additional maintenance after cog loads.
    @Cog.listener()
    async def on_ready(self):
        if not RpgUtilities.is_initialized:
            _log.debug("Initializing RpgUtilities")
            await RpgUtilities.init(self.bot)
        _log.info("RpgAdminCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgAdminCommands(bot))
