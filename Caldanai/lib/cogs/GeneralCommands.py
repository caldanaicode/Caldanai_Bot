from random import randint, choice
from typing import Union, Tuple, Dict

from discord import Embed
from discord.ext import tasks
from discord.ext.commands import Cog, command, cooldown, BucketType, Context
from discord.ext.commands.errors import MissingRequiredArgument

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import get_logger


_log = get_logger(__name__)


class GeneralCommands(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.reminders = {}
        self.reminder_loop.start()

    class Reminder:
        def __init__(self, seconds: int, message: str = ""):
            self.seconds = seconds
            self.message = message

    @Cog.listener()
    async def on_ready(self):
        _log.info("GeneralCommands ready.")

    async def check_hilo(self, ctx: Context, count: int, options: tuple) -> Union[int, None]:
        idx = None
        hilo = 0
        if "hi" in options and "lo" in options:
            embed = Embed(
                title=f"Dice Roll for {ctx.author.nick or ctx.author.name}",
                description="Specify `hi` or `lo`, but not both. Example: ` 4d6 hi 3 ` rolls 4 dice with 6 sides each,"
                " and keeps the 3 highest.",
                color=0xFF0000,
            )
            Dispatcher.add(ctx, embed=embed)
            return None

        elif "hi" in options:
            hilo = 1
            idx = options.index("hi") + 1

        elif "lo" in options:
            hilo = -1
            idx = options.index("lo") + 1

        if idx is not None and idx < len(options):
            try:
                hilo *= int(options[idx])

            except Exception:
                embed = Embed(
                    title=f"Dice Roll for {ctx.author.nick or ctx.author.name}",
                    description="Specify how many dice to keep immediately following `hi` or `lo`. Example:"
                    " ` 4d6 hi 3 ` rolls 4 dice with 6 sides each, and keeps the 3 highest.",
                    color=0xFF0000,
                )
                Dispatcher.add(ctx, embed=embed)
                return None

            if abs(hilo) >= count:
                embed = Embed(
                    title=f"Dice Roll for {ctx.author.nick or ctx.author.name}",
                    description="The number of rolls to keep must be greater than 0 and less than the number of dice "
                    "being rolled. Example: ` 4d6 hi 3 ` rolls 4 dice with 6 sides each, and keeps the 3 highest.",
                    color=0xFF0000,
                )
                Dispatcher.add(ctx, embed=embed)
                return None

        return hilo

    @staticmethod
    def __int__(s: str, fault: int = 1):
        try:
            return fault if (isinstance(s, str) and not s.isnumeric()) else int(s)
        except Exception as e:
            _log.error(e)
            return 0

    async def check_dice(self, ctx: Context, dice: str) -> Tuple[Union[int, None], Union[int, None]]:
        count, sides = map(self.__int__, dice.split("d"))
        if count < 1:
            embed = Embed(
                title=f"Dice Roll for {ctx.author.nick or ctx.author.name}",
                description="Use the NdN format. Example: ` 3d6 ` rolls 3 dice with 6 sides each.",
                color=0xFF0000,
            )
            Dispatcher.add(ctx, embed=embed)
            return None, None

        if sides < 2:
            embed = Embed(
                title=f"Dice Roll for {ctx.author.nick or ctx.author.name}",
                description="The number of sides must be greater than 1.",
                color=0xFF0000,
            )
            Dispatcher.add(ctx, embed=embed)
            return None, None

        if count > 1000000:
            embed = Embed(
                title=f"Dice Roll for {ctx.author.nick or ctx.author.name}",
                description=f"Don't be absurd, <@!{ctx.author.id}>! Go roll your own {count:,} dice!",
                color=0xFF0000,
            )
            Dispatcher.add(ctx, embed=embed)
            return None, None
        return count, sides

    @command(name="reminder", aliases=["remind"], brief="Tells the bot to send you a DM as a reminder for something.")
    @cooldown(1, 5, BucketType.user)
    async def reminder_command(self, ctx: Context, timespan: Union[int, str], *message) -> None:
        """
        Sets a timespan at which the bot will send a DM to the invoker. Using this command again before a reminder has expired will overwrite the existing reminder. Note: Do not use this for very important reminders, as there is no guarantee the bot will available at the desired time. Reminders are not persistent, meaning that should the bot go offline (for restart, power outage, etc), then any reminders will be lost.

        :param timespan: A timespan in the format of [d:][h:][m:]s. Examples: `1:30` is 1 minute, 30 seconds. `1:2:34:56` is 1 day 2 hours 34 minutes 56 seconds. `600` is 600 seconds or 10 minutes.
        :param message: The message the bot will deliver with the reminder.
        """

        if timespan is None or timespan == "":
            Dispatcher.add(ctx, "You must specify the timespan to use.")
            return

        seconds = abs(timespan) if isinstance(timespan, int) else 0

        if isinstance(timespan, str):
            parts = tuple(map(abs, map(lambda x: self.__int__(x, 0), timespan.split(":"))))
            count = len(parts)
            seconds = (
                parts[-1]
                + abs(self.__int__(parts[-2] or 0 if count > 1 else 0) * 60)
                + abs(self.__int__(parts[-3] or 0 if count > 2 else 0) * 3600)
                + abs(self.__int__(parts[-4] or 0 if count > 3 else 0) * 86400)
            )

        if seconds <= 0:
            Dispatcher.add(ctx, "The timespan provided was invalid, or 0.")
            return

        self.reminders[ctx.author] = self.Reminder(seconds, str.join(" ", message))
        Dispatcher.add(ctx, f"Reminder has been set for {seconds} seconds.")

    @reminder_command.error
    async def reminder_error(self, ctx: Context, exc):
        if isinstance(exc, MissingRequiredArgument):
            if ctx.author in self.reminders.keys():
                r = self.reminders[ctx.author]
                embed = Embed(
                    title=f"Approximately {r.seconds:,} seconds remain.",
                    description=r.message or "No message provided.",
                    color=0x00FFFF,
                )

            else:
                embed = Embed(
                    title=f"No reminder available.",
                    description="You have no reminder set at this time.",
                    color=0xFF0000,
                )

            Dispatcher.add(ctx, embed=embed)

    @tasks.loop(seconds=1)
    async def reminder_loop(self):
        remove = ()
        for user, reminder in self.reminders.items():
            if reminder.seconds == 0:
                Dispatcher.add(user, f"Reminder: ```\n{reminder.message}```")
                remove += (user,)
            reminder.seconds -= 1

        for user in remove:
            del self.reminders[user]

    @command(name="roll", aliases=["dice"], brief="Rolls dice given in the NdN format.")
    @cooldown(1, 5, BucketType.member)
    async def roll(self, ctx: Context, dice: str, *options: str):
        """
        Rolls dice given in the NdN format.

        :param dice: Use the NdN format. Example: `3d6` rolls 3 dice with 6 sides each.
        :param options: Specify `hi` or `lo` to keep a number of highest or lowest rolls. Example: `4d6 hi 3` rolls 4 dice with 6 sides each, and keeps the 3 highest.
            The number of rolls to keep must be greater than 0 and less than the number of dice being rolled.
            Specify `verbose` to show all die rolls. Example: `3d8 verbose`
        """
        count, sides = await self.check_dice(ctx, dice)
        if count is None or sides is None:
            return

        rolls = [randint(1, sides) for _ in range(count)]
        dropped = []

        hilo = 0
        verbose = False

        if options is not None:
            verbose = "verbose" in options
            hilo = await self.check_hilo(ctx, count, options)
            if hilo is None:
                return

        rolls.sort()

        if hilo == 0:
            pass

        elif hilo < 0:
            dropped = rolls[1 - hilo :]
            rolls = rolls[:-hilo]

        else:
            dropped = rolls[:-hilo]
            rolls = rolls[-hilo:]

        total = sum(rolls)
        msg = ""
        shorten = False

        if verbose:
            counts: Dict[int, int] = {}
            drops: Dict[int, int] = {}
            for r in rolls:
                counts[r] = 1 + (counts[r] if r in counts else 0)

            for d in dropped:
                drops[d] = 1 + (drops[d] if d in drops else 0)

            msg = str("\n").join([f"{n:3d} * {c}" for n, c in counts.items()])
            msg = f"```\n{msg}\n = {total:,}"
            if dropped is not None and len(dropped) > 0:
                msg += "\n\nDropped: [ "
                msg += ", ".join([f"{n} * {c}" for n, c in drops.items()]) + " ]"
            msg += "```"

        if len(msg) > 2048:
            shorten = True

        if shorten or not verbose:
            msg = (
                f"```\n{count}d{sides}{(' hi ' if hilo > 0 else ' lo ') + str(abs(hilo)) if hilo != 0 else '' } ="
                f" {total:,}```"
            )

        embed = Embed(
            title=f"{ctx.author.nick or ctx.author.name}'s roll",
            description=msg if len(msg) < 2048 else "The result is too large to display.",
            color=0x00FF00,
        )

        footer = ""
        if verbose and not shorten:
            footer = (
                f"[ TL;DR ] {count}d{sides}{(' hi ' if hilo > 0 else ' lo ') + str(abs(hilo)) if hilo != 0 else ''}"
                f" = {total:,}"
            )

        elif verbose:
            footer = "Verbose ignored due to message length."

        embed.set_footer(text=footer)
        Dispatcher.add(ctx, embed=embed)

    @roll.error
    async def roll_error(self, ctx: Context, exc):
        if isinstance(exc, MissingRequiredArgument):
            embed = Embed(
                title=f"Dice roll for {ctx.author.nick or ctx.author.name} failed",
                description="The dice parameter is required. See `$help roll` for example usage.",
                color=0xFF0000,
            )
            Dispatcher.add(ctx, embed=embed)

    @command(brief="Ask the bot for a prediction.")
    @cooldown(1, 5, BucketType.member)
    async def ask(self, ctx: Context):
        """
        Ask the bot a question and receive the questionable wisdom of a possible future.
        """
        choices = [
            "It is certain.",
            "It is decidedly so.",
            "Without a doubt.",
            "Yes, definitely.",
            "You may rely on it.",
            "As I see it, yes.",
            "Most likely.",
            "Outlook good.",
            "Yes.",
            "Signs point to yes.",
            "Reply hazy, try again.",
            "Ask again later.",
            "Better not tell you now.",
            "Cannot predict now.",
            "Concentrate and ask again.",
            "Don't count on it.",
            "My reply is no.",
            "My sources say no.",
            "Outlook not so good.",
            "Very doubtful.",
        ]

        Dispatcher.add(ctx, choice(choices))


async def setup(bot):
    await bot.add_cog(GeneralCommands(bot))
