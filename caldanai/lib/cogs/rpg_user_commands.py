import math
from random import choice, randint

from discord import File, TextChannel
from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group, Context

from caldanai.dispatcher import Dispatcher
from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.utils import RpgUtilities, generate_report
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg import Game
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.parser import parse


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
    async def attack(self, ctx: Context, *, target: str = None):
        """
        Attacks the critter currently daring to show its face to intrepid adventurers!
        Optionally specify a body part to target, e.g. ``$kill arm.left``
        or ``$kill goblin arm.left``. If already in combat, re-calling
        ``$kill <part>`` updates the target without re-joining.

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

        already_in_combat = player in game.combatants

        # Parse explicit body-part targets from the command arguments.
        # Supports one target (all sources hit it) or multiple (one per source).
        part_targets = self._parse_part_targets(target, game.monster)

        # Warn if the player typed something but nothing resolved.
        if target and target.strip() and not part_targets and game.monster.body_parts:
            Dispatcher.add(
                game.channel,
                f"No targetable part matching '{target.strip()}' found. Attacking randomly.",
            )

        if already_in_combat:
            game.combat_targets[player.user_id] = part_targets or None
            if part_targets:
                label = self._display_targets(part_targets)
                Dispatcher.add(game.channel, f"{player.name} shifts focus to {label}!")
            else:
                Dispatcher.add(game.channel, f"{player.name} attacks wildly!")
            return

        game.combatants.append(player)
        game.combat_targets[player.user_id] = part_targets or None

        if part_targets:
            label = self._display_targets(part_targets)
            Dispatcher.add(game.channel, f"{player.name} prepares to attack, targeting {label}!")
        else:
            Dispatcher.add(game.channel, f"{player.name} prepares to attack!")

    def _parse_part_targets(self, target_str, monster):
        """Parse body-part names from the player's command input.

        Returns a list of matched part-name strings (may be empty).
        Accepts: ``"arm.left"``, ``"arm.left leg.right"``,
        ``"goblin arm.left"`` (unrecognized tokens like the monster
        name are silently skipped).
        """
        if not target_str or not monster.body_parts:
            return []

        seen = set()
        matched = []
        for token in target_str.strip().split():
            if token in seen:
                continue
            exact = monster.get_part(token)
            if exact:
                seen.add(token)
                matched.append(token)
                continue
            prefix_matches = [
                p for p in monster.get_targetable_parts()
                if p.name.startswith(token + ".") or p.name == token
            ]
            if prefix_matches:
                seen.add(token)
                matched.append(token)
        return matched

    @command(name="target", aliases=["aim", "focus"], brief="Changes your attack target to specific body parts.")
    @guild_only()
    async def target_part(self, ctx: Context, *, part: str = None):
        """
        Changes your attack focus mid-combat.
        Use ``$target arm.left`` to focus all weapons on one part,
        ``$target arm.left leg.right`` to split (one per weapon), or
        ``$target`` alone to clear targeting and attack randomly.
        """
        game, player = await RpgUtilities.get_game_and_player(ctx)

        if game is None or player is None:
            return

        if player not in game.combatants:
            Dispatcher.add(game.channel, f"{player.name} is not in combat. Use $kill to join!")
            return

        if game.monster is None:
            Dispatcher.add(game.channel, "There's nothing to target!")
            return

        if not part or not part.strip():
            game.combat_targets[player.user_id] = None
            Dispatcher.add(game.channel, f"{player.name} clears targeting — attacking randomly.")
            return

        part_targets = self._parse_part_targets(part, game.monster)

        if not part_targets:
            Dispatcher.add(
                game.channel,
                f"No targetable part matching '{part.strip()}' found on the {game.monster.name}.",
            )
            return

        game.combat_targets[player.user_id] = part_targets
        label = self._display_targets(part_targets)
        Dispatcher.add(game.channel, f"{player.name} shifts focus to {label}!")

    @staticmethod
    def _display_part_name(codified: str, with_article: bool = False) -> str:
        """Convert a codified part name to a readable display name.

        ``"arm.left"`` → ``"left arm"``, ``"head.2"`` → ``"head 2"``,
        ``"head"`` → ``"head"``.

        When ``with_article`` is True, prepends "the" for directional
        and simple names but NOT for numbered parts:
        ``"the left arm"`` vs ``"head 2"`` (not "the head 2").
        """
        if "." not in codified:
            name = codified
            use_the = True
        else:
            base, qualifier = codified.rsplit(".", 1)
            if qualifier.isnumeric():
                name = f"{base} {qualifier}"
                use_the = False
            else:
                name = f"{qualifier} {base}"
                use_the = True

        if with_article and use_the:
            return f"the {name}"
        return name

    @classmethod
    def _display_targets(cls, part_targets: list) -> str:
        """Join a list of codified part names into a readable label
        with appropriate articles.

        ``["arm.left", "leg.right"]`` → ``"the left arm and the right leg"``
        ``["head.2", "torso"]`` → ``"head 2 and the torso"``
        """
        return " and ".join(
            cls._display_part_name(t, with_article=True) for t in part_targets
        )

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

            # Monster takes priority if its name matches the mentioned player
            mention = ctx.message.mentions[0]
            if (
                game.monster is not None
                and game.monster.on_hugged
                and game.monster.name.lower() == mention.display_name.lower()
            ):
                Dispatcher.add(
                    game.channel, parse(game.monster.on_hugged(player, ctx.invoked_with), game.monster, player)
                )
            elif (target := await RpgUtilities.get_player(mention, game=game, notify=False)) is not None:
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
                haunted = await RpgUtilities.get_player(ctx.message.mentions[0], game=game, notify=False)
            elif game.monster is not None and game.monster.name == target.lower():
                haunted = game.monster

            if haunted is None or not isinstance(haunted, Creature):
                await self.haunt(ctx)
                return

            if haunted.is_dead():
                msgs = [
                    f"The spirit of @1 attempts to bond with that of @2, but a slight burst of pressure repels @1o.",
                    f"@1np shade investigates the remains of @2.",
                    f"As @1np ghostly form approaches the remains of @2, @1 flickers rapidly before suddenly "
                    f"teleporting back to @1a own corpse.",
                ]

            else:
                msgs = [
                    f"{'The ' if not isinstance(haunted, Player) else ''}@2 glances around the area suspiciously as @2s "
                    f"@2v(senses|sense) the unearthly presence of @1.",
                    f"Soft laughter echoes in {'the ' if not isinstance(haunted, Player) else ''}@2np ears as @1np spirit toys with @2o.",
                    f"{'The ' if not isinstance(haunted, Player) else ''}@2np breath suddenly catches as @1np shade wisps through @2o.",
                ]

        else:
            msgs = [
                f"The ghostly presence of @1 floods into the area briefly before ebbing away.",
                f"A sudden chill blankets the area as @1np spirit wafts through.",
                f"@1np forlorn lament brings with it a cold, solemn feeling.",
            ]

        if player.is_dead():
            if haunted and isinstance(haunted, Player) and haunted.member == player.member:
                msg = f"@1np spirit tries to fuse back into @1a body, but merely passes right through it."
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
                    "A sense of dread settles over @1np shade, and @1s @1v(cries|cry) out forlornly.",
                ]
            )
            Dispatcher.add(game.channel, parse(msg, player))
            return

        msgs = [
            "@1 offers a solemn prayer, seeking forgiveness and humility.",
            "@1 seeks the guidance of the Divine.",
            "@1 falls to @1a knees in reverence, face lifted to the sky as @1s @1v(basks|bask) in a divine embrace.",
            "@1np eyes turn skyward as @1s @1v(entreats|entreat) the Divine for benevolence.",
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
                if p == player:
                    continue
                # "Needs healing" includes part injuries — a player
                # with a destroyed arm but full body HP should still
                # be caught in the rain.
                body_hurt = p.health < p.get_health_max()
                part_hurt = any(
                    part.health < part.health_max
                    for part in (p.body_parts or [])
                )
                if not (body_hurt or part_hurt):
                    continue
                msg += f"\n@{index}'s skin glows softly under the touch of the rain. "
                if body_hurt:
                    heal_msg = p.apply_damage(p.health - p.get_health_max())
                    if heal_msg:
                        msg += f"{heal_msg} "
                # Divine rain is total: restore every body part too.
                for part in p.body_parts or []:
                    part.health = part.health_max
                p.health_regen = 0
                p.is_dirty = True
                msg += f"@{index} is made whole!"
                actors.append(p)
                index += 1

            if player in game.combatants:
                game.combatants.remove(player)

        elif d20.value > 16:
            # Candidate filter includes part-injured players, not
            # just body-HP-injured ones.
            def _needs_healing(p) -> bool:
                return (
                    p.health < p.get_health_max()
                    or any(
                        part.health < part.health_max
                        for part in (p.body_parts or [])
                    )
                )

            candidates = [
                p for p in game.player_manager.players.values()
                if _needs_healing(p)
            ] or [player]
            # Pick the most-injured by body-HP ratio; if everyone has
            # full body HP but some have part injuries, pick by
            # part-injury count as a tiebreaker.
            heal_target: Player = min(
                candidates,
                key=lambda p: (
                    p.get_health_scale(),
                    -sum(
                        1 for part in (p.body_parts or [])
                        if part.health < part.health_max
                    ),
                ),
            )
            actors.append(heal_target)
            index = len(actors)

            if d20.value == 20:
                # Divine miracle: full body + full parts restore.
                body_heal_msg = ""
                if heal_target.health < heal_target.get_health_max():
                    body_heal_msg = heal_target.apply_damage(
                        -heal_target.get_health_max()
                    )
                for part in heal_target.body_parts or []:
                    part.health = part.health_max
                heal_target.health_regen = 0
                heal_target.is_dirty = True
                if body_heal_msg:
                    msg += f"\n{body_heal_msg}"
                msg += (
                    f"\nA radiant column of light engulfs @{index}; "
                    f"wounds seal and broken flesh knits whole in moments."
                )
            else:
                # 17–19: computed body heal + fully restore ONE most-
                # injured part (triage). Keeps nat 20 distinct as the
                # "everything fixed" outcome.
                missing_health = heal_target.get_health_max() - heal_target.health
                quarter = math.ceil(missing_health / 4) if missing_health else 0

                if quarter > 1:
                    heal_amount = Dice.quick_roll(f"1d{quarter}") + quarter * (d20.value % 17)
                elif missing_health == 1:
                    heal_amount = 1
                elif missing_health > 0:
                    heal_amount = Dice.quick_roll(f"1d{missing_health}")
                else:
                    heal_amount = 0

                heal_amount = heal_amount or 0
                body_heal_msg = heal_target.apply_damage(-heal_amount) if heal_amount else ""

                if body_heal_msg:
                    msg += f"\n{body_heal_msg}"

                msg += f"\nA warm light suffuses @{index}, "

                if heal_amount > 0 and missing_health > 0:
                    msg += f"imbuing @{index}o with {heal_amount} points of health!"
                else:
                    msg += f"and a pleasant tingle envelops @{index}o without noticeable effect."

                # One part restored. Triage by fractional HP so the
                # worst off (typically destroyed) gets priority.
                injured_parts = [
                    part for part in (heal_target.body_parts or [])
                    if part.health < part.health_max
                ]
                if injured_parts:
                    worst = min(
                        injured_parts, key=lambda p: p.health / p.health_max,
                    )
                    worst.health = worst.health_max
                    heal_target.is_dirty = True
                    msg += (
                        f"\n@{index}'s {worst.display_name} knits itself whole."
                    )

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
