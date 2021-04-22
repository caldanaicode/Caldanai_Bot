from typing import Optional
from discord import Embed
from discord.utils import get
from discord.ext.commands import Cog, command, cooldown, BucketType
from discord.ext.menus import MenuPages, ListPageSource

def syntax(command):
	aliases = "|".join([str(command), *command.aliases])
	params = []
	for key, value in command.params.items():
		if key not in ("self", "ctx"):
			params.append(f"[{key}]" if "NoneType" in str(value) else f"<{key}>")
	
	params = " ".join(params)
	return f"```\n{aliases} {params}```"


class HelpMenu(ListPageSource):
	def __init__(self, ctx, data):
		self.ctx = ctx

		super().__init__(data, per_page=3)
	
	async def write_page(self, menu, fields=[]):
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

		for name,value in fields:
			embed.add_field(name=name, value=value, inline=False)

		return embed
	
	async def format_page(self, menu, commands):
		fields = []

		for cmd in commands:
			fields.append((cmd.brief or "No description", syntax(cmd)))

		return await self.write_page(menu, fields)

class Help(Cog):
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
			if(command := get(self.bot.commands, name=cmd)):
				await self.cmd_help(ctx, command)
			else:
				await ctx.send(f"No such command exists: {cmd}")
	
	async def cmd_help(self, ctx, command):
		embed = Embed(
			title=f"Help for `{command}`",
			description=syntax(command),
			color=0xff7700)
		embed.add_field(name="Command Description", value=command.help)
		await ctx.send(embed=embed)

	@Cog.listener()
	async def on_ready(self):
		print("Help Cog ready.")


def setup(bot):
	bot.add_cog(Help(bot))