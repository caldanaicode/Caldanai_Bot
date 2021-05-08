from math import fsum, floor
from typing import List, Dict, Tuple

from discord import Member, Embed, File
from discord.errors import HTTPException
from .creature import Creature
from ..dice import quick_roll
from ..inventory.inventory import Inventory, Item, Weapon
from Caldanai.db.db import MongoDB
from pymongo.errors import DuplicateKeyError
from datetime import datetime


class Player(Creature):
	"""A simple Player object for tracking player data"""
	def __init__(
			self,
			pid: int = None,
			gid: int = None,
			uid: int = None,
			member: Member = None,
			weight_limit: int = 100,
			joined: datetime = None,
			clarks: int = 0,
			defense: int = 1,
			dodge: int = 1,
			health: int = 1,
			left_hand: Weapon = None,
			right_hand: Weapon = None,
			inventory: Inventory = Inventory(),
			atk_avg: float = 0,
			atk_cnt: int = 0,
			dmg_avg: float = 0,
			dmg_cnt: int = 0,
			skills: Dict[str, int] = {}
	):
		name = member.display_name if member is not None else ''
		super().__init__(name=name, atk=None, defense=defense, dodge=dodge, health=health)
		self.id = pid
		self.guildId = gid
		self.userId = uid
		self.member = member
		self.weightLimit = weight_limit
		self.joined = joined
		self.clarks = clarks
		self.leftHand = left_hand
		self.rightHand = right_hand
		self.inventory = inventory
		self.attackAverage = atk_avg
		self.attackCount = atk_cnt
		self.damageAverage = dmg_avg
		self.damageCount = dmg_cnt
		self.skills = skills

	def __eq__(self, o):
		return isinstance(o, Player) and self.userId == o.userId and self.guildId == o.guildId

	# Sends a message and/or embed to the player as a DM, returning a boolean indicating success or failure.
	async def send(self, message: str = None, embed: Embed = None, file: File = None) -> bool:
		"""Sends a message and/or embed to the player as a DM, returning a boolean indicating success or failure."""
		try:
			await self.member.send(content=message, embed=embed, file=file)
		except HTTPException as e:
			msg = f'{datetime.now().strftime("%m-%d-%Y %H:%M:%S")}: HTTP Exception'
			if e.code == 429:
				msg += f' -- Message blocked due to rate limiting.'
				if 'Retry-After' in e.response.headers.keys():
					msg += f" Retry After {e.response.headers['Retry-After']} seconds."
			elif e.code == 400:
				msg += f' -- Message returned a bad format error.'
			else:
				msg += e.text

			print(msg)
			return False
		return True

	# Un-equips the item in the player's left hand.
	def disarm_left(self) -> None:
		"""Un-equips the item in the player's left hand.

		Also un-equips the right hand if the item is two-handed.
		"""
		item = self.leftHand
		self.leftHand = None
		if item is not None and item.isTwoHanded:
			self.rightHand = None

	# Un-equips the item in the player's right hand.
	def disarm_right(self) -> None:
		"""Un-equips the item in the player's right hand.

		Also un-equips the left hand if the item is two-handed.
		"""
		item = self.rightHand
		self.rightHand = None
		if item is not None and item.isTwoHanded:
			self.leftHand = None

	# Equips an item in the left hand, removing the currently equipped item if necessary.
	def equip_left(self, weapon: Weapon) -> None:
		"""Equips an item in the left hand, removing the currently equipped item if necessary.

		Also equips to the right hand if the weapon is two-handed.
		"""
		if self.leftHand is not None:
			self.disarm_left()

		self.leftHand = weapon
		if weapon is not None and weapon.isTwoHanded:
			self.rightHand = weapon

	# Equips an item in the right hand, removing the currently equipped item if necessary.
	def equip_right(self, weapon: Weapon) -> None:
		"""Equips an item in the right hand, removing the currently equipped item if necessary.

		Also equips to the left hand if the weapon is two-handed."""
		if self.rightHand is not None:
			self.disarm_right()

		self.rightHand = weapon
		if weapon is not None and weapon.isTwoHanded:
			self.leftHand = weapon

	# Returns the attack and damage bonus for a given skill as a tuple.
	def get_skill_bonus(self, skill: str) -> Tuple[int, int]:
		atk = floor(self.get_skill_level(skill) / 2)
		dmg = floor(self.get_skill_level(skill) / 4)
		return atk, dmg

	# Calculates attack and damage rolls (including bonuses) using the player's equipped weapon(s).
	def get_attack_rolls(self) -> (int, int, int, int):
		"""Returns a tuple containing (l_atk, l_dmg, r_atk, r_dmg) rolls for the player.
		r_atk and r_dmg will be 0 if attacking with a two-handed weapon.
		"""
		left = self.leftHand is not None
		two = left and self.leftHand.isTwoHanded
		right = self.rightHand is not None

		l_atk = quick_roll("1d20")
		l_dmg = self.leftHand.get_attack_damage() if left else quick_roll("1d4")
		l_bonus = self.get_skill_bonus(self.leftHand.skill) if left else self.get_skill_bonus("unarmed")

		r_atk = quick_roll("1d20") if not two else 0
		r_dmg = 0 if two else self.rightHand.get_attack_damage() if right else quick_roll("1d4")
		r_bonus = self.get_skill_bonus(self.rightHand.skill) if right and not two else (0, 0)

		return l_atk + l_bonus[0], l_dmg + l_bonus[1], r_atk + r_bonus[0], r_dmg + r_bonus[1]

	# Updates the player's attack and damage averages.
	def update_averages(self, l_atk, l_dmg, r_atk, r_dmg):
		"""Updates the player's attack and damage averages."""
		a_count = (1 if l_atk > 0 else 0) + (1 if r_atk > 0 else 0)
		d_count = (1 if l_dmg > 0 else 0) + (1 if r_dmg > 0 else 0)
		if self.attackCount + a_count > 0:
			self.attackAverage = fsum([self.attackCount * self.attackAverage, l_atk, r_atk])\
				/ (self.attackCount + a_count)
			self.attackCount += a_count
		if self.damageCount + d_count > 0:
			self.damageAverage = fsum([self.damageCount * self.damageAverage, l_dmg, r_dmg])\
				/ (self.damageCount + d_count)
			self.damageCount += d_count
		self.save()

	# Returns the skill level for the given skill name.
	def get_skill_level(self, skill: str) -> int:
		if skill not in self.skills.keys():
			return 1

		return floor((25 + (5 * (125 + self.skills[skill])) ** 0.5) / 50)

	# Increments the given skill's experience level.
	def gain_skill_experience(self, skill: str) -> None:
		if skill not in self.skills.keys():
			self.skills[skill] = 0
		self.skills[skill] += 10 + floor(10 * (self.get_skill_level(skill) ** 0.5))

	# Returns a discord Embed for the player's profile.
	def get_profile(self, guild_name: str) -> Embed:
		"""Returns a discord Embed for the player's profile."""
		embed = Embed(
			title=f"Player Profile",
			description=f'for {self.name} on {guild_name}',
			color=0x00ffff
		)
		fields = [
			("Equipped", "---------------------------------------------------", False),
			("Left Hand", "None" if self.leftHand is None
				else f"{self.leftHand.article} {self.leftHand.name} ({self.leftHand.rarity.name})", True),
			("Right Hand", "None" if self.rightHand is None
				else f"{self.rightHand.article} {self.rightHand.name} ({self.rightHand.rarity.name})", True),
			("\u200b", "\u200b", False),
			("Stats", "---------------------------------------------------", False),
			("Left Hand", f"{self.leftHand.attack} + {self.leftHand.bonus}" if self.leftHand is not None
				else "1d4", True),
			("Right Hand", f"{self.rightHand.attack} + {self.rightHand.bonus}" if self.rightHand is not None
				else "1d4", True),
			("\u200b", "\u200b", True),
			("Defense", self.defense, True),
			("Dodge", self.dodge, True),
			("Health", self.health, True),
			("\u200b", "\u200b", False),
			("General", "---------------------------------------------------", False),
			("Average Attack Roll", f'{self.attackAverage:.2f}', True),
			("Attack Count", f"{self.attackCount:,}", True),
			("\u200b", "\u200b", True),
			("Average Damage Amount", f'{self.damageAverage:.2f}', True),
			("Damage Count", f'{self.damageCount:,}', True),
			("\u200b", "\u200b", True),
			("Clarks", f'{self.clarks:,}', True),
			("Weight", f'{self.get_weight():,} / {self.weightLimit:,}', True),
			("Joined", self.joined, False),
			("\u200b", "\u200b", False),
			("Skills", "---------------------------------------------------", False)
		]

		for skill in self.skills.keys():
			bonuses = self.get_skill_bonus(skill)
			msg = f"Current XP: {self.skills[skill]:,}\nAttack Bonus: {bonuses[0]}\nDamage Bonus: {bonuses[1]}"
			fields.append((f"{skill} ({self.get_skill_level(skill)})", msg, False))

		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)

		return embed

	# Returns the cumulative weight of the player's inventory.
	def get_weight(self):
		"""Returns the cumulative weight of the player's inventory."""
		return self.inventory.get_weight()

	# Adds an item to the player's inventory, if they can afford the weight.
	def give_item(self, item: Item) -> bool:
		"""Adds an item to the player's inventory, if they can afford the weight.

		Returns a boolean value indicating if the item was added."""
		if self.get_weight() + item.weight > self.weightLimit:
			return False

		item.playerId = self.id
		return self.inventory.add(item)

	# Removes an item from the player's inventory, if present.
	def take_item(self, item: Item) -> bool:
		"""Removes an item from the player's inventory, if present.

		Returns a boolean indicating if the item was found and removed.
		"""
		if item == self.inventory[str(item.id)]:
			item.playerId = None
			return self.inventory.remove(item)
		return False

	# Returns a string containing a formatted display of the player's inventory.
	def get_inventory(self, guild_name: str):
		"""Returns a string containing a formatted display of the player's inventory."""
		msg = ''
		for idx, item in self.inventory.enumeration():
			msg += f"\n{idx}: {item.article} {item.name} ({item.rarity.name} {item.itemType})" \
				f"{' [left hand]' if item == self.leftHand else ''}{' [right hand]' if item == self.rightHand else ''}"

		if msg == '':
			msg = 'You have no items.'

		return f'Inventory for {self.name} on {guild_name}```js\n{msg}```'

	def to_dict(self) -> dict:
		"""Returns a dictionary of the player's attributes."""
		d = {
			'_id': self.id,
			'userId': self.userId,
			'guildId': self.guildId,
			'name': self.name,
			'defense': self.defense,
			'dodge': self.dodge,
			'health': self.health,
			'weightLimit': self.weightLimit,
			'joined': self.joined,
			'clarks': self.clarks,
			'leftHand': self.leftHand.id if self.leftHand is not None else None,
			'rightHand': self.rightHand.id if self.rightHand is not None else None,
			'attackAverage': self.attackAverage,
			'attackCount': self.attackCount,
			'damageAverage': self.damageAverage,
			'damageCount': self.damageCount,
			'skills': self.skills
		}

		if self.id is None:
			del d['_id']

		return d

	# Adds or updates a player object in the database.
	def save(self) -> None:
		"""Adds or updates a player object in the database.
		"""
		try:
			self.id = MongoDB.players.insert_one(self.to_dict()).inserted_id
		except DuplicateKeyError:
			MongoDB.players.update_one({'_id': self.id}, {'$set': self.to_dict()})

	@classmethod
	# Retrieves a player object from the database, or None if it does not exist.
	def load(cls, **kwargs):
		"""Retrieves a player object from the database, or None if it does not exist.
		"""
		p = None
		if 'guildId' in kwargs.keys() and 'userId' in kwargs.keys():
			p = MongoDB.players.find_one({"guildId": kwargs['guildId'], "id": kwargs['userId']})
		elif 'pDict' in kwargs.keys():
			p = kwargs['pDict']

		return cls.from_dict(p)

	@classmethod
	# Retrieves a player object given a dictionary representation.
	def from_dict(cls, p: dict):
		if p is None:
			return None

		player = cls(
			pid=p['_id'],
			gid=p['guildId'],
			uid=p['userId'],
			weight_limit=p['weightLimit'],
			joined=p['joined'],
			clarks=p['clarks'],
			defense=p['defense'],
			dodge=p['dodge'],
			health=p['health'],
			inventory=Inventory.load(p['_id']),
			atk_avg=p['attackAverage'],
			atk_cnt=p['attackCount'],
			dmg_avg=p['damageAverage'],
			dmg_cnt=p['damageCount'],
			skills=p['skills']
		)

		if player.inventory[str(p['leftHand'])] is not None:
			player.equip_left(player.inventory[str(p['leftHand'])])

		if player.inventory[str(p['rightHand'])] is not None:
			player.equip_right(player.inventory[str(p['rightHand'])])

		return player
