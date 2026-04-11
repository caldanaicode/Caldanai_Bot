from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, Context
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed
from typing import Union, List, Optional

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import get_logger
from Caldanai.lib.rpg.helpers.parser import item_list_to_string
from Caldanai.lib.rpg.helpers.utils import RpgUtilities
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory import Armor, Item
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


_log = get_logger(__name__)

class RpgInventoryCommands(Cog):
    def __init__(self, bot):
        self.bot = bot

    @command(name='equip', aliases=['wield', 'ready'], brief='Equips a weapon to a given hand.')
    @cooldown(1, 2, BucketType.member)
    async def equip(self, ctx: Context, item: Union[str, int], slot: str = None, gid: int = None):
        """
        Equips an item.

        (5-second cool-down)

        :param item: An item name, item.n, item.quality, item.quality.n, or index to equip. .n indicates to use the nth of item, for example 'rock.2' would grab the second rock in your inventory. 'spear.quality' or 'spear.quality.1' would grab the first quality spear in your inventory.

        :param slot: If not provided, the item will be auto-equipped to the best slot, if possible. For weapons or other one-hand-equipped items like rings, the slot will be 'left' or 'right'. Most armor can auto-equip, but you may specify the slot such as 'head', 'torso', or 'waist'. For a full list of slots, see your `gear`.

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        channel = game.channel if ctx.guild is not None else ctx
        _item: Union[Weapon, Armor, None] = None

        if player.is_dead():
            Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
            return

        _item, *_ = player.inventory.filter(item)
        _slot = None

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

            elif slot == '_':
                _slot = _item.slots

            else:
                return Dispatcher.add(channel, f"I don't know how to turn *{slot}* into a **left** or **right**...")

        result = player.equip(_item, EquipmentSlots(_slot) if _slot else None)

        if result[0]:
            if result[1]:
                Dispatcher.add(channel, f"{player.name} equipped {_item.get_full_name()}, replacing {result[1]}.")
            else:
                Dispatcher.add(channel, f"{player.name} equipped {_item.get_full_name()}.")

        else:
            Dispatcher.add(channel, result[1])

    @command(aliases=['slots', 'gear'], brief="Shows a player's equipment.")
    @cooldown(1, 10, BucketType.member)
    async def equipment(self, ctx: Context, options: str = None, gid: int = None):
        """
        Shows a player's equipment.

        (10-second cool-down)

        :param options: Specify the word 'all' if you want to show all inventory slots, even if empty.
        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx, gid)

        if not game or not player:
            return

        show_all = bool(options and options.lower() == 'all')
        channel = game.channel if ctx.guild is not None else ctx
        embed = player.get_equipment(game.guild.name, show_all)
        embed.set_thumbnail(url=game.guild.icon.url)
        Dispatcher.add(channel, embed=embed)

    @command(name='stow', aliases=['disarm', 'unequip'], brief='Un-equip an item by slot.')
    @cooldown(1, 2, BucketType.member)
    async def stow(self, ctx: Context, item_or_slot: Union[str, int], gid: int = None):
        """
        Un-equip an item by name, name.n, index, or slot.

        (5-second cool-down)

        :param item_or_slot: An item name, item.n, item.quality, item.quality.n, index, or slot to un-equip. .n indicates to use the nth of item, for example 'rock.2' would grab the second rock in your inventory. 'spear.quality' or 'spear.quality.1' would grab the first quality spear in your inventory. Slot indicates the body part on which the item is equipped, such as 'left_held', 'head', or 'feet'. To see a full list of the slots you are currently using, see the `gear` command.

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
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
            msg = player.remove(_item)

        Dispatcher.add(channel, msg or f'You had nothing equipped, {player.name}!')

    @command(
        name='inventory',
        aliases=['inv', 'items', 'bag'],
        brief='Sends a DM to the player with information about the items they carry.'
    )
    @cooldown(1, 5, BucketType.member)
    async def inventory(self, ctx: Context, filtr: str = None, gid: int = None):
        """
        Sends a DM to the player with information about the items they carry.

        (5-second cool-down)

        :param filtr: If provided, filter the items by name or quality containing the given string. If playing on more than one server and you wish to use this in DM to display all items, specify _ as the filter before specifying the game index.

        :param gid: If calling from a DM and playing on more than one server, provide the game's index for which you wish to view inventory. Use the 'games' command to determine the game index.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        if ctx.guild is not None:
            await ctx.message.delete()

        Dispatcher.add(player.member, f'Inventory for {player.name} on {game.guild.name}')
        inv = Dispatcher.split_message(player.get_inventory(filtr), keep_sep=True)

        for msg in inv:
            Dispatcher.add(player.member, f'```js\n{msg.strip()}```')

    @command(name='item', brief='Displays details about an item.')
    @cooldown(1, 2, BucketType.member)
    async def item(self, ctx: Context, name: Union[str, int], gid: int = None):
        """
        Displays details about an item.

        (2-second cool-down)

        :param name: An item name, item.n, item.quality, item.quality.n, or index to display. .n indicates to use the nth of item, for example 'rock.2' would grab the second rock in your inventory. 'spear.masterwork' or 'spear.masterwork.1' would grab the first masterwork spear in your inventory.

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
            return

        if not name:
            Dispatcher.add(ctx, "Please specify an item.")
            return

        channel = game.channel if ctx.guild is not None else ctx
        item, *_ = player.inventory.filter(name)

        if item:
            embed, file = item.get_embed()
            Dispatcher.add(channel, embed=embed, file=file)
            return

        Dispatcher.add(channel, f"I'm afraid you don't have that, {player.name}")

    @item.error
    async def item_err(self, ctx: Context, error):
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
    async def loot(self, ctx: Context):
        """
        Loots the remains of a recently-felled foe.

        (10-second cool-down)
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)

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
        msg = item_list_to_string(loot)
        dropped: List[Item] = []
        if msg is not None and len(msg) > 0:
            msg = f"{player.name} found {msg}."
            for item in loot:
                if not player.give_item(item):
                    dropped.append(item)
            if len(dropped) > 0:
                txt = item_list_to_string(dropped)
                msg += f" It appears you may have a hoarding problem, though. The following item" \
                    f"{'s' if len(dropped) > 1 else ''} would overburden you: {txt}."
        else:
            msg = f"{player.name} pokes around the corpse, finding nothing useful."

        del game.loot[player.user_id]
        if len(dropped) > 0:
            game.loot[player.user_id] = dropped

        Dispatcher.add(game.channel, msg)

    @cooldown(1, 2, BucketType.member)
    @guild_only()
    @command(name='sell', brief='Sells an item, range of items, unequipped items, or items having a given rarity.')
    async def sell(self, ctx: Context, *items: Union[int, str]):
        """
        Sells items by name, name.n, index, a range of indices, all items, or items having a given rarity.
        Items must be unequipped to be sold.

        (2-second cool-down)

        :param items: An item name, name.n, name.quality, name.quality.n, index, range of indices, quality,
        or 'all'. You may also specify multiple items with a space between them (i.e. 'stick rock spear.junk')
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        channel = game.channel if ctx.guild is not None else ctx

        if player.is_dead():
            Dispatcher.add(channel, f"A frustrated wail escapes the corpse of {player.name}.")
            return

        if items is None or len(items) == 0:
            Dispatcher.add(channel, "You must specify something to sell.")
            return

        msg = ''
        equipped = ([i.id for s, i in player.equip_slots.items() if i and not EquipmentSlots.exclude_from_output(s)])
        sell: List[Item] = []
        total = 0

        for _item in items:
            if (isinstance(_item, int) or _item.isnumeric()) and 1 <= int(_item) <= len(player.inventory):
                item, *_ = player.inventory.filter(_item)

                if item and item.id not in equipped:
                    sell.append(item)
                elif item is not None:
                    msg += f'\nYou must un-equip {item.get_full_name()} before selling them.'
                else:
                    msg += f'\nNo such item: {_item}.'

            elif isinstance(_item, str):
                if _item.lower() == 'all':
                    sell += [i for i in list(player.inventory.all()) if i.id not in equipped]
                elif '-' in _item:
                    try:
                        low, high = map(int, _item.split('-'))
                        if low > high:
                            tmp = low
                            low = high
                            high = tmp

                        low -= 1
                        if 0 <= low <= high <= len(player.inventory):
                            sell += list(filter(lambda i: i.id not in equipped, player.inventory.all()[low:high]))

                        else:
                            msg += f"\nIndex range invalid."

                    except ValueError:
                        msg += f"\nUnable to determine lower and upper indices from {_item}."
                else:
                    sell += [i for i in player.inventory.filter(_item) if i and i.id not in equipped]

            else:
                msg += f"\nI'm afraid you don't have any {_item}."

        if len(sell) > 0:
            for item in sell:
                m, v = player.sell(item, 1, True)
                msg += f"\n{m}"
                total += v

        msg = f'{player.name} sold the following items for a total of {total:,} clarks: ```\n{msg}```'
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
    async def use(self, ctx: Context, item: Union[int, str], gid: int = None):
        """
        Attempts to use an item.

        (5-second cool-down)

        :param item: An item name, item.n, item.quality, item.quality.n, or index to display. .n indicates to use the nth of item, for example 'candy.2' would grab the second candy in your inventory. 'sandwich.fine' or 'sandwich.fine.1' would grab the first fine sandwich in your inventory.

        :param gid: For use in DMs when playing on more than one server. Specify the game's index for which information is to be displayed. The game indices can be determined by using the `games` command.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)
        if game is None or player is None:
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
    async def use_err(self, ctx: Context, error):
        if isinstance(error, MissingRequiredArgument):
            embed = Embed(
                title=f'Item help',
                description=f"The item's name or index is required. To find the index, check `{ctx.prefix}inventory`",
                color=0xff0000
            )
            Dispatcher.add(ctx, embed=embed)

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgInventoryCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgInventoryCommands(bot))
