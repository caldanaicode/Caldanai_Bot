from discord.ext.commands import Cog, command, cooldown, BucketType
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed
from typing import Union, List, Optional

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.lib.cogs.RpgUtilities import RpgUtilities
from Caldanai.lib.rpg import Game
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.weapons import Weapon


class RpgInventoryCommands(Cog):
	def __init__(self, bot):
		self.bot = bot
		self.utilCog: Optional[RpgUtilities] = None

	def utils(self) -> RpgUtilities:
		if self.utilCog is None:
			self.utilCog = self.bot.get_cog("RpgUtilities")
		return self.utilCog

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
	@cooldown(1, 5, BucketType.member)
	async def inventory(self, ctx, filtr: str = None, game_idx: int = None):
		"""
		Sends a DM to the player with information about the items they carry.

		(5-second cool-down)

		:param filtr: If provided, filter the items by name or rarity containing the given string. If playing on more than one server and you wish to use this in DM to display all items, specify _ as the filter before specifying the game index.

		:param game_idx: If calling from a DM and playing on more than one server, provide the game's index for which you wish to view inventory. Use the 'games' command to determine the game index.
		"""

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if ctx.guild is not None:
			await ctx.message.delete()

		if filtr == '_':
			filtr = None

		Dispatcher.add(player.member, f'Inventory for {player.name} on {game.guild.name}')
		inv = Dispatcher.split_message(player.get_inventory(filtr), keep_sep=True)
		for msg in inv:
			Dispatcher.add(player.member, f'```js\n{msg.strip()}```')

	@command(name='item', brief='Displays details about an item.')
	@cooldown(1, 2, BucketType.member)
	async def item(self, ctx, name: str = "", game_idx: int = None):
		f"""
		Displays details about an item.
		
		(2-second cool-down)
		
		:param name: The name of the item to display. If you have more than one of that type, the first will be 
			shown. If you wish to specify another, use .n after the name where n is the number to use. For example, 
			to display the third stick in your inventory, enter '{self.bot.command_prefix}item stick.3' without the 
			quotation marks.  
		:param game_idx: If you are playing on multiple servers and wish to use this from DM, specify the game index to 
			which you wish to refer. Use '{self.bot.command_prefix}games' to determine the game index for the server you 
			desire.
		"""

		if not name:
			Dispatcher.add(ctx, "Please specify an item.")
			return

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		item = player.inventory.filter(name)
		if len(item):
			embed, file = item[0].get_embed()
			Dispatcher.add(channel, embed=embed, file=file)
			return

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
				Dispatcher.add(
					channel,
					f'The number of items to sell must be greater than 0 and less than {item.count + 1}'
				)
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
				sell = [i for i in list(player.inventory.all()) if i.id not in equipped]
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
				sell = [i for i in player.inventory.filter_by_rarity(flag) if i.id not in equipped]

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

	@command(name='use', brief='Attempts to use an item.')
	@cooldown(1, 5, BucketType.member)
	async def use(self, ctx, item: Union[int, str], game_idx: int = None):
		"""
		Attempts to use an item.

		(5-second cool-down)
		"""

		game: Game = await self.utils().get_game(ctx, game_idx)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		if player.is_dead():
			Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
			return

		if item.isnumeric():
			item = int(item)
			if 0 <= item < len(player.inventory):
				Dispatcher.add(channel, player.use_item(item))
			else:
				Dispatcher.add(channel, f"I'm afraid you don't have that, {player.name}")
		else:
			Dispatcher.add(channel, player.use_item(item))

	@use.error
	async def use_err(self, ctx, error):
		if isinstance(error, MissingRequiredArgument):
			embed = Embed(
				title=f'Item help',
				description=f"The item's name or index is required. To find the index, check `{ctx.prefix}inventory`",
				color=0xff0000
			)
			Dispatcher.add(ctx, embed=embed)

	@Cog.listener()
	async def on_ready(self):
		stdout("RpgInventoryCommands ready.")


def setup(bot):
	bot.add_cog(RpgInventoryCommands(bot))
