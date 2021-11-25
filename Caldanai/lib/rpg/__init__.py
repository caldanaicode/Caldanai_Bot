import importlib
import random
from asyncio import sleep
from glob import glob
from os import path

from discord.ext.commands import Bot
from discord import Guild, TextChannel
from typing import Dict, List, Union, Optional
from random import choice, randint

from .areas import Area
from .helpers.enums import AggressionLevels, TimesOfDay
from .helpers.parser import parse
from .time import GameClock
from .creatures import Creature
from .helpers import get_random_direction
from .creatures.monsters import Monster
from .creatures.player import Player
from .inventory.items import Item
from .inventory.weapons import Weapon
from ...Dispatcher import Dispatcher
from ...Logger import stdout
from ...db import MongoDB


class Game:
	"""
	Structure for game information.

	Members
	-------
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
	enable_ambience : bool
		Whether or not to display ambience messages such as weather, day/night cycles, and monster ambience messages

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
			enable_ambience: bool = True,
			game_time: int = 0
	):
		"""
		Initialize a new Game object.

		:param bot: The bot that owns this game.
		:param game_id: The game's database ID.
		:param guild: The guild (a.k.a server) that hosts this game.
		:param channel: The channel to which this game sends most responses.
		:param use_spawn_timer: Whether or not to allow periodic monster spawns.
		:param spawn_max: Maximum minutes between monster spawns.
		:param spawn_min: Minimum minutes between monster spawns.
		:param spawn_duration: Number of minutes before first combat triggers. Additional rounds occur at half this
		time.
		:param loot_duration: Number of minutes before loot expires.
		:param prefix: The game's command prefix.
		:param enable_ambience: Whether or not to display ambience messages such as weather, day/night cycles,
		and monster ambience messages.
		:param game_time: The game's internal time value.
		"""
		self.bot = bot
		self.id = game_id
		self.guild = guild
		self.channel = channel
		self.players: Dict[int, Player] = {}
		self.monster: Optional[Monster] = None
		self.monsters: List[str] = []
		self.combatants: List[int] = []
		self.looters: List[int] = []
		self.loot: Dict[int, List[Union[Item, Weapon]]] = {}
		self.use_spawn_timer = use_spawn_timer
		self.spawn_duration = spawn_duration * 60
		self.loot_duration = loot_duration * 60
		self.loot_countdown = loot_duration * 60
		self.minutes_max = spawn_max
		self.minutes_min = spawn_min
		self.prefix = prefix
		self.enable_ambience = enable_ambience

		self.game_clock = GameClock(game_time=game_time)
		self.game_clock.tick.start()
		self.weather = None
		self._last_ambience_tick = self.game_clock.get_seconds()
		self.room0: Area = None

		# Regen timer is triggered every game hour (15 minutes for default time scale)
		self.game_clock.add_routine(self.do_health_regen, 3600 / self.game_clock.time_scale)

		if use_spawn_timer:
			self.game_clock.add_routine(self.do_spawn, 5, True)
		if enable_ambience:
			self.game_clock.add_routine(self.do_ambience, 1)

	async def check_time(self):
		if not self.monster or self.monster.is_dead() \
				or (not self.monster.flees_from_time and not self.monster.dies_from_time):
			self.game_clock.remove_routine(self.check_time)
			return

		monster = self.monster
		tod = self.game_clock.get_time_of_day()
		h, m, _ = self.game_clock.get_time_components()
		next_tod, next_h, next_m = self.game_clock.get_next_time()
		flee = not bool(monster.time_partition & TimesOfDay[tod.upper()].value)
		next_flee = not bool(monster.time_partition & TimesOfDay[next_tod.upper()].value)
		msg = ""

		if flee and monster.dies_from_time:
			msg = monster.time_death
			msg += self.on_monster_death()

		elif monster.flees_from_time:
			remaining = ((24 if h > next_h else 0) + next_h + next_m / 60) - (h + m / 60)
			if flee or (next_flee and remaining < 1 / 6):
				msg = monster.time_flee
				self.cancel_combat()

		if msg:
			Dispatcher.add(self.channel, parse(msg, monster))

	def get_monster(self, monster: Optional[str] = None):
		if monster is None:
			self.monster = Monster.get_random_monster(self.game_clock)
		else:
			monsters = [
				filepath.split(path.sep)[-1][:-3] for filepath in glob("./Caldanai/lib/rpg/creatures/monsters/*.py")
			]
			monsters.remove('__init__')
			self.monster = importlib.import_module(f'Caldanai.lib.rpg.creatures.monsters.{monster}').MonsterPlugin()

		embed, file = self.monster.get_embed()
		Dispatcher.add(self.channel, parse(self.monster.arrival, self.monster), embed=embed, file=file)
		if self.monster.dies_from_time or self.monster.flees_from_time:
			self.game_clock.add_routine(self.check_time, 1)

	async def do_spawn(self, force: bool = False, monster: Optional[str] = None):
		if self.monster:
			return

		if not force:
			r = randint(self.minutes_min, self.minutes_max)
			await sleep(r * 60)
			if self.monster:
				return

		self.get_monster(monster)
		self.game_clock.add_routine(self.do_combat, self.spawn_duration, True)

	def cancel_combat(self):
		"""Clears the current monster, combatants, and loot."""
		self.monster = None
		self.combatants.clear()
		self.loot.clear()
		self.looters.clear()
		self.game_clock.remove_routine(self.do_combat)
		self.game_clock.add_routine(self.do_spawn, 5, True)

	async def loot_expires(self):
		"""Cleans up uncollected loot and restarts spawning after loot expiration and minimum spawn time."""
		if any([len(loot) for loot in self.loot.values()]) > 0:
			Dispatcher.add(
				self.channel,
				"A swarm of tiny, shadow-clad creatures floods in and makes off with the items on the ground."
			)
		self.loot.clear()
		self.game_clock.add_routine(self.do_spawn, 5, True)

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
		self.game_clock.remove_routine(self.do_combat)
		if has_loot:
			self.game_clock.add_routine(self.loot_expires, self.loot_duration, True)
			return f"\nThere might be something to `{self.prefix}loot`..."
		else:
			self.game_clock.add_routine(self.do_spawn, 5, True)
			return "\nThere does not appear to be anything to loot, this time."

	async def do_health_regen(self):
		"""Applies health regen to players, and increments the health regen amount."""
		msg = ""
		for player in self.players.values():
			m = player.apply_damage(-player.health_regen)
			if m:
				msg += f"\n{m}"
			player.health_regen = (player.health_regen + 1) if player.health < player.health_max else 0

		if msg:
			Dispatcher.add(self.channel, msg)

	def attack_random_combatant(self) -> str:
		victim = self.players[choice(self.combatants)]
		m, d = self.monster.do_attack(victim)
		if d > 0:
			m += parse(victim.apply_damage(d), victim)
		return m

	async def do_combat(self):
		"""Tallies and displays combat results."""

		if self.monster is None:
			stdout(f"Combat unable to proceed in `{self.guild.name}` because no monster was present.")
			self.game_clock.add_routine(self.do_spawn, 5, True)
			return

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

		msg += parse(self.monster.apply_damage(damage) or "", self.monster)
		if self.monster.is_dead():
			monster = self.monster
			msg += parse(self.on_monster_death(), monster)
			msgs = Dispatcher.split_message(msg, '```\n', True)
			for m in msgs:
				Dispatcher.add(self.channel, m)

		else:
			if self.monster.aggression in (AggressionLevels.RAMPAGE, AggressionLevels.VENGEFUL) \
				and len(self.combatants) > 0:

				msg += f"\n{self.attack_random_combatant()}"
				if self.monster.aggression == AggressionLevels.RAMPAGE:
					Dispatcher.add(self.channel, parse(msg, self.monster))
					self.combatants.clear()
					self.game_clock.add_routine(self.do_combat, int(self.spawn_duration / 2), True)
					return

			if self.monster.aggression in (AggressionLevels.VENGEFUL, AggressionLevels.PASSIVE) \
				or len(self.combatants) == 0:

				Dispatcher.add(self.channel, f"{msg}\n{parse(self.monster.escape, self.monster)}")
				self.cancel_combat()

	def kill_monster(self):
		"""Cancels combat and forces monster death."""

		self.game_clock.remove_routine(self.do_combat)
		monster = self.monster
		msg = self.on_monster_death()
		if len(msg) > 0:
			Dispatcher.add(self.channel, parse(msg, monster))

	async def do_ambience(self):
		"""Small chance to display a random ambience message."""

		if not self.enable_ambience:
			stdout(f"Removing ambience loop for game on {self.guild.name}.")
			self.game_clock.remove_routine(self.do_ambience)
			return

		game_time = self.game_clock.get_seconds()

		msg = ""

		sunrise, sunset = self.game_clock.get_sunrise_and_sunset()

		if self._last_ambience_tick < sunrise <= game_time:
			msg = "The sky glows softly to the east as night gives way to day."
		elif self._last_ambience_tick < sunset <= game_time:
			msg = "The crimson disc sinks slowly beyond the horizon, and darkness creeps across the land."

		if random.randint(1, 3000) == 3000:
			msg += choice([
				"A squirrel bounds across the ground, and up a nearby tree.",
				"A bush rustles as something skitters unseen within.",
				f"A lonesome howl floats in from the {get_random_direction()}.",
				"Happy warbling resounds as a songbird flits across the area."
			])

		if msg:
			Dispatcher.add(self.channel, msg)

		self._last_ambience_tick = game_time

	def to_dict(self):
		"""Returns the database friendly dictionary for this game."""

		d = {
			'guild_id'       : self.guild.id,
			'channelId'      : self.channel.id,
			'use_spawn_timer': self.use_spawn_timer,
			'spawn_duration' : int(self.spawn_duration / 60),
			'loot_duration'  : int(self.loot_duration / 60),
			'minutes_max'    : self.minutes_max,
			'minutes_min'    : self.minutes_min,
			'prefix'         : self.prefix,
			'enable_ambience': self.enable_ambience,
			'game_time'      : self.game_clock.get_seconds()
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
			enable_ambience=d['enable_ambience'],
			game_time=d['game_time']
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
