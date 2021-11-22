from random import choice
from typing import Optional
from discord import Embed
from discord.utils import get
from discord.ext.commands import Cog, command, Command, cooldown, BucketType, Group
from discord.ext.menus import MenuPages, ListPageSource

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout


def syntax(cmd: Command):
	aliases = [*cmd.aliases]
	aliases.sort()
	params = []
	for key, value in cmd.params.items():
		if key not in ("self", "ctx"):
			params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
	params = " ".join(params)
	parents = [p.name for p in cmd.parents]
	parents.reverse()
	if len(parents) and parents[0] == cmd.name:
		parents.pop(0)
	subs = []

	if isinstance(cmd, Group):
		subs = [s.name if '_' not in s.name or not len(s.aliases) else choice(s.aliases) for s in cmd.commands]
		subs.sort()
		subs = ', '.join(subs)

	result = f"*Description:* {cmd.brief or 'No description available.'}"

	if len(aliases):
		result += f"\n\n*Aliases:* {', '.join(aliases)}"

	if len(subs) > 0:
		result += f"\n\n*Subcommands:* {subs}"

	result += f"\n\n*Usage:* ```\n{' '.join(parents) + ' ' if len(parents) else ''}" \
			  f"{cmd.name if '_' not in cmd.name or not len(aliases) else choice(aliases)} {params}```"

	return result


class HelpMenu(ListPageSource):
	def __init__(self, ctx, data):
		self.ctx = ctx

		super().__init__(data, per_page=3)
	
	async def write_page(self, menu, fields=()):
		offset = (menu.current_page * self.per_page) + 1
		length = len(self.entries)

		embed = Embed(
			title="Help",
			description="Caldanai Bot's very own help dialog.",
			color=0xff7700
		)
		thumb = self.ctx.guild.me.avatar_url if self.ctx.guild is not None else self.ctx.me.avatar_url
		embed.set_thumbnail(url=thumb)
		embed.set_footer(text=f"{offset:,} - {min(length, offset+self.per_page-1):,} of {length:,} commands")

		for name, value in fields:
			embed.add_field(name=name, value=value, inline=False)

		return embed
	
	async def format_page(self, menu: MenuPages, commands):
		fields = []

		for cmd in commands:
			fields.append((cmd.name, syntax(cmd)))
			if cmd != commands[-1]:
				fields.append(('\u200b', '\u200b'))
		return await self.write_page(menu, fields)


class HelpCommands(Cog):
	def __init__(self, bot):
		self.bot = bot
		self.bot.remove_command("help")
	
	@command(name="help", brief="Shows this message.")
	@cooldown(1, 5, BucketType.member)
	async def show_help(self, ctx, cmd: Optional[str], sub: Optional[str]):
		"""
		Shows this message.

		Providing an optional command will show the help for that command in detail. If a subcommand is also
		provided, then only the help for the subcommand will be shown.
		"""
		if cmd is None:
			commands = [c for c in self.bot.commands if not c.hidden]
			commands.sort(key=lambda c: c.name)
			menu = MenuPages(
				source=HelpMenu(ctx, commands),
				delete_message_after=True,
				timeout=60.0
			)

			await menu.start(ctx)
		else:
			if c := get(self.bot.commands, name=cmd):
				if sub is None or not isinstance(c, Group):
					await self.cmd_help(ctx, c)
				elif isinstance(c, Group) and (s := get(c.commands, name=sub)):
					await self.cmd_help(ctx, s)

			else:
				found = False
				for c in self.bot.commands:
					if cmd in c.aliases or (isinstance(c, Group) and (s := get(c.commands, name=sub))):
						found = True
						await self.cmd_help(ctx, s if s else c)

				if not found:
					Dispatcher.add(ctx, f"No such command exists: {cmd}")
	
	async def cmd_help(self, ctx, cmd: Command):
		embed = Embed(
			title=f"Help for `{cmd}`",
			description=syntax(cmd),
			color=0xff7700
		)
		Dispatcher.add(ctx, embed=embed)

	@Cog.listener()
	async def on_ready(self):
		stdout("HelpCommands ready.")


def setup(bot):
	bot.add_cog(HelpCommands(bot))
