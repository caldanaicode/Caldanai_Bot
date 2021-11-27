from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed
from typing import Union, List, Optional

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.lib.cogs.RpgUtilities import RpgUtilities
from Caldanai.lib.rpg import Game
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory import Armor, Item
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


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
	async def equip(self, ctx, item: Union[str, int], slot: str = None, gid: int = None):
		"""
		Equips an item.

		(5-second cool-down)

		:param item: An item name, item.n, item.rarity, item.rarity.n, or index to equip. .n indicates to use the nth of item, for example 'rock.2' would grab the second rock in your inventory. 'spear.rare' or 'spear.rare.1' would grab the first rare spear in your inventory.

		:param slot: If not provided, the item will be auto-equipped to the best slot, if possible. For weapons or other one-hand-equipped items like rings, the slot will be 'left' or 'right'. Most armor can auto-equip, but you may specify the slot such as 'head', 'torso', or 'waist'. For a full list of slots, see your `profile`.

		:param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
		"""
		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx
		_item: Union[Weapon, Armor, None] = None

		if player.is_dead():
			Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
			return

		_item, *_ = player.inventory.filter(item)

		if not _item:
			Dispatcher.add(channel, "You don't seem to have such an item.")
			return

		if not isinstance(_item, Equipment):
			Dispatcher.add(channel, f"That item cannot be equipped.")
			return

		if slot:
			if slot.lower() in ('l', 'left'):
				_slot = EquipmentSlots.LEFT_SIDE & _item.slots

			elif slot.lower() in ('r', 'right'):
				_slot = EquipmentSlots.RIGHT_SIDE & _item.slots

			elif slot.lower() == '_':
				_slot = _item.slots

			else:
				return Dispatcher.add(channel, f"I don't know how to turn {slot} into a 'left' or 'right'...")

			return Dispatcher.add(channel, player.equip(_item, EquipmentSlots(_slot)))

		return Dispatcher.add(channel, player.equip(_item))

	@command(aliases=['slots', 'gear'], brief="Shows a player's equipment.")
	@cooldown(1, 10, BucketType.member)
	async def equipment(self, ctx, gid: int = None):
		"""
		Shows a player's equipment.

		(10-second cool-down)

		:param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player: Player = game.players[ctx.author.id] if ctx.author.id in game.players.keys() else None

		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		embed = player.get_equipment(game.guild.name)
		embed.set_thumbnail(url=game.guild.icon_url)
		Dispatcher.add(channel, embed=embed)

	@command(name='stow', aliases=['disarm', 'unequip'], brief='Un-equip an item by slot.')
	@cooldown(1, 5, BucketType.member)
	async def stow(self, ctx, item_or_slot: Union[str, int], gid: int = None):
		"""
		Un-equip an item by name, name.n, index, or slot.

		(5-second cool-down)

		:param item_or_slot: An item name, item.n, item.rarity, item.rarity.n, index, or slot to un-equip. .n indicates to use the nth of item, for example 'rock.2' would grab the second rock in your inventory. 'spear.rare' or 'spear.rare.1' would grab the first rare spear in your inventory. Slot indicates the body part on which the item is equipped, such as 'left_hand', 'head', or 'feet'. To see a full list of the slots you are currently using, see the `profile` command.

		:param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		if player.is_dead():
			Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
			return

		if not item_or_slot:
			Dispatcher.add(channel, "You must specify the item or slot which you would like to un-equip.")
			return

		msg = "I'm unable to determine which item you meant."
		_item: Optional[Equipment] = None
		if isinstance(item_or_slot, int):
			_item, *_ = player.inventory.filter(item_or_slot)

		elif isinstance(item_or_slot, str):
			for s in EquipmentSlots:
				if s.name == item_or_slot.replace(' ', '_').upper():
					_item = player.equip_slots[s.name]
					break

			if not _item:
				_item, *_ = player.inventory.filter(item_or_slot)

		if _item:
			msg = player.remove(_item.slots)

		Dispatcher.add(channel, msg or f'You had nothing equipped, {player.name}!')

	@command(
		name='inventory',
		aliases=['inv', 'items', 'bag'],
		brief='Sends a DM to the player with information about the items they carry.'
	)
	@cooldown(1, 5, BucketType.member)
	async def inventory(self, ctx, filtr: str = None, gid: int = None):
		"""
		Sends a DM to the player with information about the items they carry.

		(5-second cool-down)

		:param filtr: If provided, filter the items by name or rarity containing the given string. If playing on more than one server and you wish to use this in DM to display all items, specify _ as the filter before specifying the game index.

		:param gid: If calling from a DM and playing on more than one server, provide the game's index for which you wish to view inventory. Use the 'games' command to determine the game index.
		"""

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player: Player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		if ctx.guild is not None:
			await ctx.message.delete()

		Dispatcher.add(player.member, f'Inventory for {player.name} on {game.guild.name}')
		inv = Dispatcher.split_message(player.get_inventory(filtr), keep_sep=True)

		for msg in inv:
			Dispatcher.add(player.member, f'```js\n{msg.strip()}```')

	@command(name='item', brief='Displays details about an item.')
	@cooldown(1, 2, BucketType.member)
	async def item(self, ctx, name: Union[str, int], gid: int = None):
		"""
		Displays details about an item.
		
		(2-second cool-down)
		
		:param name: An item name, item.n, item.rarity, item.rarity.n, or index to display. .n indicates to use the nth of item, for example 'rock.2' would grab the second rock in your inventory. 'spear.rare' or 'spear.rare.1' would grab the first rare spear in your inventory.
			
		:param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
		"""

		if not name:
			Dispatcher.add(ctx, "Please specify an item.")
			return

		game: Game = await self.utils().get_game(ctx, gid)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game)
		if player is None:
			return

		channel = game.channel if ctx.guild is not None else ctx

		item, *_ = player.inventory.filter(name)

		if item:
			embed, file = item.get_embed()
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

	@cooldown(1, 2, BucketType.member)
	@command(name='sell', brief='Sells an item, range of items, unequipped items, or items having a given rarity.')
	async def sell(self, ctx, flag: Union[int, str] = None, count: int = None, gid: int = None):
		"""
		Sells items by name, name.n, index, a range of indices, all items, or items having a given rarity.
		Items must be unequipped to be sold.
		When selling an individual item, you may specify a quantity to sell if the item is stackable.

		(2-second cool-down)

		:param flag: An item name, name.n, name.rarity, name.rarity.n, index, range of indices, rarity, or 'all'.

		:param count: If the given item is stackable, provide the number you wish to sell unless you used the 'all'	flag.

		:param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
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
			Dispatcher.add(
				channel,
				"You must specify the item name, name.n, name.rarity, name.rarity.n, index, the range of indices, "
				"a rarity, or 'all'."
			)
			return

		msg = ''
		equipped = ([i.id for s, i in player.equip_slots.items() if i and not EquipmentSlots.exclude_from_output(s)])
		sell_all = False
		sell: List[Item] = []

		if isinstance(flag, int) or flag.isnumeric() and 0 <= int(flag) < len(player.inventory):
			item = player.inventory.filter(flag)
			if count and isinstance(item, Stackable) and (count < 0 or count > item.count):
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
				Dispatcher.add(channel, 'You must un-equip items before selling them.')
				return

		elif isinstance(flag, str):
			sell_all = True
			if flag.lower() == 'all':
				sell = [i for i in list(player.inventory.all()) if i.id not in equipped]
			elif '-' in flag:
				try:
					low, high = map(int, flag.split('-'))
					low -= 1
					high -= 1
					if low > high:
						tmp = low
						low = high
						high = tmp

					if 0 <= low < high < len(player.inventory):
						sell = [filter(lambda i: i.id not in equipped, player.inventory.all()[low:high])]

					else:
						Dispatcher.add(
							channel, f"I'm afraid I can't do that, {player.name}. You may want to check your numbers."
						)
						return

				except ValueError:
					Dispatcher.add(channel, f"Unable to determine lower and upper indices from {flag}.")
					return
			else:
				sell = [i for i in player.inventory.filter(flag) if i.id not in equipped]

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
	async def use(self, ctx, item: Union[int, str], gid: int = None):
		"""
		Attempts to use an item.

		(5-second cool-down)

		:param item: An item name, item.n, item.rarity, item.rarity.n, or index to display. .n indicates to use the nth of item, for example 'candy.2' would grab the second candy in your inventory. 'sandwich.rare' or 'sandwich.rare.1' would grab the first rare sandwich in your inventory.

		:param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
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

		_item, *_ = player.inventory.filter(item)

		if _item:
			Dispatcher.add(channel, player.use_item(_item))

		else:
			Dispatcher.add(channel, f"I'm afraid you don't have that, {player.name}")

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
