from discord.ext.commands import (
    Cog, command, cooldown, BucketType, guild_only, Context,
    check_any, group, has_permissions, is_owner,
)
from discord import Embed
from typing import Optional

import pandas
import matplotlib.pyplot as plt

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.db import DB
from caldanai.lib.rpg import Game
from caldanai.lib.rpg.helpers.enums import (
    Directions, INJURY_LEVEL_DISPLAY, InjuryLevels, Pronouns, Roles,
)
from caldanai.lib.rpg.helpers.plotting import (
    CYAN_ACCENT, fig_to_file, style_axes_dark,
)
from caldanai.lib.rpg.helpers.utils import RpgUtilities

_log = get_logger(__name__)


# Standard body-HP tier dot. Separate from per-part injury dots because
# body HP is a single value whereas parts have injury-level enums.
def _body_hp_dot(player) -> str:
    """Return a status dot reflecting the player's body HP fraction."""
    ratio = player.get_health_scale()
    if ratio >= 1.0:
        return "🟢"
    if ratio >= 0.75:
        return "🟡"
    if ratio >= 0.4:
        return "🟠"
    if ratio > 0:
        return "🔴"
    return "⚫"


_ANSI_RESET = "\x1b[0m"


def _ansi_wrap(text: str, color_code: str) -> str:
    """Wrap ``text`` in an ANSI color escape for a ```ansi fence.
    Uses the dim/normal intensity (``2;``) to match Discord's other
    colored-diff aesthetics."""
    return f"\x1b[2;{color_code}m{text}{_ANSI_RESET}"


def _injured_parts_suffix(player) -> str:
    """Returns a short comma-separated list of the player's non-NONE
    parts with their status word (ANSI-colored), for use as a one-line
    suffix in ``$health hurt`` / ``$health injured``. Empty string if
    nothing."""
    chunks = []
    for part in getattr(player, "body_parts", []) or []:
        level = part.get_injury_level()
        if level == InjuryLevels.NONE:
            continue
        _, word, color = INJURY_LEVEL_DISPLAY.get(level, ("", str(level), "37"))
        chunks.append(f"{part.name} {_ansi_wrap(word, color)}")
    return ", ".join(chunks)


def _render_health_table(player) -> str:
    """Render the calling player's full health report: body HP + regen
    summary line, followed by the shared per-part status table (see
    ``Creature.render_body_part_status_table``).

    Regen is reported as "next tick +N HP" rather than a rate because
    the value is an accumulating charge, not a stable per-hour rate —
    it ramps each tick until everything is fully healed and then
    resets to 0. Showing "next tick" keeps the displayed number
    honest about what it represents (the amount the *next* healing
    event will restore)."""
    body_dot = _body_hp_dot(player)
    if player.health_regen > 0:
        regen_str = f", next tick +{player.health_regen} HP"
    else:
        regen_str = ""
    header = (
        f"{body_dot} **{player.name}** — {player.health} / "
        f"{player.get_health_max()} health{regen_str}"
    )
    table = player.render_body_part_status_table()
    if not table:
        return header
    return f"{header}\n{table}"


class RpgInfoCommands(Cog):
    def __init__(self, bot):
        self.bot = bot

    @command(brief="Lists the current players in a game.")
    @cooldown(1, 10, BucketType.guild)
    async def players(self, ctx: Context, gid: int = None):
        """
        Lists the current players in the game.

        (10-second server-wide cool-down)

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game: Game = await RpgUtilities.get_game(ctx, gid)
        if game is None:
            return

        length = len(game.player_manager.players)
        s = list(game.player_manager.players.values())
        s.sort(key=lambda p: p.member.display_name)
        msg = "```\n"
        for idx, player in enumerate(s):
            msg += f"{idx}: {player.member.display_name}\n"

        embed = Embed(
            title=f"There {'is' if length == 1 else 'are'} currently {length:,} player{'' if length == 1 else 's'}.",
            description=msg.strip() + "```" if len(msg) > 4 else None,
        )
        embed.set_thumbnail(url=game.guild.icon.url)
        Dispatcher.add(game.channel, embed=embed)

    @command(brief="Shows a player's profile.")
    @cooldown(1, 10, BucketType.member)
    async def profile(self, ctx: Context, gid: int = None):
        """
        Shows a player's profile.

        (10-second cool-down)

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        embed = player.get_profile(game.guild.name)
        embed.set_thumbnail(url=game.guild.icon.url)
        Dispatcher.add(channel, embed=embed)

    @command(brief="Shows a player's skills.")
    @cooldown(1, 10, BucketType.member)
    async def skills(self, ctx: Context, gid: int = None):
        """
        Shows a player's skills.

        (10-second cool-down)

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)
        embed = player.get_skill_display()
        embed.set_thumbnail(url=game.guild.icon.url)
        Dispatcher.add(channel, embed=embed)

    @guild_only()
    @cooldown(1, 5, BucketType.guild)
    @command(aliases=["stimer"], brief="Shows the amount of time until the next monster spawn.")
    async def spawn_timer(self, ctx: Context):
        """Shows the amount of time until the next monster spawn."""
        game: Game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        r, i = game.game_clock.find_routine(game.do_spawn.__qualname__)
        routine = r[i] if r else None

        if routine:
            next_spawn = routine.time_added - game.game_clock.get_tick_time() + routine.seconds
            Dispatcher.add(ctx, f"Next spawn in approximately {int(next_spawn / 60)} minutes.")
        else:
            Dispatcher.add(ctx, "Next spawn is not yet determined... try again later!")

    @guild_only()
    @cooldown(1, 5, BucketType.member)
    @command(brief="Generates a chart using the specified options")
    async def chart(self, ctx: Context, *options: str):
        """
        Generates a chart using the specified options.

        :param options: Options for the display of the chart and data.
            [d4, d6, d8, d10, d12, d20] The dice rolls for which to show data. Default is d20.
            [bar, barh, area, line] The type of chart to show. Default is bar.
            [wN, hN] The size of the chart in inches. Default is auto-sized for "all" charts, and w8 h4 for individual charts.
            [all] Compiles data for all players.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        data_types = ("d4", "d6", "d8", "d10", "d12", "d20")
        plot_types = {
            # 'hexbin': {'x': 'index', 'y': ''},
            "bar": {"options": {"stacked": True}, "labels": ("Rolls", "Count")},
            # 'pie': {'options': {'y': 'Roll Counts', 'subplots': True}},
            "barh": {"options": {"stacked": True}, "labels": ("Count", "Rolls")},
            # 'scatter': {},
            "hist": {"options": {}, "labels": ("Rolls by Count", "Count Total")},
            # 'density': {},
            "area": {"options": {}, "labels": ("Rolls", "Count")},
            "line": {"options": {}, "labels": ("Rolls", "Count")},
        }

        rolls = 0
        total = 0
        kind = "bar"
        tcolor = CYAN_ACCENT
        dtype = "d20"
        dsize = 20
        width = 8
        height = 4
        autosize = True

        for option in options:
            opt = option.lower()
            if opt in plot_types.keys():
                kind = opt
            elif opt in data_types:
                dtype = opt
                dsize = int(opt.split("d")[1])
            elif opt[0] == "w" and opt[1:].isnumeric() and (w := int(opt[1:])) >= 1:
                width = w
                autosize = False
            elif opt[0] == "h" and opt[1:].isnumeric() and (h := int(opt[1:])) >= 1:
                height = h
                autosize = False

        if "all" in options:
            data = {p.name: p.rolls[dtype] for p in game.player_manager.players.values() if any(p.rolls[dtype])}
            if len(data) == 0:
                data = {"None": (0,) * dsize}
            df = pandas.DataFrame(data, index=range(1, dsize + 1), dtype="int")
            for d in data.values():
                for idx, count in enumerate(d):
                    rolls += count
                    total += (idx + 1) * count

            mean = total / rolls if rolls > 0 else 0
            if autosize:
                ax = df.plot(kind=f"{kind}", fontsize=14, **plot_types[kind]["options"])
            else:
                ax = df.plot(kind=f"{kind}", fontsize=14, figsize=(width, height), **plot_types[kind]["options"])

            ax.legend(
                bbox_to_anchor=(1, 1),
                loc="upper left",
                facecolor="black",
                framealpha=0.3,
                edgecolor=tcolor,
                labelcolor=tcolor,
            )

        else:
            data = player.rolls[dtype]
            df = pandas.DataFrame(data, index=range(1, dsize + 1), dtype="int")
            for idx, count in enumerate(data):
                i = idx + 1
                rolls += count
                total += i * count
                df.rename(index={i: f"{i} [ {count:,} ]"}, inplace=True)

            mean = total / rolls if rolls > 0 else 0
            if autosize:
                ax = df.plot(kind=f"{kind}", legend=False, figsize=(8, 4), fontsize=16, **plot_types[kind]["options"])
            else:
                ax = df.plot(
                    kind=f"{kind}", legend=False, figsize=(width, height), fontsize=16, **plot_types[kind]["options"]
                )

        try:
            ax.set_xlabel(plot_types[kind]["labels"][0])
            ax.set_ylabel(plot_types[kind]["labels"][1])
            ax.set_ybound(lower=0)
            style_axes_dark(ax, accent_color=tcolor, grid_axis="y")
        except:
            pass

        file = fig_to_file(ax.figure, filename="plot.png")
        Dispatcher.add(ctx, file=file)
        Dispatcher.add(ctx, f"Count: {rolls:,}, Mean: {mean:.2f}")

    @cooldown(1, 10, BucketType.member)
    @guild_only()
    @command(name="usage", aliases=["commands"], brief="Shows a chart of most-used commands.")
    async def usage(self, ctx: Context, scope: str = None, arg: str = None):
        """
        Shows a horizontal bar chart of the most frequently used
        commands. Defaults to your personal usage in this game.

        (10-second cool-down)

        :param scope: ``game`` for this game, ``guild`` for server-wide, ``bot`` for bot-wide (admin only), ``command <name>`` for alias breakdown, or a number to limit results. Negative numbers show the least-used (e.g. ``-5``).
        :param arg: A limit when scope is a keyword (``$usage game 10``), or a command/alias name for ``$usage command kill``.
        """
        scope_str = (scope or "").lower()
        limit = None
        ascending = False

        if scope_str.lstrip("-").isnumeric() and scope_str:
            n = int(scope_str)
            ascending = n < 0
            limit = abs(n)
            scope_str = ""

        if arg and arg.lstrip("-").isnumeric():
            n = int(arg)
            ascending = n < 0
            limit = abs(n)
            arg = None

        if scope_str == "command":
            if not arg:
                Dispatcher.add(ctx, "Specify a command name: `$usage command kill`")
                return
            cmd = ctx.bot.get_command(arg.lower())
            canonical = cmd.qualified_name.lower() if cmd else arg.lower()
            data = DB.get_alias_breakdown(
                canonical, channel_id=ctx.channel.id,
                limit=limit, ascending=ascending,
            )
            title = f"Alias Breakdown: ${canonical}"
        elif scope_str == "bot":
            if not (ctx.author.id in getattr(ctx.bot, "owner_ids", set())
                    or await ctx.bot.is_owner(ctx.author)):
                Dispatcher.add(ctx, "Bot-wide usage is admin-only.")
                return
            data = DB.get_command_usage(limit=limit, ascending=ascending)
            title = "Bot-Wide Command Usage"
        elif scope_str == "guild":
            data = DB.get_command_usage(
                guild_id=ctx.guild.id, limit=limit, ascending=ascending,
            )
            title = f"{ctx.guild.name} Command Usage"
        elif scope_str == "game":
            data = DB.get_command_usage(
                channel_id=ctx.channel.id, limit=limit, ascending=ascending,
            )
            title = "Game Command Usage"
        else:
            data = DB.get_command_usage(
                channel_id=ctx.channel.id, user_id=ctx.author.id,
                limit=limit, ascending=ascending,
            )
            title = f"{ctx.author.display_name}'s Command Usage"

        if not data:
            Dispatcher.add(ctx, "No command usage recorded yet.")
            return

        labels = [row["_id"] for row in reversed(data)]
        counts = [row["count"] for row in reversed(data)]

        tcolor = "#DDDDDD"
        fig, ax = plt.subplots(figsize=(8, max(3, len(labels) * 0.4)))
        ax.barh(labels, counts, color="#5865F2")
        ax.set_xlabel("Uses")
        ax.set_title(title, color=tcolor, fontsize=14)
        style_axes_dark(ax, accent_color=tcolor, grid_axis="x")

        total = sum(row["count"] for row in data)
        file = fig_to_file(fig, filename="usage.png")
        Dispatcher.add(ctx, file=file)
        Dispatcher.add(ctx, f"Total tracked: {total:,}")

    # Returns a string to display games in which a user is currently playing.
    @cooldown(1, 60, BucketType.user)
    @command(name="games", brief="Sends a DM to the calling player with a list of games in which they are a member.")
    async def games_display(self, ctx: Context):
        """
        Sends a DM to the calling player with a list of games in which they are a member.

        (60-second cool-down)
        """

        msg = ""
        games = RpgUtilities.get_games_for_user(ctx.author.id)
        for idx, game in enumerate(games):
            msg += f"{idx}: {game.guild.name}\n"

        Dispatcher.add(
            RpgUtilities.dm_target(ctx.author, ctx.channel),
            f"```js\n{msg}```" if len(msg) > 0 else "You are not playing any games.",
        )
        if ctx.guild is not None and not RpgUtilities.is_bot_player(ctx.author):
            await ctx.message.delete()

    @cooldown(1, 5, BucketType.member)
    @command(name="gender", brief="Displays or sets the user's gender.")
    async def gender(self, ctx: Context, gender: Optional[str] = None, gid: Optional[int] = None):
        """
        Displays or sets the user's gender.

        (5-second cool-down)

        :param gender: Can be anything you like, but if the gender is not 'male', 'female', or 'non-binary', the pronouns will not be auto-updated by the game.

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if gender:
            player.gender = gender.lower()
            player.update_pronouns()
            player.is_dirty = True
            Dispatcher.add(
                channel,
                f"{player.name}'s gender has been set to '{player.gender}'. "
                f"You may also wish to set your `{ctx.prefix}pronouns`",
            )
        else:
            Dispatcher.add(channel, f"{player.name}'s gender is currently shown as '{player.gender}'.")

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="pronouns", brief="Displays or sets the user's pronouns.")
    async def pronouns(self, ctx: Context, s: str = None, o: str = None, p: str = None, a: str = None):
        """
        Displays or sets the user's pronouns using subject/object/possessive/adjective form.

        (5-second cool-down)

        :param s: The subjective form, such as 'he', 'she', or 'they'. Example usage: 'He hid from the monster.'

        :param o: The objective form, such as 'him', 'her', or 'them'. Example usage: 'The monster bites her playfully.'

        :param p: The possessive form, such as 'his', 'hers', or 'theirs'. Example usage: 'That sword is theirs.'

        :param a: The adjective form, such as 'his', 'her', or 'their'. Example usage: 'Her health has been restored.'
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if not s or not o or not p or not a:
            Dispatcher.add(
                game.channel, f"{player.name}'s pronouns are currently shown as '{'/'.join(player.pronouns.values())}'."
            )
            return

        player.pronouns[Pronouns.SUBJECTIVE] = s
        player.pronouns[Pronouns.OBJECTIVE] = o
        player.pronouns[Pronouns.POSSESSIVE] = p
        player.pronouns[Pronouns.ADJECTIVE] = a
        player.pronouns[Pronouns.REFLEXIVE] = f"{o}self"
        player.is_dirty = True
        Dispatcher.add(
            game.channel,
            f"{player.name}'s pronouns have been set to '"
            f"{'/'.join(player.pronouns.values())}'. You may also wish to set your `"
            f"{ctx.prefix}gender`",
        )

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="health", brief="Displays player health and regeneration.")
    async def health(self, ctx: Context, flag: str = None):
        """
        Displays player health and regeneration.

        (5-second cool-down)

        :param flag: 'all', 'hurt', or 'injured'. If nothing is specified, shows only the calling player's health, regeneration, and per-part injury table. 'all' shows body HP for all players. 'hurt' or 'injured' adds an injured-parts suffix for each listed player.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        channel = RpgUtilities.resolve_reply_channel(ctx, game)

        if flag and flag.lower() in ("active", "all", "hurt", "injured"):
            flag_norm = flag.lower()
            players = sorted(
                sorted(
                    [
                        i
                        for i in game.player_manager.players.values()
                        if (
                            flag_norm == "all"
                            or (flag_norm in ("hurt", "injured") and i.is_injured())
                            or (flag_norm == "active" and game.player_manager.roles[Roles.ACTIVE] in i.member.roles)
                        )
                    ],
                    key=lambda x: x.name.lower(),
                ),
                key=lambda x: x.get_health_scale(),
            )

            if not players:
                msg = "No players are injured."
            else:
                # Every list view appends the injured-parts suffix when
                # a player has part injuries, regardless of which flag
                # brought them in — a healer / scanner wants the detail
                # anywhere a player with a destroyed arm appears.
                # Fence is ``ansi`` so the colored suffix words render.
                lines = ["```ansi"]
                for p in players:
                    dot = _body_hp_dot(p)
                    line = (
                        f"{dot} {p.name}: {p.health} / {p.get_health_max()}"
                    )
                    suffix = _injured_parts_suffix(p)
                    if suffix:
                        line += f" — {suffix}"
                    lines.append(line)
                lines.append("```")
                msg = "\n".join(lines)

            Dispatcher.add(channel, msg)

        else:
            msg = _render_health_table(player)
            Dispatcher.add(channel, msg)

    @cooldown(1, 10, BucketType.member)
    @guild_only()
    @command(name="time", brief="Displays the game's time.")
    async def time(self, ctx: Context):
        """
        Displays the game's time.

        (10-second cool-down)
        """
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        msg = game.game_clock.get_full_date()

        Dispatcher.add(game.channel, msg)

    @cooldown(1, 10, BucketType.member)
    @guild_only()
    @group(
        name="weather",
        brief="Describes the current weather, or admin subcommands.",
        invoke_without_command=True,
        case_insensitive=True,
    )
    async def weather(self, ctx: Context):
        """
        Describes the current weather for the game.

        (10-second cool-down)
        """
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return
        if game.weather is None:
            Dispatcher.add(game.channel, "The weather is unremarkable.")
            return
        Dispatcher.add(game.channel, game.weather.describe())

    # -- Weather admin subcommands --------------------------------------
    # Colocated with the bare ``$weather`` command so ``$help weather``
    # resolves to a single group with all subcommands listed. Each
    # admin subcommand guards itself with the standard
    # is_owner / manage_guild check — the bare call stays open so any
    # player can check the weather.

    @weather.command(name="status", brief="Show raw weather state + time left.")
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def weather_status(self, ctx: Context):
        """Show the weather daemon's internal state — active components,
        per-component severity, and remaining game-minutes (with a
        real-time conversion) until the next transition roll."""
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.weather is None:
            Dispatcher.add(ctx, "No weather daemon running on this channel.")
            return

        w = game.weather
        if w.is_clear():
            state_lines = ["(clear skies)"]
        else:
            state_lines = [
                f"  {p.name}: {s.name}" for p, s in w.severities.items()
            ]

        # Real-time conversion: game_clock.time_scale is how many
        # game-hours per real hour.
        time_scale = max(1, game.game_clock.time_scale)
        real_minutes = w._duration_remaining / time_scale
        if real_minutes >= 60:
            rh, rm = divmod(int(real_minutes), 60)
            real_str = f"~{rh}h {rm}m real"
        else:
            real_str = f"~{real_minutes:.1f}m real"

        msg = (
            f"```\n"
            f"Weather state:\n"
            f"{chr(10).join(state_lines)}\n"
            f"Duration remaining: {w._duration_remaining} game-minutes ({real_str})\n"
            f"Current description: {w.describe()}\n"
            f"```"
        )
        Dispatcher.add(ctx, msg)

    @weather.command(
        name="force",
        brief="Force a weather pattern and severity.",
        usage="<pattern> [severity]",
    )
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def weather_force(
        self, ctx: Context, pattern: str, severity: str = "MODERATE",
    ):
        """Force a weather component to a specific severity. ``pattern``
        is a ``WeatherPatterns`` name (``CLOUDY``, ``FOG``,
        ``PRECIPITATION``, ``WIND``). Severities: ``LIGHT``,
        ``MODERATE``, ``HEAVY``, ``SEVERE``. Adds the component on top
        of existing state — use ``clear`` first to wipe the slate.

        Does NOT reset the transition timer; use ``roll`` for that.
        """
        from caldanai.lib.rpg.helpers.enums import (
            WeatherPatterns, WeatherSeverities,
        )
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.weather is None:
            Dispatcher.add(ctx, "No weather daemon running on this channel.")
            return

        pattern_name = pattern.upper()
        severity_name = severity.upper()
        if pattern_name not in WeatherPatterns.__members__ or pattern_name == "CLEAR":
            valid = [
                n for n in WeatherPatterns.__members__ if n != "CLEAR"
            ]
            Dispatcher.add(
                ctx,
                f"Unknown pattern `{pattern}`. Valid: {', '.join(valid)}.",
            )
            return
        if severity_name not in WeatherSeverities.__members__:
            Dispatcher.add(
                ctx,
                f"Unknown severity `{severity}`. Valid: "
                f"{', '.join(WeatherSeverities.__members__)}.",
            )
            return

        p = WeatherPatterns[pattern_name]
        s = WeatherSeverities[severity_name]
        game.weather.severities[p] = s
        Dispatcher.add(game.channel, game.weather.describe())

    @weather.command(name="clear", brief="Clear the weather (no active components).")
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def weather_clear(self, ctx: Context):
        """Wipe all active weather components. Leaves duration alone —
        next transition will roll fresh."""
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.weather is None:
            Dispatcher.add(ctx, "No weather daemon running on this channel.")
            return

        game.weather.severities = {}
        Dispatcher.add(game.channel, game.weather.describe())

    @weather.command(name="roll", brief="Immediately roll a new weather state.")
    @check_any(is_owner(), has_permissions(manage_guild=True))
    async def weather_roll(self, ctx: Context):
        """Skip the transition timer and roll a new weather state based
        on the current season."""
        from caldanai.lib.rpg.helpers.enums import Seasons
        game = await RpgUtilities.get_game(ctx)
        if game is None or game.weather is None:
            Dispatcher.add(ctx, "No weather daemon running on this channel.")
            return

        season = Seasons(game.game_clock.get_season())
        game.weather._roll_new_state(season)
        Dispatcher.add(game.channel, game.weather.describe())

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="almanac", brief="Displays information about the current game-day.")
    async def almanac(self, ctx: Context):
        """
        Displays information about the current game-day.

        (5-second cool-down)
        """
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return
        time = game.game_clock.get_seconds()
        sunrise, sunset = game.game_clock.get_sunrise_and_sunset()
        msg = game.game_clock.get_full_date()
        msg += f" Sunrise {'is' if time <= sunrise else 'was'} at {sunrise.get_time()}."
        msg += f" Sunset {'is' if time <= sunset else 'was'} at {sunset.get_time()}."

        # Weather forecast — best-effort, occasionally wrong (as an
        # in-world almanac should be).
        if game.weather is not None:
            from caldanai.lib.rpg.helpers.enums import Seasons
            season = Seasons(game.game_clock.get_season())
            msg += f"\n\nForecast: {game.weather.forecast(season)}"

        Dispatcher.add(game.channel, msg)

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @staticmethod
    def _monster_matches_look_target(monster, target: str) -> bool:
        """Match ``$look <target>`` against the active monster's
        rendered name. Accepts the full display name OR any single
        whitespace-separated token from it.

        Variant-aware: a Hexed Hydra's ``self.name`` is "hexed
        hydra"; players see "hydra" in spawn flavor and reach for
        ``$look hydra``, which the prior literal-equality check
        rejected. Word-token matching catches both "hexed" and
        "hydra" without false-positive partials ("hex" rightly
        fails since it isn't a full token).

        Future generalization is the ``MonsterPlugin.find_plugin_classes``
        fuzzy resolver (already used by ``$spawn``). Today's
        simpler word-token rule covers the immediate UX gap and
        leaves the harder multi-monster disambiguation for the
        time it ships.
        """
        target_lower = target.lower()
        name_lower = (monster.name or "").lower()
        if target_lower == name_lower:
            return True
        return target_lower in name_lower.split()

    @command(name="look", brief="Displays information about the area, a direction, or a creature.")
    async def look(self, ctx: Context, *target: str):
        """
        Displays information about the area, a direction, or a creature.

        (5-second cool-down)

        :param target: A direction in which to look, or a monster or player at which to look.
        """
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        msg = "Nothing to see here, move along!"

        target = " ".join(target) if len(target) > 0 else None

        if target is None:
            if ctx.channel == game.channel:
                msg = game.room0.verbose

            time = game.game_clock.get_time_of_day()
            msg += f" It appears to be {time}."

        elif target.upper() in Directions.__members__:
            direction = Directions[target.upper()]
            msg = game.room0.get_look_direction(direction)
            time = game.game_clock.get_time_of_day()
            msg += f" It appears to be {time}."

        elif game.monster and self._monster_matches_look_target(
            game.monster, target,
        ):
            embed, file = game.monster.get_embed()
            Dispatcher.add(game.channel, embed=embed, file=file)
            return

        elif ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
            p = await RpgUtilities.get_player(ctx.message.mentions[0], game=game, notify=False)
            if p:
                embed = p.get_profile(game.guild.name)
                Dispatcher.add(game.channel, embed=embed)
                return

        Dispatcher.add(game.channel, msg)

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(aliases=["cmproll"], brief="Compares the given options for the calling player and mentioned players.")
    async def compare_roll(self, ctx: Context, *options: str):
        """
        Compares the given options for the calling player and mentioned players.

        :param options: This may be "fumbles", "crits", or a die-type such as "d6" followed by the value to compare.
        :return:
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if ctx.message.mentions is None:
            Dispatcher.add(ctx, "You must include someone for comparison by @mentioning them.")
            return

        if player.member in ctx.message.mentions:
            Dispatcher.add(ctx, "If you need to compare yourself to yourself, then please make use of a mirror.")
            return

        if self.bot.user in ctx.message.mentions:
            Dispatcher.add(ctx, "Comparing yourself to the AI will only leave you feeling inadequate.")
            return

        if not options:
            embed = Embed(
                title=f"Compare Roll help",
                description=f"I gotta have more options! (See `{ctx.prefix}help {ctx.command.name}`)",
                color=0xFF0000,
            )
            Dispatcher.add(ctx, embed=embed)
            return

        opt0 = options[0].lower()
        dice = ("d4", "d6", "d8", "d10", "d12", "d20")
        dtype = "d20" if opt0 in ("fumbles", "crits") else opt0 if opt0 in dice else None

        roll = (
            0
            if opt0 == "fumbles"
            else 19 if opt0 == "crits" else int(options[1]) - 1 if len(options) > 1 and options[1].isnumeric() else None
        )

        if dtype is None or roll is None:
            Dispatcher.add(ctx, f"Invalid options. See `{ctx.prefix}help cmproll` for more information.")
            return

        if roll < 0 or roll > int(dtype[1:]) - 1:
            Dispatcher.add(ctx, "The provided roll value is invalid for the selected die type.")
            return

        r = player.rolls[dtype][roll]
        t = sum(player.rolls[dtype])
        a = r / t if t > 0 else 0
        rolls = {player.name: (r, t, a)}
        name_len = len(player.name)
        roll_len = len(f"{r:,}")
        sum_len = len(f"{t:,}")
        high_avg = a
        low_avg = a

        for m in ctx.message.mentions:
            if p := await RpgUtilities.get_player(m, game, False):
                r = p.rolls[dtype][roll]
                t = sum(p.rolls[dtype])
                a = r / t if t > 0 else 0
                rolls[p.name] = (r, t, a)
                name_len = max(name_len, len(p.name))
                roll_len = max(roll_len, len(f"{r:,}"))
                sum_len = max(sum_len, len(f"{t:,}"))
                high_avg = max(high_avg, a)
                low_avg = min(low_avg, a)

        if len(rolls) < 2:
            Dispatcher.add(ctx, "You must mention other players for comparison.")
            return

        s = sorted(rolls.items(), key=lambda i: i[1][2])
        s.reverse()
        rolls = dict(s)

        msg = f"Comparison of {roll + 1} on a {dtype}:\n```"
        for p, (r, t, a) in rolls.items():
            msg += f"\n{p:>{name_len}}: {r:{roll_len},} / {t:{sum_len},} = {a:.2%}"

        Dispatcher.add(ctx, msg + "```")

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="last_command", brief="Retrieves the most recent command recorded in the database.")
    async def last_command(self, ctx: Context):
        """
        Retrieves the most recent command recorded in the database, and database updates are only sent once per minute. If this appears to not update properly, please inform the bot owner.
        """
        game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        cmd = DB.get_last_command(ctx.guild.id)
        if cmd:
            msg = f'Last command: {cmd["alias"]} @ {cmd["timestamp"]}'
        else:
            msg = "No result from the search for last command. This may indicate that the database is currently disconnected, or there is a larger system issue."

        Dispatcher.add(ctx, msg)

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgInfoCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgInfoCommands(bot))
