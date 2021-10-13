from io import BytesIO

from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed, File
from typing import Union, List, Optional

import pandas
import matplotlib.pyplot as plt

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.lib.cogs.RpgUtilities import RpgUtilities
from Caldanai.lib.rpg.game import Game
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.inventory.item import Item
from Caldanai.lib.rpg.inventory.weapon import Weapon
from Caldanai.db.db import MongoDB
from datetime import datetime


class RpgUserCommands(Cog):
	def __init__(self, bot):
		self.bot = bot
		self.utilCog: Optional[RpgUtilities] = None

	def utils(self) -> RpgUtilities:
		if self.utilCog is None:
			self.utilCog = self.bot.get_cog("RpgUtilities")
		return self.utilCog

	@group(brief="Groups together various game commands for players.")
	@guild_only()
	@cooldown(1, 10, BucketType.member)
	async def game(self, ctx):
		"""
		Requires a subcommand.
		(10-second cool-down)
		"""

		if ctx.invoked_subcommand is None:
			Dispatcher.add(ctx, "This command cannot be used on its own.")
			return

	# Adds a player to the RPG system if they don't already exist.
	@game.command(brief="Adds a player to the RPG system.")
	async def join(self, ctx):
		"""
		Adds a member to the RPG system as a player if they do not already exist in the database. This can only be
		called by the member trying to participate.
		"""

		game: Game = await self.utils().get_game(ctx)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game, False)
		if player is None:
			player = Player(gid=ctx.guild.id, uid=ctx.author.id, joined=datetime.now())
			player.member = ctx.author
			player.isDirty = True
			game.players[ctx.author.id] = player
			Dispatcher.add(game.channel, f'Welcome, {ctx.author.display_name}')

		else:
			Dispatcher.add(game.channel, f'You are already a player in this RPG, {ctx.author.display_name}!')

	# Removes a player from the RPG system.
	@game.command(name="leave", brief="Removes the player from the RPG system.")
	async def leave(self, ctx, gid: int = None):
		"""
		Removes an existing player from the game. This can only be called by member withdrawing from participation.
		"""

		game: Game = await self.utils().get_game(ctx, gid)

		if game is None:
			return

		player: Player = game.players[ctx.author.id]

		if player is not None:
			MongoDB.players.delete_one({'guildId': ctx.guild.id, 'userId': ctx.author.id})
			del game.players[ctx.author.id]
			game.save()
			Dispatcher.add(game.channel, f'You have been removed from the game, {ctx.author.display_name}!')

	# Lists all players of the current RPG.
	@command(brief="Lists the current players in a game.")
	@cooldown(1, 10, BucketType.guild)
	async def players(self, ctx, gid: int = None):
		"""
		Lists the current players in the game.
		(10-second cool-down across the server)
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		length = len(game.players)
		s = list(game.players.values())
		s.sort(key=lambda p: p.member.display_name)
		msg = "```\n"
		for idx, player in enumerate(s):
			msg += f"{idx}: {player.member.display_name}\n"

		embed = Embed(
			title=f"There {'is' if length == 1 else 'are'} currently {length:,} player{'' if length == 1 else 's'}.",
			description=msg.strip()+'```' if len(msg) > 4 else None
		)
		embed.set_thumbnail(url=game.guild.icon_url)
		Dispatcher.add(game.channel, embed=embed)

	# Send a DM to the player with their profile.
	@command(brief="Shows a player's profile.")
	@cooldown(1, 10, BucketType.member)
	async def profile(self, ctx, gid: int = None):
		"""
		Shows a player's profile.
		(10-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player: Player = game.players[ctx.author.id] if ctx.author.id in game.players.keys() else None

		if player is None:
			return

		embed = player.get_profile(game.guild.name)
		embed.set_thumbnail(url=game.guild.icon_url)
		if ctx.guild is None:
			Dispatcher.add(player.member, embed=embed)
		else:
			Dispatcher.add(game.channel, embed=embed)

	@command(brief="Shows a player's skills.")
	@cooldown(1, 10, BucketType.member)
	async def skills(self, ctx, gid: int = None):
		"""
		Shows a player's skills.
		(10-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player: Player = game.players[ctx.author.id] if ctx.author.id in game.players.keys() else None

		if player is None:
			return

		embed = player.get_skill_display()
		embed.set_thumbnail(url=game.guild.icon_url)
		if ctx.guild is None:
			Dispatcher.add(player.member, embed=embed)
		else:
			Dispatcher.add(game.channel, embed=embed)

	@guild_only()
	@cooldown(1, 5, BucketType.member)
	@command(brief="Generates a chart using the specified options")
	async def chart(self, ctx, *options: str):
		"""
		Generates a chart using the specified options.
		:param ctx: The Discord context of the command.
		:param options: Options for the display of the chart and data.
			[d4, d6, d8, d10, d12, d20] The dice rolls for which to show data. Default is d20.
			[bar, barh, area, line] The type of chart to show. Default is bar.
			[all] Compiles data for all players.
		"""

		game: Game = await self.utils().get_game(ctx)
		if game is None:
			return

		data_types = ('d4', 'd6', 'd8', 'd10', 'd12', 'd20')

		plot_types = {
			# 'hexbin': {'x': 'index', 'y': ''},
			'bar': {'options': {'stacked': True}, 'labels': ('Rolls', 'Count')},
			# 'pie': {'options': {'y': 'Roll Counts', 'subplots': True}},
			'barh': {'options': {'stacked': True}, 'labels': ('Count', 'Rolls')},
			# 'scatter': {},
			'hist': {'options': {}, 'labels': ('Rolls by Count', 'Count Total')},
			# 'density': {},
			'area': {'options': {}, 'labels': ('Rolls', 'Count')},
			'line': {'options': {}, 'labels': ('Rolls', 'Count')}
		}

		rolls = 0
		total = 0
		kind = 'bar'
		tcolor = (0., 1., 0.7, 1.)
		dtype = 'd20'
		dsize = 20

		for option in options:
			opt = option.lower()
			if opt in plot_types.keys():
				kind = opt
			if opt in data_types:
				dtype = opt
				dsize = int(opt.split('d')[1])

		if 'all' in options:
			data = {p.name: p.rolls[dtype] for p in game.players.values() if any(p.rolls[dtype])}
			if len(data) == 0:
				data = {'None': (0,) * dsize}
			df = pandas.DataFrame(data, index=range(1, dsize + 1), dtype='int')
			for d in data.values():
				for idx, count in enumerate(d):
					rolls += count
					total += (idx + 1) * count

			mean = total / rolls if rolls > 0 else 0
			ax = df.plot(kind=f'{kind}', **plot_types[kind]['options'])
			ax.legend(
				bbox_to_anchor=(1, 1),
				loc="upper left",
				facecolor='black',
				framealpha=0.3,
				edgecolor=tcolor,
				labelcolor=tcolor
			)

		else:
			player: Player = game.players[ctx.author.id] if ctx.author.id in game.players.keys() else None
			if player is None:
				return

			data = player.rolls[dtype]
			df = pandas.DataFrame(data, index=range(1, dsize + 1), dtype='int')
			for idx, count in enumerate(data):
				rolls += count
				total += (idx + 1) * count

			mean = total / rolls if rolls > 0 else 0
			ax = df.plot(kind=f'{kind}', legend=False, **plot_types[kind]['options'])

		try:
			ax.set_xlabel(plot_types[kind]['labels'][0])
			ax.set_ylabel(plot_types[kind]['labels'][1])
			ax.xaxis.label.set_color(tcolor)
			ax.yaxis.label.set_color(tcolor)
			ax.set_ybound(lower=0)
			ax.tick_params(axis='both', colors=tcolor)
			ax.grid(True, axis='y', color=tcolor, alpha=0.25)
			for spine in ax.spines.values():
				spine.set_color(tcolor)
		except:
			pass

		buffer = BytesIO()
		plt.savefig(buffer, format='png', transparent=True, bbox_inches="tight")
		plt.close()
		buffer.seek(0)

		file = File(buffer, filename='plot.png')
		Dispatcher.add(ctx, file=file)
		Dispatcher.add(ctx, f"Count: {rolls:,}, Mean: {mean:.2f}")

	# Attacks the current monster.
	@command(
		name='attack',
		aliases=['kill', 'murder', 'destroy', 'obliterate', 'slaughter'],
		brief="Attacks the critter currently daring to show it's face to intrepid adventurers!"
	)
	@guild_only()
	@cooldown(1, 10, BucketType.member)
	async def attack(self, ctx):
		"""
		Attacks the critter currently daring to show it's face to intrepid adventurers!
		(10-second cool-down)
		"""

		game, player = await self.utils().get_game_and_player(ctx)

		if game is None or player is None:
			return

		if game.monster is None:
			Dispatcher.add(game.channel, "You see nothing to attack!")
			return

		if any(player.userId == pid for pid in game.combatants):
			Dispatcher.add(game.channel, f"But {ctx.author.display_name}, you are already attacking!")
			return

		game.combatants.append(player.userId)
		Dispatcher.add(game.channel, f"{player.name} prepares to attack!")

	# Loots the current monster, if it was defeated.
	@command(aliases=['spoils', 'pillage', 'plunder'], brief='Loots the remains of a recently-felled foe.')
	@guild_only()
	@cooldown(1, 10, BucketType.member)
	async def loot(self, ctx):
		"""
		Loots the remains of a recently-felled foe.
		(10-second cool-down)
		"""

		game, player = await self.utils().get_game_and_player(ctx)

		if game is None or player is None:
			return

		if game.monster is not None:
			Dispatcher.add(game.channel, "You should probably kill it before you try to loot it.")
			return

		if len(game.loot) == 0:
			Dispatcher.add(game.channel, "There is nothing to loot!")
			return

		if player.userId not in game.loot.keys():
			Dispatcher.add(game.channel, f"{player.name} attempts to loot the corpse, but cannot interact with it.")
			return

		loot = game.loot[player.userId]
		msg = ', '.join([f"{item.get_full_name()}" for item in loot])
		dropped: List[Item] = []
		if msg is not None and len(msg) > 0:
			msg = f"{player.name} found {' and '.join(msg.rsplit(', ', 1))}."
			for item in loot:
				if not player.give_item(item):
					dropped.append(item)
			if len(dropped) > 0:
				txt = ', '.join([f'{d.get_full_name()}' for d in dropped]).rsplit(', ', 1)
				txt = ' and '.join(txt)
				msg += f" It appears you may have a hoarding problem, though. The following item" \
					f"{'s' if len(dropped) > 1 else ''} would overburden you: {txt}."
		else:
			msg = f"{player.name} pokes around the corpse, finding nothing useful."

		del game.loot[player.userId]
		if len(dropped) > 0:
			game.loot[player.userId] = dropped

		Dispatcher.add(game.channel, msg)

	# Hugs, snuggles, or cuddles!
	@command(name='hug', aliases=['snuggle', 'cuddle'], brief='Hugs, snuggles, and cuddles for all of your needs!')
	@guild_only()
	@cooldown(1, 5, BucketType.member)
	async def hug(self, ctx, *, msg: str = None):
		"""
		Hugs, snuggles, and cuddles for all of your needs!

		See that monster over there?! It's just angry because it never feels loved!
		Want to show your fellows a little appreciation? There's a hug for them too!

		(5-second cool-down)
		"""
		if msg is not None and len(msg) > 0:
			game: Game = await self.utils().get_game(ctx, False)
			if game is not None and game.monster is not None and game.monster.name.lower() in msg.lower():
				if game.monster.on_hugged:
					Dispatcher.add(ctx, game.monster.on_hugged(ctx.author.display_name, ctx.invoked_with))
			else:
				Dispatcher.add(ctx, f"*{ctx.author.display_name} {ctx.invoked_with}s {msg}*")
		else:
			Dispatcher.add(ctx, f"*{ctx.author.display_name} {ctx.invoked_with}s the air awkwardly.*")
		await ctx.message.delete()

	@command(name='equip', aliases=['wield', 'ready'], brief='Equips a weapon to a given hand.')
	@cooldown(1, 5, BucketType.member)
	async def equip(self, ctx, hand: str, index: int, game_idx: int = None):
		"""
		Equips a weapon to the given hand.
		(5-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if hand.lower() not in ('left', 'l', 'right', 'r'):
			Dispatcher.add(ctx, "You must specify to which hand the item will be equipped, left (or l) or right (or r)")
			return

		if index is None or index < 0 or index >= len(player.inventory):
			Dispatcher.add(ctx, f"Invalid item index. See `{game.prefix}inventory` for a list of your items.")
			return

		item = player.inventory.get_by_index(index)
		if not isinstance(item, Weapon):
			Dispatcher.add(ctx, f"That item cannot be equipped.")
			return

		if hand.lower()[0] == 'l':
			player.equip_left(item)
		else:
			player.equip_right(item)
		Dispatcher.add(ctx, f"You have equipped {item.get_full_name()}.")

	@command(name='stow', aliases=['disarm', 'unequip'], brief='Unequips the item in the given hand.')
	@cooldown(1, 5, BucketType.member)
	async def stow(self, ctx, hand: str, game_idx: int = None):
		"""
		Unequips a weapon from the given hand, or all equipped items.
		(5-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if hand.lower() not in ('left', 'l', 'right', 'r', 'all'):
			Dispatcher.add(ctx, "You must specify which hand to stow, left (or l) or right (or r) or all.")
			return

		msg = ''

		if (hand.lower()[0] == 'l' or hand.lower() == 'all') and player.leftHand is not None:
			msg += f'\nStowed {player.leftHand.get_full_name()}.'
			player.disarm_left()

		if (hand.lower()[0] == 'r' or hand.lower() == 'all') and player.rightHand is not None:
			msg += f'\nStowed {player.rightHand.get_full_name()}.'
			player.disarm_right()

		Dispatcher.add(ctx, msg or 'You had nothing equipped!')

	@command(
		name='inventory',
		aliases=['inv', 'items', 'bag'],
		brief='Sends a DM to the player with information about the items they carry.'
	)
	@cooldown(1, 10, BucketType.member)
	async def inventory(self, ctx, game_idx: int = None):
		"""
		Sends a DM to the player with information about the items they carry.
		(10-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if ctx.guild is not None:
			await ctx.message.delete()

		Dispatcher.add(player.member, f'Inventory for {player.name} on {game.guild.name}')
		inv = Dispatcher.split_message(player.get_inventory(), keep_sep=True)
		for msg in inv:
			Dispatcher.add(player.member, f'```js\n{msg.strip()}```')

	@command(name='item', brief='Displays details about an item.')
	@cooldown(1, 2, BucketType.member)
	async def item(self, ctx, index: int, game_idx: int = None):
		"""
		Displays details about an item.
		(2-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if 0 <= index < len(player.inventory):
			embed, file = player.inventory.get_by_index(index).get_embed()
			Dispatcher.add(ctx, embed=embed, file=file)
		else:
			Dispatcher.add(ctx, f"I'm afraid you don't have that, {player.name}")

	@item.error
	async def item_err(self, ctx, error):
		if isinstance(error, MissingRequiredArgument):
			embed = Embed(
				title=f'Item help',
				description=f"The item's index is required. To find the index, check `{ctx.prefix}inventory`",
				color=0xff0000
			)
			Dispatcher.add(ctx.author, embed=embed)

	# Returns a string to display games in which a user is currently playing.
	@cooldown(1, 60, BucketType.user)
	@command(
		name='games',
		brief='Sends a DM to the calling player with a list of games in which they are a member.'
	)
	async def games_display(self, ctx):
		"""
		Sends a DM to the calling player with a list of games in which they are a member.
		(60-second cool-down)
		"""

		msg = ""
		games = self.utils().get_games_for_user(ctx.author.id)
		for idx, game in enumerate(games):
			msg += f'{idx}: {game.guild.name}\n'

		Dispatcher.add(ctx.author, f'```js\n{msg}```' if len(msg) > 0 else "You are not playing any games.")
		if ctx.guild is not None:
			await ctx.message.delete()

	# Sells an item, range of items, unequipped items, or items having a given rarity.
	@cooldown(1, 2, BucketType.member)
	@command(name='sell', brief='Sells an item, range of items, unequipped items, or items having a given rarity.')
	async def sell(self, ctx, flag: Union[int, str] = None, gid: int = None):
		"""
		Sells an item, range of items, all items, or items having a given rarity. Items must be unequipped to be sold.
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if flag is None:
			Dispatcher.add(ctx, "You must specify the item index to sell, the range of indices, a rarity, or 'all' to "
								"sell anything not equipped.")
			return

		msg = ''
		equipped = [player.leftHand.id, player.rightHand.id]
		sell: List[Item] = []

		if isinstance(flag, int) and 0 <= flag < len(player.inventory):
			item = player.inventory.get_by_index(flag)
			if item.id not in equipped:
				sell.append(item)
			else:
				Dispatcher.add(ctx, 'You must unequip items before selling them.')
				return

		elif isinstance(flag, str):
			if flag.lower() == 'all':
				sell = [i for i in list(player.inventory.all()) if i is not None and i.id not in equipped]
			elif '-' in flag:
				try:
					low, high = map(int, flag.split('-'))
					if low > high:
						tmp = low
						low = high
						high = tmp

					if 0 <= low < high <= len(player.inventory):
						for i in range(high, low - 1, -1):
							item = player.inventory.get_by_index(i)
							if item.id not in equipped:
								sell.append(item)

					else:
						Dispatcher.add(
							ctx,
							f"I'm afraid I can't do that, {player.name}. You may want to check your numbers."
						)
						return

				except ValueError:
					Dispatcher.add(ctx, f"Unable to determine lower and upper indices from {flag}.")
					return
			else:
				sell = [i for i in list(player.inventory.all()) if i is not None and i.rarity.name.lower() ==
						flag.lower() and i.id not in equipped]

		else:
			Dispatcher.add(ctx, f"I'm afraid you don't have that, {player.name}")
			return

		if len(sell) > 0:
			for item in sell:
				msg += f"\n{player.sell(item)}"

		if len(msg) == 0:
			Dispatcher.add(ctx, f'You had no items to sell, {player.name}')
			return
		else:
			msg = f'{player.name} sold the following items: ```\n{msg}```'

		msgs = Dispatcher.split_message(msg, 'clarks.', True)
		count = 0
		for m in msgs:
			Dispatcher.add(
				ctx,
				('```\n' if count > 0 else '') + m + ('```' if count > 0 and not m.endswith('```') else '')
			)
			count += 1

	@Cog.listener()
	async def on_ready(self):
		stdout("RpgUserCommands ready.")


def setup(bot):
	bot.add_cog(RpgUserCommands(bot))
