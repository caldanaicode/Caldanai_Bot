from random import choice, randint
from typing import Union, Tuple

from discord import Embed
from discord.embeds import EmptyEmbed
from discord.ext.commands import Cog, command, cooldown, BucketType
from discord.ext.commands.errors import MissingRequiredArgument

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout


class GeneralCommands(Cog):
	def __init__(self, bot):
		self.bot = bot
	
	@Cog.listener()
	async def on_ready(self):
		stdout("GeneralCommands ready.")
	
	@command(name='hello', aliases=['hi', 'hey'], brief="Greets the user.")
	@cooldown(1, 5, BucketType.member)
	async def hello(self, ctx):
		"""Greets the user.
		"""
		greeting = f"{choice(('Hello', 'Hi', 'Hey', 'Greetings'))}, {ctx.author.nick or ctx.author.mention}!"
		Dispatcher.add(ctx, greeting)

	async def check_hilo(self, ctx, count: int, options: tuple) -> Union[int, None]:
		idx = None
		hilo = 0
		if 'hi' in options and 'lo' in options:
			embed = Embed(
				title=f'Dice Roll for {ctx.author.nick or ctx.author.name}',
				description="Specify `hi` or `lo`, but not both. Example: ` 4d6 hi 3 ` rolls 4 dice with 6 sides each,"
				" and keeps the 3 highest.",
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)
			return None

		elif 'hi' in options:
			hilo = 1
			idx = options.index('hi') + 1
			
		elif 'lo' in options:
			hilo = -1
			idx = options.index('lo') + 1
		
		if idx is not None and idx < len(options):
			try:
				hilo *= int(options[idx])

			except Exception:
				embed = Embed(
					title=f'Dice Roll for {ctx.author.nick or ctx.author.name}',
					description="Specify how many dice to keep immediately following `hi` or `lo`. Example:"
					" ` 4d6 hi 3 ` rolls 4 dice with 6 sides each, and keeps the 3 highest.",
					color=0xff0000
				)
				Dispatcher.add(ctx, embed=embed)
				return None
			
			if abs(hilo) >= count:
				embed = Embed(
					title=f'Dice Roll for {ctx.author.nick or ctx.author.name}',
					description="The number of rolls to keep must be greater than 0 and less than the number of dice "
					"being rolled. Example: ` 4d6 hi 3 ` rolls 4 dice with 6 sides each, and keeps the 3 highest.",
					color=0xff0000
				)
				Dispatcher.add(ctx, embed=embed)
				return None

		return hilo
	
	async def check_dice(self, ctx, dice: str) -> Tuple[Union[int, None], Union[int, None]]:
		try:
			count, sides = map(int, dice.split('d'))
		except Exception as e:
			embed = Embed(
				title=f'Dice Roll for {ctx.author.nick or ctx.author.name}',
				description="Use the NdN format. Example: ` 3d6 ` rolls 3 dice with 6 sides each.",
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)
			return None, None

		if sides < 2:
			embed = Embed(
				title=f'Dice Roll for {ctx.author.nick or ctx.author.name}',
				description="The number of sides must be greater than 1.",
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)
			return None, None
		
		if count > 1000000:
			embed = Embed(
				title=f'Dice Roll for {ctx.author.nick or ctx.author.name}',
				description=f"Don't be absurd, {ctx.author.mention}! Go roll your own {count:,} dice!",
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)
			return None, None
		return count, sides
	
	@command(name='roll', aliases=['dice'], brief="Rolls dice given in the NdN format.")
	@cooldown(1, 5, BucketType.member)
	async def roll(self, ctx, dice: str, *options: str):
		"""Rolls dice given in the NdN format.

		Use the NdN format. Example: ` 3d6 ` rolls 3 dice with 6 sides each.

		Specify `hi` or `lo` to keep a number of highest or lowest rolls. Example: ` 4d6 hi 3 ` rolls 4 dice with 6
		sides each, and keeps the 3 highest.

		The number of rolls to keep must be greater than 0 and less than the number of dice being rolled.

		Specify `verbose` to show all die rolls. Example: ` 3d8 verbose `
		"""
		count, sides = await self.check_dice(ctx, dice)
		if count is None or sides is None:
			return

		rolls = [randint(1, sides) for d in range(count)]
		dropped = None

		hilo = 0
		verbose = False

		if options is not None:
			verbose = 'verbose' in options
			hilo = await self.check_hilo(ctx, count, options)
			if hilo is None:
				return

		dropped = []
		rolls.sort()

		if hilo == 0:
			pass

		elif hilo < 0:
			dropped = rolls[1-hilo:]
			rolls = rolls[:-hilo]

		else:
			dropped = rolls[:-hilo]
			rolls = rolls[-hilo:]
		
		total = sum(rolls)
		msg = ''
		shorten = False

		if verbose:
			msg = f"```\n[ {' + '.join([str(r) for r in rolls])} ] = {total:,}"
			if dropped is not None and len(dropped) > 0:
				msg += f"\n\nDropped: [ {', '.join([str(d) for d in dropped])} ]"
			msg += "```"
		
		if len(msg) > 2048:
			shorten = True

		if shorten or not verbose:
			msg = f"```\n{count}d{sides}{(' hi ' if hilo > 0 else ' lo ') + str(abs(hilo)) if hilo != 0 else '' } =" \
				f" {total:,}```"
		
		embed = Embed(
			title=f"{ctx.author.nick or ctx.author.name}'s roll",
			description = msg if len(msg) < 2048 else "The result is too large to display.",
			color=0x00ff00
		)

		footer = EmptyEmbed
		if verbose and not shorten:
			footer = f"[ TL;DR ] {count}d{sides}{(' hi ' if hilo > 0 else ' lo ') + str(abs(hilo)) if hilo != 0 else ''}" \
				f" = {total:,}"

		elif verbose:
			footer = 'Verbose ignored due to message length.'
		
		embed.set_footer(text=footer)
		Dispatcher.add(ctx, embed=embed)

	@roll.error
	async def roll_error(self, ctx, exc):
		if isinstance(exc, MissingRequiredArgument):
			embed = Embed(
				title=f'Dice roll for {ctx.author.nick or ctx.author.name} failed',
				description='The dice parameter is required. See `$help roll` for example usage.',
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)


def setup(bot):
	bot.add_cog(GeneralCommands(bot))