import math
from io import BytesIO
from random import choice

from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed, File
from typing import Union, List, Optional

import pandas
import matplotlib.pyplot as plt

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.lib.cogs.RpgUtilities import RpgUtilities
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg import Game
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import Directions, Pronouns
from Caldanai.lib.rpg.helpers.parser import parse
from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.weapons import Weapon
from Caldanai.db import MongoDB
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

	@guild_only()
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
			player.name = ctx.author.display_name
			player.is_dirty = True
			game.players[ctx.author.id] = player
			Dispatcher.add(game.channel, f'Welcome, {ctx.author.display_name}')

		else:
			Dispatcher.add(game.channel, f'You are already a player in this RPG, {ctx.author.display_name}!')

	@guild_only()
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
			MongoDB.players.delete_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id})
			del game.players[ctx.author.id]
			game.save()
			Dispatcher.add(game.channel, f'You have been removed from the game, {ctx.author.display_name}!')

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
			description=msg.strip() + '```' if len(msg) > 4 else None
		)
		embed.set_thumbnail(url=game.guild.icon_url)
		Dispatcher.add(game.channel, embed=embed)

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

		channel = game.channel if ctx.guild is not None else ctx

		embed = player.get_profile(game.guild.name)
		embed.set_thumbnail(url=game.guild.icon_url)
		Dispatcher.add(channel, embed=embed)

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

		channel = game.channel if ctx.guild is not None else ctx

		embed = player.get_skill_display()
		embed.set_thumbnail(url=game.guild.icon_url)
		Dispatcher.add(channel, embed=embed)

	@guild_only()
	@cooldown(1, 5, BucketType.member)
	@command(brief="Generates a chart using the specified options")
	async def chart(self, ctx, *options: str):
		"""
		Generates a chart using the specified options.

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
			'bar' : {'options': {'stacked': True}, 'labels': ('Rolls', 'Count')},
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

	@command(
		name='attack',
		aliases=['annihilate', 'kill', 'murder', 'destroy', 'obliterate', 'slaughter', 'slay', 'rip&tear'],
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

		if player.is_dead():
			Dispatcher.add(game.channel, f"A ghostly moan escapes the corpse of {player.name}.")
			return

		if any(player.user_id == pid for pid in game.combatants):
			Dispatcher.add(game.channel, f"But {ctx.author.display_name}, you are already attacking!")
			return

		game.combatants.append(player.user_id)
		Dispatcher.add(game.channel, f"{player.name} prepares to attack!")

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

		if player.user_id not in game.loot.keys():
			Dispatcher.add(game.channel, f"{player.name} attempts to loot the corpse, but cannot interact with it.")
			return

		loot = game.loot[player.user_id]
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

		del game.loot[player.user_id]
		if len(dropped) > 0:
			game.loot[player.user_id] = dropped

		Dispatcher.add(game.channel, msg)

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
		game, player = await self.utils().get_game_and_player(ctx)
		if game is None or player is None:
			return

		if player.is_dead():
			Dispatcher.add(game.channel, f"A lonely sigh slips from the corpse of {player.name}.")

		elif msg is not None and len(msg) > 0:
			if game.monster is not None and game.monster.name.lower() in msg.lower():
				if game.monster.on_hugged:
					Dispatcher.add(
						game.channel,
						parse(game.monster.on_hugged(player, ctx.invoked_with), game.monster, player))
			else:
				Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s {msg}*")

		else:
			Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s the air awkwardly.*")

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

		channel = game.channel if ctx.guild is not None else ctx

		if player.is_dead():
			Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
			return

		if hand.lower() not in ('left', 'l', 'right', 'r'):
			Dispatcher.add(channel, "You must specify to which hand the item will be equipped, left (or l) or "
										 "right (or r)")
			return

		if index is None or index < 0 or index >= len(player.inventory):
			Dispatcher.add(channel, f"Invalid item index. See `{game.prefix}inventory` for a list of your items.")
			return

		item = player.inventory.get_by_index(index)
		if not isinstance(item, Weapon):
			Dispatcher.add(channel, f"That item cannot be equipped.")
			return

		if hand.lower()[0] == 'l':
			player.equip_left(item)
		else:
			player.equip_right(item)
		Dispatcher.add(channel, f"{player.name} has equipped {item.get_full_name()}.")

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

		channel = game.channel if ctx.guild is not None else ctx

		if player.is_dead():
			Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
			return

		if hand.lower() not in ('left', 'l', 'right', 'r', 'all'):
			Dispatcher.add(channel, "You must specify which hand to stow, left (or l) or right (or r) or all.")
			return

		msg = ''

		if (hand.lower()[0] == 'l' or hand.lower() == 'all') and player.left_hand is not None:
			msg += f'\n{player.name} stowed {player.left_hand.get_full_name()}.'
			player.disarm_left()

		if (hand.lower()[0] == 'r' or hand.lower() == 'all') and player.right_hand is not None:
			msg += f'\n{player.name} stowed {player.right_hand.get_full_name()}.'
			player.disarm_right()

		Dispatcher.add(channel, msg or f'You had nothing equipped, {player.name}!')

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

		channel = game.channel if ctx.guild is not None else ctx

		if 0 <= index < len(player.inventory):
			embed, file = player.inventory.get_by_index(index).get_embed()
			Dispatcher.add(channel, embed=embed, file=file)
		else:
			Dispatcher.add(channel, f"I'm afraid you don't have that, {player.name}")

	@item.error
	async def item_err(self, ctx, error):
		if isinstance(error, MissingRequiredArgument):
			embed = Embed(
				title=f'Item help',
				description=f"The item's index is required. To find the index, check `{ctx.prefix}inventory`",
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)

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

	@cooldown(1, 2, BucketType.member)
	@command(name='sell', brief='Sells an item, range of items, unequipped items, or items having a given rarity.')
	async def sell(self, ctx, flag: Union[int, str] = None, count: int = None, gid: int = None):
		"""
		Sells an item, range of items, all items, or items having a given rarity. Items must be unequipped to be sold.
		When selling an individual item, you may specify a quantity to sell if the item is stackable.

		(2-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		if player.is_dead():
			Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
			return

		if flag is None:
			Dispatcher.add(channel, "You must specify the item index to sell, the range of indices, a rarity, "
								"or 'all' to sell anything not equipped.")
			return

		msg = ''
		equipped = []
		sell_all = False
		if player.left_hand:
			equipped.append(player.left_hand.id)
		if player.right_hand:
			equipped.append(player.right_hand.id)

		sell: List[Item] = []

		if isinstance(flag, int) and 0 <= flag < len(player.inventory):
			item = player.inventory.get_by_index(flag)
			if count and item.stackable and (count < 0 or count > item.count):
				Dispatcher.add(channel, f'The number of items to sell must be greater than 0 and less than '
									f'{item.count + 1}')
				return

			if item.id not in equipped:
				sell.append(item)
				if count is None:
					sell_all = True
			else:
				Dispatcher.add(channel, 'You must unequip items before selling them.')
				return

		elif isinstance(flag, str):
			sell_all = True
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
							channel, f"I'm afraid I can't do that, {player.name}. You may want to check your numbers."
						)
						return

				except ValueError:
					Dispatcher.add(channel, f"Unable to determine lower and upper indices from {flag}.")
					return
			else:
				sell = [i for i in list(player.inventory.all()) if i is not None and i.rarity.name.lower() ==
						flag.lower() and i.id not in equipped]

		else:
			Dispatcher.add(channel, f"I'm afraid you don't have that, {player.name}")
			return

		if len(sell) > 0:
			for item in sell:
				msg += f"\n{player.sell(item, count or 1, sell_all)}"

		if len(msg) == 0:
			Dispatcher.add(channel, f'You had no items to sell, {player.name}')
			return
		else:
			msg = f'{player.name} sold the following items: ```\n{msg}```'

		msgs = Dispatcher.split_message(msg, 'clarks.', True)
		count = 0
		for m in msgs:
			Dispatcher.add(
				channel,
				('```\n' if count > 0 else '') + m + ('```' if count > 0 and not m.endswith('```') else '')
			)
			count += 1

	@cooldown(1, 5, BucketType.member)
	@command(name='gender', brief='Displays or sets the user\'s gender.')
	async def gender(self, ctx, gender: Optional[str] = None):
		"""
		Displays or sets the user's gender.

		(5-second cool-down)
		"""
		game, player = await self.utils().get_game_and_player(ctx)
		if game is None or player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		if gender:
			player.gender = gender.lower()
			player.is_dirty = True
			Dispatcher.add(channel, f"{player.name}'s gender has been set to '{player.gender}'. "
										 f"You may also wish to set your `{ctx.prefix}pronouns`")
		else:
			Dispatcher.add(channel, f"{player.name}'s gender is currently shown as '{player.gender}'.")

	@cooldown(1, 5, BucketType.member)
	@guild_only()
	@command(name='pronouns', brief='Displays or sets the user\'s pronouns.')
	async def pronouns(self, ctx, pronouns: Optional[str] = None):
		"""
		Displays or sets the user's pronouns using subject/object/possessive/adjective form.

		(5-second cool-down)
		"""
		game, player = await self.utils().get_game_and_player(ctx)
		if game is None or player is None:
			return

		if pronouns is None:
			Dispatcher.add(
				game.channel,
				f"{player.name}'s pronouns are currently shown as '{'/'.join(player.pronouns.values())}'.")
			return

		if isinstance(pronouns, str):
			p = pronouns.split('/')
			if len(p) != 4:
				Dispatcher.add(
					game.channel, f"Please enter pronouns in the form of 'subject/object/possessive/adjective'. "
					f"Example: `{ctx.prefix}pronouns she/her/hers/her` or `{ctx.prefix}pronouns he/him/his/his`."
				)
				return

			player.pronouns[Pronouns.SUBJECTIVE] = p[0]
			player.pronouns[Pronouns.OBJECTIVE] = p[1]
			player.pronouns[Pronouns.POSSESSIVE] = p[2]
			player.pronouns[Pronouns.ADJECTIVE] = p[3]
			player.pronouns[Pronouns.REFLEXIVE] = f"{p[1]}self"
			player.is_dirty = True
			Dispatcher.add(
				game.channel, f"{player.name}'s pronouns have been set to '"
							  f"{'/'.join(player.pronouns.values())}'. You may also wish to set your `"
							  f"{ctx.prefix}gender`"
			)

	@cooldown(1, 5, BucketType.member)
	@command(name='health', brief='Displays the player\'s current health and regeneration.')
	async def health(self, ctx, flag: str = None):
		"""
		Displays the player's current health and regeneration. If the word 'all' is supplied, all players' health are
		shown without the regeneration message. If the word 'hurt' is supplied, only the players who are not at full
		health are shown.

		(5-second cool-down)
		"""
		game, player = await self.utils().get_game_and_player(ctx)

		if game is None or player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		if flag and flag.lower() in ('all', 'hurt'):
			players = sorted(
				sorted([
					i for i in game.players.values()
					if flag == 'all' or (flag == 'hurt' and i.health < i.health_max)
				], key=lambda x: x.name.lower())
				, key=lambda x: x.health / x.health_max
			)

			if players is None or len(players) == 0:
				msg = "No players are injured."

			else:
				msg = f'```diff'
				for p in players:
					msg += f"\n{'-' if p.health < p.health_max else '+'} {p.name}: {p.health} / {p.health_max}"
				msg += '\n```'

			Dispatcher.add(channel, msg)

		else:
			Dispatcher.add(
				channel, f"{player.name}, you currently have {player.health} / {player.health_max} "
							  f"health, and {player.health_regen} regeneration per game-hour."
			)

	@cooldown(1, 5, BucketType.member)
	@guild_only()
	@command(name='haunt', brief='Allows the dead to harass the less-dead.')
	async def haunt(self, ctx, target: str = None):
		"""
		Allows the dead to harass the less-dead. When specifying a target, use the @ symbol to target another player.

		(5-second cool-down)
		"""
		game, player = await self.utils().get_game_and_player(ctx)
		haunted = None

		if game is None or player is None:
			return

		if target is not None:
			if game.monster is not None and game.monster.name == target.lower():
				haunted = game.monster
			elif ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
				haunted = await self.utils().get_player(ctx.message.mentions[0])

			if haunted is None or not isinstance(haunted, Creature):
				await self.haunt(ctx)
				return

			msgs = [
				f"{'The ' if not isinstance(haunted, Player) else ''}@2 glances around the area suspiciously as @2s "
				f"senses the unearthly presence of @1.",
				f"Soft laughter echoes in {'the ' if not isinstance(haunted, Player) else ''}@2's ears as @1's spirit toys with @2o.",
				f"{'The ' if not isinstance(haunted, Player) else ''}@2's breath suddenly catches as @1's shade wisps through @2o."
			]

		else:
			msgs = [
				f"The ghostly presence of @1 floods into the area briefly before ebbing away.",
				f"A sudden chill blankets the area as @1's spirit wafts through.",
				f"@1's forlorn lament brings with it a cold, solemn feeling."
			]

		if player.is_dead():
			msg = choice(msgs)
		else:
			msg = f"@1 pretends to float around, making supposedly ghostly noises, but it's not very effective."

		Dispatcher.add(game.channel, parse(msg, player, haunted))

	@cooldown(1, 60, BucketType.member)
	@command(
		name='pray',
		aliases=['meditate', 'reflect'],
		brief='Beseeches heavenly blessings.'
	)
	async def pray(self, ctx):
		"""
		Beseeches heavenly blessings. Occasionally, prayers may be answered...

		(60-second cool-down)
		"""
		game, player = await self.utils().get_game_and_player(ctx)

		if game is None or player is None:
			return

		if ctx.guild is None:
			Dispatcher.add(ctx, f"I see you're interested in a little private reflection...")
			return

		if player.is_dead():
			msg = choice([
				"Posthumous piety profits particularly poorly, @1.",
				"Your prayers can no longer pierce the planes of piety, @1.",
				"It seems, @1, that if anyone is listening, they no longer care...",
				"The power of prayer eludes the dead, @1.",
				"Hideous cackling erupts from unseen places as the spirit of @1 seeks salvation.",
				"A sense of dread settles over @1's shade, and @1s cries out forlornly."
			])
			Dispatcher.add(game.channel, parse(msg, player))
			return

		msgs = [
			"@1 offers a solemn prayer, seeking forgiveness and humility.",
			"@1 seeks the guidance of the Divine.",
			"@1 falls to @1a knees in reverence, face lifted to the sky as @1s basks in a divine embrace.",
			"@1's eyes turn skyward as @1s entreats the Divine for benevolence.",
			"@1 proffers words of hope, attempting to sooth the splintered souls of comrades."
		]

		msg = choice(msgs)
		d20 = Dice.d20()
		msg += f" (1d{d20.sides} = {d20.value})"
		player.update_roll_count(d20.sides, d20.value)
		heal_amount = 0
		actors = [player,]
		if d20.value == 1:
			msg += "\nSacrifice is demanded for your insolence, @1!\n\nA sudden storm explodes into the area, " \
				"as a blinding bolt of lightning envelopes @1. When the light fades, nothing remains but a charred husk."

			msg += f"\n\n{player.apply_damage(player.health)}\n\nThe storm calms to a gentle rain..."

			index = 2
			for p in game.players.values():
				if p != player and p.health < p.health_max:
					msg += f"\n@{index}'s skin glows softly under the touch of the rain. "
					heal_msg = p.apply_damage(p.health - p.health_max)
					if heal_msg:
						msg += f"{heal_msg} "
					msg += f"@{index}'s health is completely restored!"
					actors.append(p)
					index += 1

		elif d20.value > 17:
			heal_target: Player = player

			for p in game.players.values():
				if p.health < heal_target.health:
					heal_target = p

			missing_health = heal_target.health_max - heal_target.health
			actors.append(heal_target)
			index = len(actors)
			third = math.ceil(missing_health / 3)

			if third > 1:
				if d20.value == 18:
					heal_amount = Dice.quick_roll(f"1d{third}")
				elif d20.value == 19:
					heal_amount = Dice.quick_roll(f"1d{third}") + third
				elif d20.value == 20:
					heal_amount = Dice.quick_roll(f"1d{third}") + third * 2
			elif missing_health == 1:
				heal_amount = 1
			else:
				heal_amount = Dice.quick_roll(f"1d{missing_health}")

			heal_msg = heal_target.apply_damage(-heal_amount)

			if heal_msg:
				msg += f"\n{heal_msg}"

			msg += f"\nA warm light suffuses @{index}, "

			if heal_amount > 0 and missing_health > 0:
				msg += f"imbuing @{index}o with {heal_amount} points of health!"
			else:
				msg += f"and a pleasant tingle envelops @{index}o without noticeable effect."

		Dispatcher.add(game.channel, parse(msg, *actors))

	@cooldown(1, 10, BucketType.member)
	@guild_only()
	@command(name='time', brief='Displays the game\'s time.')
	async def time(self, ctx):
		"""
		Displays the game's time.

		(10-second cool-down)
		"""
		game = await self.utils().get_game(ctx)
		if game is None:
			return

		msg = game.game_clock.get_full_date()

		Dispatcher.add(game.channel, msg)

	@cooldown(1, 5, BucketType.member)
	@guild_only()
	@command(name='almanac', brief='Displays the game-day\'s time periods.')
	async def almanac(self, ctx):
		"""
		Displays the game-day's time periods.

		(5-second cool-down)
		"""
		game = await self.utils().get_game(ctx)
		if game is None:
			return
		time = game.game_clock.get_seconds()
		sunrise, sunset = game.game_clock.get_sunrise_and_sunset()
		msg = game.game_clock.get_full_date()
		msg += f" Sunrise {'is' if time <= sunrise else 'was'} at {sunrise.get_time()}."
		msg += f" Sunset {'is' if time <= sunset else 'was'} at {sunset.get_time()}."
		Dispatcher.add(game.channel, msg)

	@cooldown(1, 5, BucketType.member)
	@guild_only()
	@command(name='look', brief='Display\'s information about the area, or more information about a creature.')
	async def look(self, ctx, target: str = None):
		"""
		Display's information about the area, or details about a creature or direction.

		(5-second cool-down)
		"""
		game = await self.utils().get_game(ctx)
		if game is None:
			return

		msg = "Nothing to see here, move along!"

		if target is None:
			if ctx.channel == game.channel:
				msg = game.room0.verbose

			time = game.game_clock.get_time_of_day()
			msg += f" It appears to be {time}."

		elif target.upper() in Directions.__members__:
			direction = Directions[target.upper()]
			msg += game.room0.get_look_direction(direction)

		elif game.monster and target.lower() == game.monster.name:
			embed, file = game.monster.get_embed()
			Dispatcher.add(game.channel, embed=embed, file=file)
			return

		elif ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
			p = await self.utils().get_player(ctx.message.mentions[0])
			if p:
				embed = p.get_profile(game.guild.name)
				Dispatcher.add(game.channel, embed=embed)
				return

		Dispatcher.add(game.channel, msg)

	@Cog.listener()
	async def on_ready(self):
		stdout("RpgUserCommands ready.")


def setup(bot):
	bot.add_cog(RpgUserCommands(bot))
