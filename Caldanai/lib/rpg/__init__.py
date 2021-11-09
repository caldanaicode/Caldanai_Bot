import random

from discord.ext.commands import Bot
from discord.ext import tasks
from discord import Guild, TextChannel
from typing import Dict, List, Union, Optional

from .creatures import Creature
from .creatures.player import Player
from random import choice, randint
from asyncio import sleep

from .helpers import get_random_direction, get_random_monster
from .inventory.items import Item
from .inventory.weapons import Weapon
from .time.GameClock import GameClock
from ...Dispatcher import Dispatcher
from ...Logger import stdout
from ...db import MongoDB


class Game:
	"""
	Structure for game information.

	Attributes
	----------
	channel: discord.TextChannel
		The TextChannel to which this game sends public responses.
	players : Dict[int, Player]
		The dictionary mapping of user ID to Player mappings.
	monster : Monster
		The current monster spawned.
	combatants : List[int]
		The list of players attacking the current monster.
	loot : Dict[int, List[Union[Item, Weapon]]
		The list of loot from the current monster.
	use_spawn_timer : bool
		Whether or not to spawn monsters using the timer.
	spawn_duration : int
		Combat duration in minutes
	loot_duration : int
		Loot duration in minutes
	loot_countdown : int
		Current loot timer counter
	trigger : int
		Trigger chance for monster spawn
	minutes_max : int
		Maximum minutes between monster spawns
	minutes_min : int
		Minimum minutes between monster spawns
	prefix : str
		The prefix used by the bot for this game
	use_ambiance : bool
		Whether or not to display ambiance messages such as weather, day/night cycles, and monster ambiance messages
	:param channel:
	"""

	def __init__(
			self,
			bot: Bot = None,
			game_id: str = None,
			guild: Guild = None,
			channel: TextChannel = None,
			use_spawn_timer: bool = True,
			spawn_max: int = 60,
			spawn_min: int = 10,
			spawn_duration: int = 10,
			loot_duration: int = 5,
			prefix: str = None,
			use_ambiance: bool = True,
			time: int = 0
	):
		"""
		:param bot: discord.ext.commands.Bot -- The bot that owns this game.
		:param game_id: int -- The game's database ID.
		:param guild: The Discord Guild (a.k.a server) that hosts this game.
		:param channel: The Discord TextChannel to which this game sends responds.
		:param use_spawn_timer: bool -- Whether or not to allow periodic monster spawns.
		:param spawn_max: int -- Maximum minutes between monster spawns.
		:param spawn_min: int -- Minimum minutes between monster spawns.
		:param spawn_duration: int -- Number of minutes before first combat triggers.
		:param loot_duration: int -- Number of minutes before loot expires.
		:param prefix: str -- The game's command prefix.
		:param use_ambiance: bool -- Whether or not to display ambiance messages such as weather, day/night cycles,
		and monster ambiance messages.
		:param time: int -- The game's internal time value.
		"""
		self.bot = bot
		self.id = game_id
		self.guild = guild
		self.channel = channel
		self.players: Dict[int, Player] = {}
		self.monster: Optional[Creature] = None
		self.monsters: List[str] = []
		self.combatants: List[int] = []
		self.looters: List[int] = []
		self.loot: Dict[int, List[Union[Item, Weapon]]] = {}
		self.use_spawn_timer = use_spawn_timer
		self.spawn_duration = spawn_duration
		self.loot_duration = loot_duration
		self.loot_countdown = loot_duration * 60
		self.trigger = randint(spawn_min, spawn_max)
		self.minutes_max = spawn_max
		self.minutes_min = spawn_min
		self.prefix = prefix
		self.use_ambiance = use_ambiance
		self.game_clock = GameClock(time)

		self.game_clock.tick.start()
		self.spawn_cooldown = 0
		self.stage = 0
		self.weather = None

		self.last_tick_game_time = self.game_clock.get_hours()

		if use_spawn_timer:
			self.spawn_check.start()
		if use_ambiance:
			self.do_ambiance.start()

	def cancel_combat(self):
		"""Clears the current monster, combatants, and loot."""

		self.monster = None
		self.combatants.clear()
		self.loot.clear()
		self.looters.clear()
		self.spawn_cooldown = self.minutes_min
		self.stage = 3

	# Cleans up any loot that wasn't picked up
	@tasks.loop(seconds=1)
	async def loot_expires(self):
		"""Cleans up uncollected loot and restarts spawning after loot expiration and minimum spawn time."""

		if len(self.loot) > 0 and self.loot_countdown > 0:
			self.loot_countdown -= 1
			return

		self.loot_expires.stop()

		if any([len(loot) for loot in self.loot.values()]) > 0:
			Dispatcher.add(
				self.channel,
				"A swarm of tiny, shadow-clad creatures floods in and makes off with the items on the ground."
			)
		self.loot.clear()
		self.loot_countdown = self.loot_duration * 60
		self.spawn_cooldown = self.minutes_min
		self.stage = 3

	def on_monster_death(self) -> str:
		"""Generates loot, shows monster death, and clears combatants."""

		has_loot = False
		for pid in self.looters:
			loot = self.monster.get_loot()
			if len(loot) > 0:
				has_loot = True
			self.loot[pid] = loot

		self.monster = None
		self.combatants.clear()
		self.looters.clear()
		if has_loot:
			return f"\nThere might be something to `{self.prefix}loot`..."
		else:
			return "\nThere does not appear to be anything to loot, this time."

	def health_regen(self) -> str:
		"""
		Applies health regen to players, and increments the health regen amount.

		:return: A string with messages regarding player health, if any.
		"""
		msg = ""
		for player in self.players.values():
			m = player.apply_damage(-player.health_regen)
			if m:
				msg += f"\n{m}"
			player.health_regen = (player.health_regen + 1) if player.health < player.health_max else 0

		return msg

	def get_monster(self):
		self.monster = get_random_monster()
		embed, file = self.monster.get_embed()
		Dispatcher.add(self.channel, self.monster.arrival, embed=embed, file=file)

	def attack_random_combatant(self) -> str:
		victim = self.players[choice(self.combatants)]
		m, d = self.monster.do_attack(victim)
		if d > 0:
			m += victim.apply_damage(d)
		return m

	@tasks.loop(count=1)
	async def do_combat(self):
		"""Awaits the combat duration, and tallies and displays combat damage."""

		if self.monster is None:
			stdout(f"Combat unable to start on `{self.guild.name}` because no monster was generated.")
			return

		self.stage = 1
		self.trigger = self.minutes_min

		await sleep(self.spawn_duration * 30)

		while self.monster is not None:
			await sleep(self.spawn_duration * 30)

			msg = ""
			damage = 0
			for pid in self.combatants:
				player = self.players[pid]
				player.health_regen = 0
				if not player.is_dead():
					if pid not in self.looters:
						self.looters.append(pid)
					m, d = player.do_attack(self.monster)
					msg += m
					damage += d

			msg += f"Total damage done vs Health:\n\u2800\u2800\u2800\u2800{damage:,} vs {self.monster.health:,} " \
				   f"= **{max(self.monster.health - damage, 0)} health remaining.**\n"

			msg += self.monster.apply_damage(damage)
			if self.monster.is_dead():
				msg += self.on_monster_death()
				msgs = Dispatcher.split_message(msg, '```\n', True)
				for m in msgs:
					Dispatcher.add(self.channel, m)
				self.loot_expires.start()

			else:
				if self.monster.aggression in ("rampage", "vengeful") and len(self.combatants) > 0:
					msg += f"\n{self.attack_random_combatant()}"
					if self.monster.aggression == "rampage":
						Dispatcher.add(self.channel, f"{msg}\n**The {self.monster.name} seems enraged!**")
						self.combatants.clear()
						continue

				if self.monster.aggression in ("vengeful", "neutral") or len(self.combatants) == 0:
					Dispatcher.add(self.channel, f"{msg}\n{self.monster.escape}")
					self.cancel_combat()

		msg = self.health_regen()
		if msg:
			Dispatcher.add(self.channel, msg)

	@tasks.loop(minutes=1)
	async def spawn_check(self):
		"""Determines whether or not to randomly spawn a monster."""

		if not self.use_spawn_timer:
			stdout("Spawn loop ending...")
			self.spawn_check.stop()
			return

		if self.bot.is_ws_ratelimited():
			stdout("Spawning blocked due to rate limit.")
			return

		if self.stage == 3:
			self.spawn_cooldown -= 1
			self.stage = 0 if self.spawn_cooldown <= 0 else 3
			return

		if self.stage != 0:
			return

		self.trigger = min(self.trigger, self.minutes_max)
		r = randint(self.trigger, self.minutes_max)
		if r == self.minutes_max:
			self.get_monster()
			self.do_combat.start()
			return

		self.trigger += 1
		return

	def kill_monster(self):
		"""Cancels combat and forces monster death."""

		self.do_combat.cancel()
		msg = self.on_monster_death()
		self.loot_expires.start()
		if len(msg) > 0:
			Dispatcher.add(self.channel, msg)

	@tasks.loop(minutes=1)
	async def do_ambiance(self):
		"""Picks an ambiance message to display."""

		if not self.use_ambiance:
			return

		game_time = self.game_clock.get_hours()

		msg = ""

		sunrise, sunset = self.game_clock.get_sunrise_and_sunset()

		if self.last_tick_game_time < sunrise.get_hours() <= game_time:
			msg = "The sky glows softly to the east as night gives way to day."
		elif self.last_tick_game_time < sunset.get_hours() <= game_time:
			msg = "The crimson disc sinks slowly beyond the horizon, and darkness creeps across the land."

		if random.randint(1, 100) > 98:
			msg += choice([
				"A squirrel bounds across the ground, and up a nearby tree.",
				"A bush rustles as something skitters unseen within.",
				f"A lonesome howl floats in from the {get_random_direction()}.",
				"Happy warbling resounds as a songbird flits across the area."
			])

		if msg:
			Dispatcher.add(self.channel, msg)

		self.last_tick_game_time = game_time

	def to_dict(self):
		"""Returns the database friendly dictionary for this game."""

		d = {
			'guild_id': self.guild.id,
			'channelId': self.channel.id,
			'use_spawn_timer': self.use_spawn_timer,
			'spawn_duration': self.spawn_duration,
			'loot_duration': self.loot_duration,
			'minutes_max': self.minutes_max,
			'minutes_min': self.minutes_min,
			'prefix': self.prefix,
			'use_ambiance': self.use_ambiance,
			'game_time': self.game_clock.get_hours()
		}

		if self.id is not None:
			d['_id'] = self.id

		return d

	# Adds or updates a game object in the database.
	def save(self) -> None:
		"""Adds or updates a game object in the database."""

		result = MongoDB["games"].update_one({'guild_id': self.guild.id}, {'$set': self.to_dict()}, upsert=True)
		if self.id is None:
			self.id = result.upserted_id

	@classmethod
	async def load(cls, guild_id: int, bot: Bot) -> Optional["Game"]:
		"""Returns a game loaded from the database."""

		if guild_id is None:
			return None

		g = await MongoDB.games.find_one({'guild_id': guild_id})
		if g is None or bot is None:
			return None

		return await Game.from_dict(g, bot)

	@classmethod
	async def from_dict(cls, d: dict, bot: Bot) -> Optional["Game"]:
		"""Returns a game from it's dictionary representation."""

		if d is None or bot is None:
			return None

		game = cls(
			bot=bot,
			game_id=d['_id'],
			use_spawn_timer=d['use_spawn_timer'],
			spawn_max=int(d['minutes_max']),
			spawn_min=int(d['minutes_min']),
			spawn_duration=int(d['spawn_duration']),
			loot_duration=int(d['loot_duration']),
			prefix=d['prefix'],
			use_ambiance=d['use_ambiance'],
			time=d['game_time']
		)

		game.guild = bot.get_guild(d['guild_id'])
		game.channel = bot.get_channel(d['channel_id'])

		for p in MongoDB.players.find({'guild_id': game.guild.id}):
			uid = p['user_id']
			player = Player.from_dict(p)
			player.member = game.guild.get_member(uid) or await game.guild.fetch_member(uid)
			player.name = player.member.display_name
			game.players[uid] = player

		return game
