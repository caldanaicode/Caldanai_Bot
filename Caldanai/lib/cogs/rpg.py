from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group
from discord.ext.commands.errors import MissingRequiredArgument
from discord import Embed
from typing import List, Union

from Caldanai.lib.rpg.game import Game
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.inventory.weapon import Weapon
from Caldanai.db.db import MongoDB
from datetime import datetime


class RPG(Cog):
    def __init__(self, bot):
        self.bot = bot

    # Gets a list of games to which a user belongs.
    def get_games_for_user(self, uid: int) -> List[Game]:
        games = []
        if uid is None:
            return games

        players = MongoDB.players.find({'userId': uid})
        for player in players:
            game = self.bot.games[player['guildId']]
            games.append(game)

        return games

    # Get the game associated with a context, it if exists.
    async def get_game(self, ctx, game_idx: int = None) -> Union[Game, None]:
        game: Union[Game, None] = None
        games: List[Game] = []
        if ctx.guild is None:
            games = self.get_games_for_user(ctx.author.id)
        else:
            game = self.bot.games[ctx.guild.id]

        if len(games) == 0 and game is None:
            await ctx.send(f"You are not a member of any games at this time.")
            return None

        if game is None:
            if len(games) > 1 and game_idx is None:
                await ctx.send(
                    f"You are playing more than one game and did not supply the game's index."
                    f" Check `{ctx.prefix}games` to get the index of the game from which you wish to"
                    f" view your profile, or try again from the game's channel.")
                return None
            elif len(games) > 1 and len(games) > game_idx >= 0:
                game = games[game_idx]
            elif len(games) == 1:
                game = games[0]
            else:
                await ctx.send("No such game exists.")
                return None

        return game

    # Gets the player associated with a context, if any exists
    async def get_player(self, ctx, game: Game = None, notify: bool = True) -> Union[Player, None]:
        if game is None or not isinstance(game, Game):
            game: Game = await self.get_game(ctx)

        if game is None:
            return None

        if ctx.author.id not in game.players.keys():
            if notify:
                await game.send(f'Why, {ctx.author.display_name}! You are not even playing the game! Try ` $game join`')
        else:
            return game.players[ctx.author.id]
        return None

    # Returns a tuple containing (game, player) if both exist.
    async def get_game_and_player(self, ctx, notify: bool = True) -> (Game, Player):
        game: Game = await self.get_game(ctx)
        if game is None:
            return None, None

        player: Player = await self.get_player(ctx, game, notify)
        return game, player

    @group()
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def game(self, ctx):
        if ctx.invoked_subcommand is None:
            await ctx.send("This command cannot be used on its own.")
            return

    # Adds a player to the RPG system if they don't already exist.
    @game.command(brief="Adds a player to the RPG system.")
    async def join(self, ctx):
        """Adds a player to the RPG system.

        Adds a member to the RPG system as a player if they do not already exist in the database. This can only be
        called by the member trying to participate.
        (60-second cool-down)"""
        game: Game = await self.get_game(ctx)
        if game is None:
            return

        player = await self.get_player(ctx, game, False)
        if player is None:
            player = Player(gid=ctx.guild.id, uid=ctx.author.id, member=ctx.author, joined=datetime.now())
            player.save()
            game.players[ctx.author.id] = player
            await game.send(f'Welcome, {ctx.author.display_name}')

        else:
            await game.send(f'You are already a player in this RPG, {ctx.author.display_name}!')

    # Removes a player from the RPG system.
    @game.command(name="leave", brief="Removes the player from the RPG system.")
    async def leave(self, ctx, gid: int = None):
        """Removes the player from the RPG system.

        Removes an existing player from the game. This can only be called by member withdrawing from participation.
        (60-second cool-down)"""
        game: Game = await self.get_game(ctx, gid)

        if game is None:
            return

        player: Player = game.players[ctx.author.id]

        if player is not None:
            MongoDB.players.delete_one({'guildId': ctx.guild.id, 'userId': ctx.author.id})
            del game.players[ctx.author.id]
            game.save()
            await game.send(f'You have been removed from the game, {ctx.author.display_name}!')

    # Lists all players of the current RPG.
    @command(brief="Lists the current players in a game.")
    @cooldown(1, 60, BucketType.guild)
    async def players(self, ctx, gid: int = None):
        """Lists the current players in the game.
        (60-second cool-down for everyone)"""
        game: Game = await self.get_game(ctx, gid)
        if game is None:
            return

        length = len(game.players)
        msg = f"There {'is' if length == 1 else 'are'} currently {length:,}" \
              f"player{'s' if length > 1 or length == 0 else ''}.\n"
        for pid, player in game.players.items():
            msg += f"\t{player.member.display_name}\n"
        await game.send(f'```\n{msg}```')

    # Send a DM to the player with their profile.
    @command(brief="Shows a player's profile.")
    @cooldown(1, 10, BucketType.member)
    async def profile(self, ctx, gid: int = None):
        """Shows a player's profile.

        Sends a DM to the calling player with their profile results.
        (10-second cool-down)"""

        game: Game = await self.get_game(ctx, gid)
        if game is None:
            return

        player: Player = game.players[ctx.author.id] if ctx.author.id in game.players.keys() else None

        if player is None:
            return

        embed = player.get_profile(game.guild.name)
        embed.set_thumbnail(url=game.guild.icon_url)
        await player.send(embed=embed)
        if ctx.guild is not None:
            await ctx.message.delete()

    # Attacks the current monster.
    @command(name='attack', aliases=['kill', 'murder'],
             brief="Attacks the critter currently daring to show it's face to intrepid adventurers!")
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def attack(self, ctx):
        """Attacks the critter currently daring to show it's face to intrepid adventurers!

        (10-second cool-down)"""
        game, player = await self.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if game.monster is None:
            await game.send("You see nothing to attack!")
            return

        if any(player.userId == pid for pid in game.combatants):
            await game.send(f"But {ctx.author.display_name}, you are already attacking!")
            return

        game.combatants.append(player.userId)
        await game.send(f"{player.name} prepares to attack!")

    # Loots the current monster, if it was defeated.
    @command(name='loot', aliases=['spoils', 'pillage', 'plunder'], brief='Loots the remains of a recently-felled foe.')
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def loot(self, ctx):
        """Loots the remains of a recently-felled foe."""
        game, player = await self.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if game.monster is not None:
            await game.send("You should probably kill it before you try to loot it.")
            return

        if len(game.loot) == 0:
            await game.send("There is nothing to loot!")
            return

        if player.userId not in game.loot.keys():
            await game.send(f"{player.name} attempts to loot the corpse, but cannot interact with it.")
            return

        loot = game.loot[player.userId]
        msg = ', '.join([f"{item.article} {item.rarity.name} {item.name}" for item in loot])
        if msg is not None and len(msg) > 0:
            msg = f"{ctx.author.display_name} found {' and '.join(msg.rsplit(', ', 1))}."
            for item in loot:
                player.give_item(item)
        else:
            msg = f"{ctx.author.display_name} pokes around the corpse, finding nothing useful."
        del game.loot[player.userId]
        await game.send(msg)

    # Hugs, snuggles, or cuddles!
    @command(name='hug', aliases=['snuggle', 'cuddle'], brief='Hugs, snuggles, and cuddles for all of your needs!')
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def hug(self, ctx, *, msg: str = None):
        """Hugs, snuggles, and cuddles for all of your needs!

        See that monster over there?! It's just angry because it never feels loved!
        Want to show your fellows a little appreciation? There's a hug for them too!

        (5-second cool-down)
        """
        if msg is not None and len(msg) > 0:
            game: Game = await self.get_game(ctx, False)
            if game is not None and game.monster is not None and game.monster.name.lower() in msg.lower():
                await ctx.send(game.monster.receiveHug(ctx.author.display_name, ctx.invoked_with))
            else:
                await ctx.send(f"*{ctx.author.display_name} {ctx.invoked_with}s {msg}*")
        else:
            await ctx.send(f"*{ctx.author.display_name} {ctx.invoked_with}s the air awkwardly.*")
        await ctx.message.delete()

    @command(name='equip', aliases=['wield', 'ready'], brief='Equips a weapon to a given hand.')
    @cooldown(1, 5, BucketType.member)
    async def equip(self, ctx, hand: str, index: int, game_idx: int = None):
        game: Game = await self.get_game(ctx, game_idx)
        if game is None:
            return

        player: Player = await self.get_player(ctx, game)
        if player is None:
            return

        if hand.lower() not in ('left', 'l', 'right', 'r'):
            await ctx.send("You must specify to which hand the item will be equipped, left (or l) or right (or r)")
            return

        if index is None or index < 0 or index >= len(player.inventory):
            await ctx.send(f"Invalid item index. See `{game.prefix}inventory` for a list of your items.")
            return

        item = player.inventory.get_by_index(index)
        if not isinstance(item, Weapon):
            await ctx.send(f"That item cannot be equipped.")
            return

        if hand.lower()[0] == 'l':
            player.equip_left(item)
        else:
            player.equip_right(item)
        player.save()
        await ctx.send(f"You have equipped {item.article} {item.name}.")

    @command(name='inventory', aliases=['inv', 'items', 'bag'],
             brief='Sends a DM to the player with information about the items they carry.')
    @cooldown(1, 10, BucketType.member)
    async def inventory(self, ctx, game_idx: int = None):
        """Sends a DM to the player with information about the items they carry.

        (10-second cool-down)"""
        game: Game = await self.get_game(ctx, game_idx)
        if game is None:
            print("Game was none.")
            return

        player: Player = await self.get_player(ctx, game)
        if player is None:
            print("Players was none.")
            return

        await player.send(player.getInventory(game.guild.name))
        if ctx.guild is not None:
            await ctx.message.delete()

    @command(name='item', brief='Sends the player a DM with info regarding the specified item.')
    @cooldown(1, 2, BucketType.member)
    async def item(self, ctx, index: int, game_idx: int = None):
        game: Game = await self.get_game(ctx, game_idx)
        if game is None:
            return

        player = await self.get_player(ctx, game)
        if player is None:
            return

        if 0 <= index < len(player.inventory):
            embed, file = player.inventory.get_by_index(index).get_embed()
            await ctx.send(embed=embed, file=file)
        else:
            await ctx.send(f"I'm afraid you don't have that, {player.name}")

    @item.error
    async def item_err(self, ctx, error):
        if isinstance(error, MissingRequiredArgument):
            embed = Embed(
                title=f'Item help',
                description=f"The item's index is required. To find the index, check `{ctx.prefix}inventory`",
                color=0xff0000
            )
            await ctx.author.send(embed=embed)

    # Returns a string to display games in which a user is currently playing.
    @cooldown(1, 60, BucketType.user)
    @command(name='games',
             brief='Sends a DM to the calling player with a list of each game they are currently in for Caldanai Bot.')
    async def games_display(self, ctx):
        msg = ""
        games = self.get_games_for_user(ctx.author.id)
        for idx, game in enumerate(games):
            msg += f'{idx}: {game.guild.name}\n'

        await ctx.author.send(f'```js\n{msg}```' if len(msg) > 0 else "You are not playing any games.")
        if ctx.guild is not None:
            await ctx.message.delete()

    # Sells an item
    @cooldown(1, 5, BucketType.member)
    @command(name='sell', brief='Sells an item.')
    async def sell(self, ctx, index: int = None, gid: int = None):
        game: Game = await self.get_game(ctx, gid)
        if game is None:
            return

        player = await self.get_player(ctx, game)
        if player is None:
            return

        if index is None:
            await ctx.send("You must specify the item index to sell.")
            return

        if 0 <= index < len(player.inventory):
            item = player.inventory.get_by_index(index)
            player.inventory.remove(item)
            player.clarks += item.value
            player.save()
            await player.send(f"You sold {item.article} {item.rarity.name} {item.name} for {item.value} clarks.")
        else:
            await ctx.send(f"I'm afraid you don't have that, {player.name}")

    @Cog.listener()
    async def on_ready(self):
        print("RPG Cog ready.")


def setup(bot):
    bot.add_cog(RPG(bot))
