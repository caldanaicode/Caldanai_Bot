from typing import Optional
from discord import Embed
from discord.utils import get
from discord.ext.commands import Cog, command, Command, cooldown, BucketType, Group
from discord.ext.menus import MenuPages, ListPageSource

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout


def syntax(cmd: Command):
	aliases = "|".join([str(cmd), *cmd.aliases])
	params = []
	for key, value in cmd.params.items():
		if key not in ("self", "ctx"):
			params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
	params = " ".join(params)

	subs = []
	if isinstance(cmd, Group):
		for sub in cmd.walk_commands():
			if sub.parents[0] == cmd:
				subs.append(f"\n*{sub.name}*\n{sub.help}\n{syntax(sub)}")
	subs = '\n'.join(subs)
	if len(subs) > 0:
		return f"```\n{aliases} {params}```\n**Subcommands:**\n{subs}"
	return f"```\n{aliases} {params}```"


class HelpMenu(ListPageSource):
	def __init__(self, ctx, data):
		self.ctx = ctx

		super().__init__(data, per_page=3)
	
	async def write_page(self, menu, fields=()):
		offset = (menu.current_page*self.per_page) + 1
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
			fields.append((cmd.brief or "No description", syntax(cmd)))

		return await self.write_page(menu, fields)


class HelpCommands(Cog):
	def __init__(self, bot):
		self.bot = bot
		self.bot.remove_command("help")
	
	@command(name="help", brief="Shows this message.")
	@cooldown(1, 5, BucketType.member)
	async def show_help(self, ctx, cmd: Optional[str]):
		"""Shows this message.

		Providing an optional command will show the help for that command in detail.
		"""
		if cmd is None:
			menu = MenuPages(
				source=HelpMenu(ctx, [c for c in self.bot.commands if c.hidden == False]),
				delete_message_after=True,
				timeout=60.0
			)

			await menu.start(ctx)
		else:
			if cmd := get(self.bot.commands, name=cmd):
				await self.cmd_help(ctx, cmd)
			else:
				Dispatcher.add(ctx, f"No such command exists: {cmd}")
	
	async def cmd_help(self, ctx, cmd):
		embed = Embed(
			title=f"Help for `{cmd}`",
			description=syntax(cmd),
			color=0xff7700
		)
		embed.add_field(name="Command Description", value=cmd.help)
		Dispatcher.add(ctx, embed=embed)

	@Cog.listener()
	async def on_ready(self):
		stdout("HelpCommands ready.")


def setup(bot):
	bot.add_cog(HelpCommands(bot))
