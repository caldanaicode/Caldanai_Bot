import math
from random import choice, randint

from discord import File, TextChannel
from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group, Context

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import get_logger
from Caldanai.lib.rpg.helpers.utils import RpgUtilities, generate_report
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg import Game
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.parser import parse


_log = get_logger(__name__)


class RpgUserCommands(Cog):
    def __init__(self, bot):
        self.bot = bot

    @group(brief="Groups together various game commands for players.")
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def game(self, ctx: Context):
        """
        Requires a subcommand.

        (10-second cool-down)
        """

        if ctx.invoked_subcommand is None:
            Dispatcher.add(ctx, "This command cannot be used on its own.")
            return

    @guild_only()
    @game.command(brief="Adds a player to the RPG system.")
    async def join(self, ctx: Context):
        """
        Adds a member to the RPG system as a player if they do not already exist in the database. This can only be called by the member trying to participate.
        """

        game: Game = await RpgUtilities.get_game(ctx)
        if game is None:
            return

        if await game.player_manager.add_player(ctx):
            Dispatcher.add(game.channel, f"Welcome, {ctx.author.display_name}")

        else:
            Dispatcher.add(game.channel, f"You are already a player in this RPG, {ctx.author.display_name}!")

    @guild_only()
    @game.command(name="leave", brief="Removes the player from the RPG system.")
    async def leave(self, ctx: Context, gid: int = None):
        """
        Removes an existing player from the game. This can only be called by member withdrawing from participation.
        """

        game, player = await RpgUtilities.get_game_and_player(ctx, gid)

        if game is None or player is None:
            return

        await game.player_manager.remove_player(ctx.author.id, game.guild.id)
        game.save()
        Dispatcher.add(game.channel, f"You have been removed from the game, {ctx.author.display_name}!")

    @command(
        name="attack",
        aliases=[
            "annihilate",
            "kill",
            "murder",
            "destroy",
            "obliterate",
            "slaughter",
            "slay",
            "rip&tear",
            "ripandtear",
            "ripampersandtear",
        ],
        brief="Attacks the critter currently daring to show it's face to intrepid adventurers!",
    )
    @guild_only()
    @cooldown(1, 10, BucketType.member)
    async def attack(self, ctx: Context):
        """
        Attacks the critter currently daring to show its face to intrepid adventurers!

        (10-second cool-down)
        """

        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if game.monster is None:
            Dispatcher.add(game.channel, "You see nothing to attack!")
            return

        if player.is_dead():
            Dispatcher.add(game.channel, f"A ghostly moan escapes the corpse of {player.name}.")
            return

        if any(player.id == p.id for p in game.combatants):
            Dispatcher.add(game.channel, f"But {ctx.author.display_name}, you are already attacking!")
            return

        game.combatants.append(player)
        Dispatcher.add(game.channel, f"{player.name} prepares to attack!")

    @command(name="hug", aliases=["snuggle", "cuddle"], brief="Hugs, snuggles, and cuddles for all of your needs!")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def hug(self, ctx: Context, *, msg: str = None):
        """
        Hugs, snuggles, and cuddles for all of your needs!

        See that monster over there?! It's just angry because it never feels loved!
        Want to show your fellows a little appreciation? There's a hug for them too!

        (5-second cool-down)

        :param msg: A message to include with the hug. This can be a target such as a monster's noun, or a @mention of another player. It can also simply be text in the form of a custom emote, but remember to type in the third-person present participle for best effect.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        if game is None or player is None:
            return

        if player.is_dead():
            Dispatcher.add(game.channel, f"A lonely sigh slips from the corpse of {player.name}.")

        elif ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
            if self.bot.user in ctx.message.mentions:
                responses = [
                    "Get your filthy paws off me, you damned dirty ape!",
                    "You cannot hug me, for I exist only in the ether.",
                    "One does not simply hug the AI, mortal.",
                ]
                if (c := randint(0, 3)) == 3:
                    file = File(f"./site/static/images/hal9000.gif", filename="hal9000.gif")
                    Dispatcher.add(game.channel, file=file)
                else:
                    Dispatcher.add(game.channel, responses[c])
                return

            target = await RpgUtilities.get_player(ctx.message.mentions[0])

            if target is not None:
                Dispatcher.add(game.channel, parse(target.on_hugged(player, ctx.invoked_with), target, player))

        elif msg is not None and len(msg) > 0:
            if game.monster is not None and game.monster.name.lower() in msg.lower():
                if game.monster.on_hugged:
                    Dispatcher.add(
                        game.channel, parse(game.monster.on_hugged(player, ctx.invoked_with), game.monster, player)
                    )
            else:
                Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s {msg}*")

        else:
            Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s the air awkwardly.*")

    @cooldown(1, 5, BucketType.member)
    @guild_only()
    @command(name="haunt", brief="Allows the dead to harass the less-dead.")
    async def haunt(self, ctx: Context, target: str = None):
        """
        Allows the dead to harass the less-dead. When specifying a target, use the @ symbol to target another player.

        (5-second cool-down)

        :param target: An optional victim of your haunting; either a player using @mentions, or the name of the current monster.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)
        haunted = None

        if game is None or player is None:
            return

        msgs = []

        if target is not None:
            if ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
                if self.bot.user in ctx.message.mentions:
                    Dispatcher.add(game.channel, parse("You cannot haunt a figment of your imagination, @1.", player))
                    return
                haunted = await RpgUtilities.get_player(ctx.message.mentions[0])
            elif game.monster is not None and game.monster.name == target.lower():
                haunted = game.monster

            if haunted is None or not isinstance(haunted, Creature):
                await self.haunt(ctx)
                return

            if haunted.is_dead():
                msgs = [
                    f"The spirit of @1 attempts to bond with that of @2, but a slight burst of pressure repels @1o.",
                    f"@1's shade investigates the remains of @2.",
                    f"As @1's ghostly form approaches the remains of @2, @1 flickers rapidly before suddenly "
                    f"teleporting back to @1a own corpse.",
                ]

            else:
                msgs = [
                    f"{'The ' if not isinstance(haunted, Player) else ''}@2 glances around the area suspiciously as @2s "
                    f"senses the unearthly presence of @1.",
                    f"Soft laughter echoes in {'the ' if not isinstance(haunted, Player) else ''}@2's ears as @1's spirit toys with @2o.",
                    f"{'The ' if not isinstance(haunted, Player) else ''}@2's breath suddenly catches as @1's shade wisps through @2o.",
                ]

        else:
            msgs = [
                f"The ghostly presence of @1 floods into the area briefly before ebbing away.",
                f"A sudden chill blankets the area as @1's spirit wafts through.",
                f"@1's forlorn lament brings with it a cold, solemn feeling.",
            ]

        if player.is_dead():
            if haunted and isinstance(haunted, Player) and haunted.member == player.member:
                msg = f"@1's spirit tries to fuse back into @1a body, but merely passes right through it."
            else:
                msg = choice(msgs)
        else:
            msg = f"@1 pretends to float around, making supposedly ghostly noises, but it's not very effective."

        Dispatcher.add(game.channel, parse(msg, player, haunted))

    @cooldown(1, 60, BucketType.member)
    @command(name="pray", aliases=["meditate", "reflect"], brief="Beseeches heavenly blessings.")
    async def pray(self, ctx: Context):
        """
        Beseeches heavenly blessings. Occasionally, prayers may be answered...

        (60-second cool-down)
        """

        if ctx.guild is None:
            Dispatcher.add(ctx, f"I see you're interested in a little private reflection...")
            return

        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if player.is_dead():
            msg = choice(
                [
                    "Posthumous piety profits particularly poorly, @1.",
                    "Your prayers can no longer pierce the planes of piety, @1.",
                    "It seems, @1, that if anyone is listening, they no longer care...",
                    "The power of prayer eludes the dead, @1.",
                    "Hideous cackling erupts from unseen places as the spirit of @1 seeks salvation.",
                    "A sense of dread settles over @1's shade, and @1s cries out forlornly.",
                ]
            )
            Dispatcher.add(game.channel, parse(msg, player))
            return

        msgs = [
            "@1 offers a solemn prayer, seeking forgiveness and humility.",
            "@1 seeks the guidance of the Divine.",
            "@1 falls to @1a knees in reverence, face lifted to the sky as @1s basks in a divine embrace.",
            "@1's eyes turn skyward as @1s entreats the Divine for benevolence.",
            "@1 proffers words of hope, attempting to sooth the splintered souls of comrades.",
        ]

        msg = choice(msgs)
        d20 = Dice.d20()
        msg += f" (1d{d20.sides} = {d20.value})"
        player.update_roll_count(d20.sides, d20.value)
        heal_amount = 0
        actors = [
            player,
        ]
        if d20.value == 1:
            msg += (
                "\nSacrifice is demanded for your insolence, @1!\n\nA sudden storm explodes into the area, "
                "as a blinding bolt of lightning envelopes @1. When the light fades, nothing remains but a charred husk."
            )

            msg += f"\n\n{player.apply_damage(player.health)}\n\nThe storm calms to a gentle rain..."

            index = 2
            for p in game.player_manager.players.values():
                if p != player and p.health < p.get_health_max():
                    msg += f"\n@{index}'s skin glows softly under the touch of the rain. "
                    heal_msg = p.apply_damage(p.health - p.get_health_max())
                    if heal_msg:
                        msg += f"{heal_msg} "
                    msg += f"@{index}'s health is completely restored!"
                    actors.append(p)
                    index += 1

            if player in game.combatants:
                game.combatants.remove(player)

        elif d20.value > 16:
            heal_target: Player = min(
                list(filter(lambda p: p.health < p.get_health_max(), game.player_manager.players.values())) or [player],
                key=lambda p: p.health,
            )

            missing_health = heal_target.get_health_max() - heal_target.health
            actors.append(heal_target)
            index = len(actors)
            quarter = math.ceil(missing_health / 4)

            if quarter > 1:
                heal_amount = Dice.quick_roll(f"1d{quarter}") + quarter * (d20.value % 17)
            elif missing_health == 1:
                heal_amount = 1
            else:
                heal_amount = Dice.quick_roll(f"1d{missing_health}")

            heal_amount = heal_amount or 0
            heal_msg = heal_target.apply_damage(-heal_amount)

            if heal_msg:
                msg += f"\n{heal_msg}"

            msg += f"\nA warm light suffuses @{index}, "

            if heal_amount > 0 and missing_health > 0:
                msg += f"imbuing @{index}o with {heal_amount} points of health!"
            else:
                msg += f"and a pleasant tingle envelops @{index}o without noticeable effect."

        Dispatcher.add(game.channel, parse(msg, *actors))

    @cooldown(1, 60, BucketType.user)
    @command(aliases=["report"], brief="Reports an error or issue to the logs and developer.")
    async def report_problem(self, ctx: Context, *, msg: str):
        """
        Reports an error or issue to the logs and developer. 1-minute cooldown.

        :param msg: A description of the problem with as much detail as possible.
        :return:
        """
        game, player = await RpgUtilities.get_game_and_player(ctx, notify=False)

        result = generate_report(
            ctx.author.id,
            ctx.author.display_name,
            msg,
            player.name if player else "None",
            ctx.guild.id if ctx.guild else "None",
            ctx.channel.id if ctx.channel else "None",
        )

        m = f"{ctx.author.display_name}, "
        if result:
            m += "your message has been logged and relayed. Thank you for helping improve me!"
        else:
            m += "there was an unexpected error while delivering your report. Please ping the developer!"

        Dispatcher.add(ctx, m)

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgUserCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgUserCommands(bot))
