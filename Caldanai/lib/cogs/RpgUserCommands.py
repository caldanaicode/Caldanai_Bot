import math
from random import choice

from discord.ext.commands import Cog, command, cooldown, BucketType, guild_only, group
from typing import Optional

from Caldanai.Dispatcher import Dispatcher
from Caldanai.Logger import stdout
from Caldanai.lib.cogs.RpgUtilities import RpgUtilities
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg import Game, Roles
from Caldanai.lib.rpg.creatures.player import Player
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.parser import parse
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
		Adds a member to the RPG system as a player if they do not already exist in the database. This can only be called by the member trying to participate.
		"""

		game: Game = await self.utils().get_game(ctx)
		if game is None:
			return

		player = await self.utils().get_player(ctx, game, False)
		if player is None:
			joined = datetime.now()
			player = Player(gid=ctx.guild.id, uid=ctx.author.id, joined=joined, last_active=joined)
			player.member = ctx.author
			player.name = ctx.author.display_name
			player.is_dirty = True
			game.players[ctx.author.id] = player
			Dispatcher.add(game.channel, f'Welcome, {ctx.author.display_name}')
			if Roles.ALL in game.roles.keys() and Roles.ACTIVE in game.roles.keys():
				await player.member.add_roles([game.roles[Roles.ALL], game.roles[Roles.ACTIVE]], "Player joined game.")

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
			if Roles.ALL in game.roles.keys() and Roles.ACTIVE in game.roles.keys() and Roles.INACTIVE in game.roles.keys():
				await player.member.remove_roles(
					[game.roles[Roles.ALL], game.roles[Roles.ACTIVE], game.roles[Roles.INACTIVE]],
					'Player left game.'
				)
			MongoDB.players.delete_one({'guild_id': ctx.guild.id, 'user_id': ctx.author.id})
			del game.players[ctx.author.id]
			game.save()
			Dispatcher.add(game.channel, f'You have been removed from the game, {ctx.author.display_name}!')

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

	@command(name='hug', aliases=['snuggle', 'cuddle'], brief='Hugs, snuggles, and cuddles for all of your needs!')
	@guild_only()
	@cooldown(1, 5, BucketType.member)
	async def hug(self, ctx, *, msg: str = None):
		"""
		Hugs, snuggles, and cuddles for all of your needs!

		See that monster over there?! It's just angry because it never feels loved!
		Want to show your fellows a little appreciation? There's a hug for them too!

		(5-second cool-down)

		:param msg: A message to include with the hug. This can be a target such as a monster's noun, or an @mention of another player. It can also simply be text in the form of a custom emote, but remember to type in the third-person present participle for best effect.
		"""
		game, player = await self.utils().get_game_and_player(ctx)
		if game is None or player is None:
			return

		if player.is_dead():
			Dispatcher.add(game.channel, f"A lonely sigh slips from the corpse of {player.name}.")

		elif ctx.message.mentions is not None and len(ctx.message.mentions) > 0:
			target = await self.utils().get_player(ctx.message.mentions[0])

			if target is not None:
				Dispatcher.add(game.channel, parse(target.on_hugged(player, ctx.invoked_with), target, player))

		elif msg is not None and len(msg) > 0:
			if game.monster is not None and game.monster.name.lower() in msg.lower():
				if game.monster.on_hugged:
					Dispatcher.add(
						game.channel,
						parse(game.monster.on_hugged(player, ctx.invoked_with), game.monster, player)
					)
			else:
				Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s {msg}*")

		else:
			Dispatcher.add(game.channel, f"*{player.name} {ctx.invoked_with}s the air awkwardly.*")

	@cooldown(1, 5, BucketType.member)
	@guild_only()
	@command(name='haunt', brief='Allows the dead to harass the less-dead.')
	async def haunt(self, ctx, target: str = None):
		"""
		Allows the dead to harass the less-dead. When specifying a target, use the @ symbol to target another player.

		(5-second cool-down)

		:param target: An optional victim of your haunting; either a player using @mentions, or the name of the current monster.
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
				if p != player and p.health < p.get_health_max():
					msg += f"\n@{index}'s skin glows softly under the touch of the rain. "
					heal_msg = p.apply_damage(p.health - p.get_health_max())
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

			missing_health = heal_target.get_health_max() - heal_target.health
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

	@Cog.listener()
	async def on_ready(self):
		stdout("RpgUserCommands ready.")


def setup(bot):
	bot.add_cog(RpgUserCommands(bot))
