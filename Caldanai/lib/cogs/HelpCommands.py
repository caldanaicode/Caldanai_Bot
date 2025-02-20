import re
from random import choice
from typing import Optional
from discord import Embed
from discord.utils import get
from discord.ext.commands import Cog, command, Command, cooldown, BucketType, Group, HelpCommand, Context
from discord.ext.menus import MenuPages, ListPageSource

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import get_logger


_log = get_logger(__name__)
paramRegex = re.compile(r":param (?P<name>[^:]+):")


def syntax(cmd: Command, prefix: str, verbose: bool = False):
    aliases = [*cmd.aliases]
    aliases.sort()
    params = []
    for key, value in cmd.clean_params.items():
        if key not in ("self", "ctx"):
            params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
    params = " ".join(params)
    subs = []

    if isinstance(cmd, Group):
        subs = [s.name if "_" not in s.name or not len(s.aliases) else choice(s.aliases) for s in cmd.commands]
        subs.sort()
        subs = ", ".join(subs)

    result = (
        f"```\n{prefix}{cmd.full_parent_name + (' ' if cmd.full_parent_name else '')}"
        f"{cmd.name if '_' not in cmd.name or not len(aliases) else choice(aliases)} {params}```"
    )

    if not verbose:
        result += f"\n__Description__\n{cmd.brief.strip() or 'No description available.'}\n"

    if len(aliases):
        result += f"\n__Aliases__\n{', '.join(aliases)}\n"

    if len(subs) > 0:
        result += f"\n__Subcommands__\n{subs}\n"

    if verbose:
        doc = cmd.callback.__doc__
        if doc:
            while match := paramRegex.search(doc):
                doc = paramRegex.sub(f"*{match.groups('name')[0]}*\n", doc, 1)
            result += f"\n__Details__\n{doc.strip()}"

    return result.strip()


class HelpMenu(ListPageSource):
    def __init__(self, ctx: Context, data):
        self.ctx = ctx
        super().__init__(data, per_page=3)

    async def write_page(self, menu, fields=()):
        offset = (menu.current_page * self.per_page) + 1
        length = len(self.entries)

        embed = Embed(title="Help", description="Caldanai Bot's very own help dialog.", color=0xFF7700)
        thumb = self.ctx.guild.me.avatar.url if self.ctx.guild is not None else self.ctx.me.avatar.url
        embed.set_thumbnail(url=thumb)
        embed.set_footer(text=f"{offset:,} - {min(length, offset+self.per_page-1):,} of {length:,} commands")

        for name, value in fields:
            embed.add_field(name=name, value=value, inline=False)

        return embed

    async def format_page(self, menu: MenuPages, commands):
        fields = []

        for cmd in commands:
            fields.append(
                (cmd.name, f"{syntax(cmd, self.ctx.prefix)}\n" + ("\u2581" * 20 if cmd != commands[-1] else ""))
            )
        return await self.write_page(menu, fields)


class HelpCommands(Cog):
    def __init__(self, bot):
        self.bot = bot
        self.bot.remove_command("help")

    @command(
        name="help",
        brief="Shows a help menu if no command is provided, otherwise shows help specific to the given command.",
    )
    @cooldown(1, 5, BucketType.member)
    async def show_help(self, ctx: Context, cmd: Optional[str], sub: Optional[str]):
        """
        Shows a help menu if no command is provided, otherwise shows help specific to the given command.

        :param cmd: The command for which to show help information.
        :param sub: If provided, shows help specific to the given subcommand.
        """
        if cmd is None:
            help_cmd = HelpCommand()
            help_cmd.context = ctx
            commands = await help_cmd.filter_commands(self.bot.commands, sort=True)
            menu = MenuPages(source=HelpMenu(ctx, commands), delete_message_after=True, timeout=60.0)

            await menu.start(ctx)
        else:
            if c := get(self.bot.commands, name=cmd):
                if sub is None or not isinstance(c, Group):
                    await self.cmd_help(ctx, c)
                elif isinstance(c, Group) and (
                    s := get(c.commands, name=sub) or list(filter(lambda sc: sub in sc.aliases, c.commands))
                ):
                    await self.cmd_help(ctx, s[0] if isinstance(s, list) and len(s) > 0 else s)

            else:
                found = False
                for c in self.bot.commands:
                    s = None
                    if cmd in c.aliases or (isinstance(c, Group) and (s := get(c.commands, name=sub))):
                        found = True
                        await self.cmd_help(ctx, s or c)

                if not found:
                    Dispatcher.add(ctx, f"No such command exists: {cmd}")

    @staticmethod
    async def cmd_help(ctx: Context, cmd: Command):
        embed = Embed(title=f"Help for `{cmd}`", description=syntax(cmd, ctx.prefix, True), color=0xFF7700)
        Dispatcher.add(ctx, embed=embed)

    @Cog.listener()
    async def on_ready(self):
        _log.info("HelpCommands ready.")


async def setup(bot):
    await bot.add_cog(HelpCommands(bot))
