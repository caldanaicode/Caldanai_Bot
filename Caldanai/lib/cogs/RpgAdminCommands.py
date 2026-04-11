from typing import Optional

from discord import Embed, Guild
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

from Caldanai.db import DB
from Caldanai.Dispatcher import Dispatcher
from Caldanai.lib.bot import Bot
from Caldanai.lib.rpg import Roles, parse
from Caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.utils import RpgUtilities
from Caldanai.lib.rpg.inventory import Inventory
from Caldanai.Logger import get_logger


_log = get_logger(__name__)


class RpgAdminCommands(Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot

    @group(aliases=["rpg"], brief="Groups the various Game commands.")
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
            if DB.get_game_by_guild_id(ctx.guild.id) is not None:
                Dispatcher.add(ctx, "Only a single game per server is supported.")

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

        await RpgUtilities.remove_game(ctx.guild.id)
        Dispatcher.add(ctx, "The game has been removed.")

    @group(brief="Role settings for the game.")
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
                    target = await RpgUtilities.get_player(mention)
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
                    target = await RpgUtilities.get_player(mention)
                    if target and target.health < target.get_health_max():
                        target.apply_damage(-target.get_health_max())
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

    @group(brief="Displays or sets various spawning options.")
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def spawn(self, ctx: Context):
        """
        Used alone, displays the various spawning options and information. See the subcommands for settings those options.

        (5-second cool-down server-wide)
        """

        if not await RpgUtilities.check_game_exists(ctx):
            return

        if ctx.invoked_subcommand is None:
            guild: Guild = ctx.guild
            game = self.bot.games.get(ctx.guild.id)
            r, i = game.game_clock.find_routine("do_spawn")
            routine = r[i] if r else None

            embed = Embed(title="Current Spawn Settings")
            embed.set_thumbnail(url=guild.icon.url)
            embed.add_field(
                name="Spawn Timing",
                value=f"{' - '.join(map(str, game.spawn_timer_range))} seconds",
                inline=True,
            )
            embed.add_field(name="Spawn Duration", value=f"{int(game.spawn_duration / 60)} minutes", inline=True)
            embed.add_field(name="Loot Duration", value=f"{int(game.loot_duration / 60)} minutes", inline=True)
            embed.add_field(name="Spawning Enabled", value=str(game.use_spawn_timer), inline=True)

            if routine:
                next_spawn = routine.time_added - game.game_clock.get_tick_time() + routine.seconds
                embed.add_field(name="Next Spawn", value=f"{int(next_spawn / 60)} minutes")

            Dispatcher.add(ctx, embed=embed)

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(
        aliases=["min"], brief="Sets or displays the minimum time between monster spawns for a game, in minutes"
    )
    async def minimum(self, ctx: Context, minutes: int = None):
        """
        Sets or displays the minimum time between monster spawns for a game, in minutes

        :param minutes: The minimum number of minutes before another monster can spawn after the previous monster is removed.
        """

        game = self.bot.games.get(ctx.guild.id)
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
    @spawn.command(
        aliases=["max"], brief="Sets or displays the maximum time between monster spawns for a game, in minutes."
    )
    async def maximum(self, ctx: Context, minutes: int = None):
        """
        Sets or displays the maximum time between monster spawns for a game, in minutes.

        :param minutes: The maximum number of minutes before another monster can be spawned after the previous is removed.
        """

        game = self.bot.games.get(ctx.guild.id)
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
    @spawn.command(aliases=["dur", "d"], brief="Sets or displays the spawn duration for a game, in minutes.")
    async def duration(self, ctx: Context, minutes: int = None):
        """
        Sets or displays the spawn duration for a game, in minutes.

        :param minutes: The number of minutes that a monster will wait for combat on the first round. This time is halved for additional rounds of combat.
        """

        game = self.bot.games.get(ctx.guild.id)
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
    @spawn.command(brief="Sets or displays the loot duration for a game, in minutes.")
    async def loot(self, ctx: Context, minutes: int = None):
        """
        Sets or displays the loot duration, in minutes. If a monster has loot after death, the spawn timer does not begin until after the loot timer expires.

        :param minutes: The number of minutes that loot will be available before removal.
        """

        game = self.bot.games.get(ctx.guild.id)
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
    @spawn.command(aliases=["set"], brief="Sets or displays the spawning for a game on or off.")
    async def spawn_set(self, ctx: Context, msg: str = None):
        """
        Sets or displays the spawning for a game on or off.

        :param msg: To enable spawning use 1, on, true, or enabled. To disable, use 0, off, false, or disabled.
        """

        game = self.bot.games.get(ctx.guild.id)
        if not game:
            return
        if msg is None:
            Dispatcher.add(game.channel, f"Spawning is currently {'en' if game.use_spawn_timer else 'dis'}abled.")
            return

        msg = msg.lower()
        if any(v == msg for v in ["1", "on", "true", "enabled"]):
            if not game.use_spawn_timer:
                game.use_spawn_timer = True
                await game.set_spawn_timer()
            else:
                Dispatcher.add(game.channel, "Spawning is already enabled.")
                return

        elif any(v == msg for v in ["0", "off", "false", "disabled"]):
            if game.use_spawn_timer:
                game.use_spawn_timer = False
                game.game_clock.remove_routine(game.do_spawn)
            else:
                Dispatcher.add(game.channel, "Spawning is already disabled.")
                return

        else:
            return

        game.save()
        Dispatcher.add(game.channel, "Spawning has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Forces a monster to spawn.")
    async def monster(self, ctx: Context, monster: Optional[str] = None):
        """
        Forces a monster to spawn.

        :param monster: the filename of the monster to spawn. If not provided, randomly chooses an available monster.
        """

        game = self.bot.games.get(ctx.guild.id)
        if not game:
            return
        if game.monster is None:
            game.game_clock.remove_routine(game.do_spawn)
            await game.do_spawn(monster)
            return

        Dispatcher.add(game.channel, f"There is already a {game.monster.name} present!")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Forces the current monster to die.")
    async def kill(self, ctx: Context):
        """
        Forces the current monster to die.
        """

        game = self.bot.games.get(ctx.guild.id)
        if not game:
            return
        if game.monster is None:
            Dispatcher.add(game.channel, "There is no monster present!")
            return

        await game.kill_monster()

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @spawn.command(brief="Spawns the requested item to the given player's inventory.")
    async def item(self, ctx: Context, item_name: str):
        """
        Spawns the requested item to the given player's inventory.

        :param item_name: The item name.
        """

        game = self.bot.games.get(ctx.guild.id)
        if not game:
            return
        target: Player = None

        if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
            target = await RpgUtilities.get_player(ctx.message.mentions[0])

        if target is None:
            target = await RpgUtilities.get_player(ctx)

        if target is None or item_name is None:
            return

        item = Inventory.load_item(item_name)
        if item:
            target.give_item(item)
            Dispatcher.add(game.channel, f"{item.get_full_name().capitalize()} was given to {target.name}.")
            return

        Dispatcher.add(game.channel, "Unable to spawn item. Please check the spelling of the item name.")

    @group(brief="Displays or sets various ambience options.")
    @guild_only()
    @check_any(is_owner(), has_permissions(manage_guild=True))
    @cooldown(1, 5, BucketType.guild)
    async def ambience(self, ctx: Context):
        """
        Displays or sets various ambience options.
        (5-second cool-down server-wide)
        """

        if not await RpgUtilities.check_game_exists(ctx):
            return

        if ctx.invoked_subcommand is None:
            guild: Guild = ctx.guild
            game = self.bot.games.get(ctx.guild.id)
            embed = Embed(title="Current Ambience Settings")
            embed.set_thumbnail(url=guild.icon.url)
            embed.add_field(name="Ambience Enabled", value=f"{game.enable_ambience}", inline=True)
            Dispatcher.add(ctx, embed=embed)

    @ambience.command(aliases=["set"], brief="Sets ambience for a game on or off.")
    async def ambience_set(self, ctx: Context, value: str = None):
        """
        Sets ambience for a game on or off. If no setting is supplied, displays the current setting.

        :param value: To enable ambience use 1, on, true, or enabled. To disable, use 0, off, false, or disabled.
        """

        game = self.bot.games.get(ctx.guild.id)
        if not game:
            return
        if value is None:
            Dispatcher.add(game.channel, f"Ambience is currently {'en' if game.enable_ambience else 'dis'}abled.")
            return

        value = value.lower()
        if value.lower() in ["1", "on", "true", "enabled"]:
            if not game.enable_ambience:
                game.enable_ambience = True
                game.game_clock.add_routine(game.do_ambience, 1)
            else:
                Dispatcher.add(game.channel, "Ambience is already enabled.")
                return

        elif value.lower() in ["0", "off", "false", "disabled"]:
            if game.enable_ambience:
                game.enable_ambience = False
                game.game_clock.remove_routine(game.do_ambience)
            else:
                Dispatcher.add(game.channel, "Ambience is already disabled.")
                return

        else:
            Dispatcher.add(game.channel, f"I'm afraid I didn't understand that.")
            return

        game.save()
        Dispatcher.add(game.channel, "Ambience has been set.")

    @check_any(is_owner(), has_permissions(manage_guild=True))
    @command(name="reload_plugins", aliases=["rp"], brief="Reloads monster and item plugins.")
    async def reload_plugins(self, ctx: Context, target: str = None):
        """
        Reloads monster and/or item plugins from disk.

        :param target: 'monsters', 'items', or omit for both.
        """
        reloaded = []
        if target is None or target.lower() == "monsters":
            MonsterPlugin.load_plugins()
            reloaded.append("monsters")
        if target is None or target.lower() == "items":
            Inventory.ITEMS.clear()
            Inventory.discover_items()
            reloaded.append("items")

        if reloaded:
            Dispatcher.add(ctx, f"Reloaded: {', '.join(reloaded)}.")
        else:
            Dispatcher.add(ctx, f"Unknown target '{target}'. Use 'monsters', 'items', or omit for both.")

    # Additional maintenance after cog loads.
    @Cog.listener()
    async def on_ready(self):
        if not RpgUtilities.is_initialized:
            _log.debug("Initializing RpgUtilities")
            await RpgUtilities.init(self.bot)
        _log.info("RpgAdminCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgAdminCommands(bot))
