from discord.errors import HTTPException
from discord.ext.commands import Bot
from discord.ext import tasks
from discord import Guild, TextChannel, Embed, File
from .creatures.player import Player
from .creatures.monster import Monster
from random import choice, randint
from asyncio import sleep
from ...db.db import MongoDB
from pymongo.errors import DuplicateKeyError
from datetime import datetime

class Game:
	def __init__(self,
		bot: Bot = None,
		gameId: str = None,
		guild: Guild = None,
		channel: TextChannel = None,
		useSpawnTimer: bool = True,
		spawnMaxMinutesBetween: int = 60,
		spawnMinMinutesBetween: int = 10,
		spawnDuration: int = 10,
		lootDuration: int = 5,
		prefix: str = None
	):
		self.bot = bot
		self.id = gameId
		self.guild = guild
		self.channel = channel
		self.players: dict[int, Player] = {}
		self.monster: Monster = None
		self.combatants: list[int] = []
		self.loot: dict[int, list] = {}
		self.use_spawn_timer = useSpawnTimer
		self.spawn_duration = spawnDuration
		self.loot_duration = lootDuration
		self.trigger = randint(0, spawnMaxMinutesBetween)
		self.minutes_max = spawnMaxMinutesBetween
		self.minutes_min = spawnMinMinutesBetween
		self.prefix = prefix

		if useSpawnTimer:
			self.spawn_check.start()

	def cancelCombat(self):
		self.monster = None
		self.combatants.clear()
		self.loot.clear()
	
	# Sends a message and/or embed to the game's channel, returning a boolean indicating success or failure.
	async def send(self, message: str = None, embed: Embed = None, file: File = None) -> bool:
		'''Sends a message and/or embed to the game's channel, returning a boolean indicating success or failure.
		'''
		try:
			await self.channel.send(content=message, embed=embed, file=file)
		except HTTPException as e:
			if e.code == 429:
				msg = f'{datetime.now().strftime("%m-%d-%Y %H:%M:%S")}: Message blocked due to rate limiting.'
				if 'Retry-After' in e.response.headers.keys():
					msg += f" Retry After {e.response.headers['Retry-After']} seconds."
			elif e.code == 400:
				msg = f'{datetime.now().strftime("%m-%d-%Y %H:%M:%S")}: Message returned a bad format error.'
		
			print(msg)
			return False
		return True
	
	# Cleans up any loot that wasn't picked up
	async def loot_expires(self):
		await sleep(self.loot_duration * 60)
		if len(self.loot) > 0:
			await self.send("A swarm of tiny, shadow-clad creatures floods in and makes off with the items on the ground.")

		self.loot.clear()

	# Builds a combat message for a player, and returns the message and the damage as a tuple
	def getCombatMessage(self, player: Player):
		lAtk, lDmg, rAtk, rDmg = player.get_attack_rolls();
		lCrit = lAtk == 20
		rCrit = rAtk == 20
		lFumble = lAtk == 1
		rFumble = rAtk == 1
		lMiss = lAtk < self.monster.dodge or lFumble
		rMiss = rAtk < self.monster.dodge or rFumble
		isDual = rAtk == 0
		msg = f"{player.member.mention}'s attack:"

		if lMiss:
			lDmg = 0
		if rMiss:
			rDmg = 0
		
		if lCrit:
			lDmg *= 2
		if rCrit:
			rDmg *= 2
		
		tDmg = lDmg + rDmg - self.monster.defense

		if tDmg <= 0 and not (lMiss and rMiss):
			tDmg = 1
		elif tDmg < 0 and lMiss and rMiss:
			tDmg = 0

		if isDual:
			msg += f"```\nAtk: {lAtk} vs Dodge: {self.monster.dodge} --> {'FUMBLE' if lFumble else 'MISS' if lMiss else 'CRIT' if lCrit else 'HIT'}"
			if not lMiss:
				msg += f"\nDamage: {lDmg} vs Defense: {self.monster.defense} --> {tDmg}"
		else:
			msg += f"```\nAtk: {lAtk}|{rAtk} vs Dodge: {self.monster.dodge} --> {'FUMBLE' if lFumble else 'MISS' if lMiss else 'CRIT' if lCrit else 'HIT'}|{'FUMBLE' if rFumble else 'MISS' if rMiss else 'CRIT' if rCrit else 'HIT'}"
			if not lMiss or not rMiss:
				msg += f"\nDamage: {lDmg} + {rDmg} vs Defense: {self.monster.defense} --> {tDmg}"
					
		msg += "```\n"
		return (msg, tDmg)

	async def on_monster_death(self):
		if not await self.send(f"{self.monster.death}"):
			self.cancelCombat()

		for pid in self.combatants:
			loot = self.monster.getLoot()
			print(f"Loot added for {pid}")
			self.loot[pid] = loot
		
		self.monster = None
		self.combatants.clear()
		if len(self.loot) == 0:
			await self.send("There does not appear to be anything to loot, this time.")
		else:
			await self.send(f"There might be something to `{self.prefix}loot`...")
			await self.loot_expires()
		
	# Performs combat sequence
	@tasks.loop(count=1)
	async def do_combat(self):
		self.spawn_check.cancel()
		await sleep(self.spawn_duration * 60)

		msg = ""
		damage = 0
		for pid in self.combatants:
			m, d = self.getCombatMessage(self.players[pid])
			if len(msg) + len(m) > 2000:
				if await self.send(msg):
					msg = ""
				else:
					self.cancelCombat()
					return
			msg += m
			damage += d
		
		msg += f"Total damage done: {damage:,} vs Health: {self.monster.health:,}\n"

		self.monster.health -= damage
		if self.monster.health <= 0:
			if await self.send(msg):
				await self.on_monster_death()
			else:
				self.cancelCombat()
				self.spawn_check.start()
				return

		else:
			if not await self.send(f"{msg}\n{self.monster.escape}"):
				self.cancelCombat()
				self.spawn_check.start()
				return

			self.cancelCombat()

		await sleep(self.minutes_min * 60)
		self.spawn_check.start()
	
	# Spawns a monster
	async def spawn(self):
		'''Spawns a monster, and starts the combat sequence.'''
		self.trigger = 0
		self.monster = Monster(choice(list(MongoDB.templates_monsters.find())))
		embed, file = self.monster.getEmbed()
		if await self.send(self.monster.arrival, embed=embed, file=file):
			self.do_combat.start()
		else:
			self.cancelCombat()

	# Attempts to spawn a monster
	@tasks.loop(minutes=1)
	async def spawn_check(self):
		if not self.use_spawn_timer:
			print("Spawn loop ending...")
			self.spawn_check.cancel()
			return
		
		if self.bot.is_ws_ratelimited():
			print("Spawning blocked due to rate limit.")
			return

		self.trigger = min(self.trigger, self.minutes_max)
		r = randint(self.trigger, self.minutes_max)
		if r == self.minutes_max:
			await self.spawn()
			return
		
		self.trigger += 1
		return
	
	async def killMonster(self):
		self.do_combat.cancel()
		await self.on_monster_death()

	# Gets a dictionary respresentation of the game.
	def to_dict(self):
		d = {
			'guildId': self.guild.id,
			'channelId': self.channel.id,
			'use_spawn_timer': self.use_spawn_timer,
			'spawn_duration': self.spawn_duration,
			'loot_duration': self.loot_duration,
			'minutes_max': self.minutes_max,
			'minutes_min': self.minutes_min,
			'prefix': self.prefix
		}

		if self.id is not None:
			d['_id'] = self.id
		
		return d
	
	# Adds or updates a game object in the database.
	def save(self) -> None:
		'''Adds or updates a game object in the database.
		'''
		try:
			self.id = MongoDB.games.insert_one(self.to_dict()).inserted_id
		except DuplicateKeyError:
			MongoDB.games.update_one({ '_id': self.id }, { '$set': self.to_dict() })
	
	@classmethod
	async def load(cls, guildId: int, bot: Bot):
		if guildId is None:
			return None

		g = MongoDB.games.find_one({ 'guildId': guildId })
		if g is None or bot is None:
			return None
		
		return await Game.from_dict(g, bot)
		
	@classmethod
	async def from_dict(cls, d: dict, bot: Bot):
		'''Returns a dictionary representation of the game.'''
		if d is None or bot is None:
			return None
		
		game = cls(
			bot = bot,
			gameId = d['_id'],
			useSpawnTimer = d['use_spawn_timer'],
			spawnMaxMinutesBetween = int(d['minutes_max']),
			spawnMinMinutesBetween = int(d['minutes_min']),
			spawnDuration = int(d['spawn_duration']),
			lootDuration = int(d['loot_duration']),
			prefix = d['prefix']
		)

		game.guild = bot.get_guild(d['guildId'])
		game.channel = bot.get_channel(d['channelId'])

		for p in MongoDB.players.find({ 'guildId': game.guild.id }):
			uid = p['userId']
			player = Player.from_dict(p)
			player.member = game.guild.get_member(uid) or await game.guild.fetch_member(uid)
			player.name = player.member.display_name
			game.players[uid] = player

		return game