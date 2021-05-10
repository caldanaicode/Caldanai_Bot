from math import fsum, floor
from typing import Dict, Tuple, Optional

from discord import Member, Embed, File
from discord.errors import HTTPException
from Caldanai.lib.rpg.creatures.creature import Creature
from Caldanai.lib.rpg.creatures.monster import Monster
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll, CombinedRoll
from Caldanai.lib.rpg.inventory.inventory import Inventory, Item, Weapon
from Caldanai.db.db import MongoDB
from pymongo.errors import DuplicateKeyError
from datetime import datetime


class Player(Creature):
	"""A simple Player object for tracking player data"""

	def __init__(
			self,
			pid: Optional[int],
			gid: Optional[int],
			uid: Optional[int],
			weight_limit: Optional[int],
			joined: Optional[datetime],
			clarks: Optional[int],
			defense: Optional[int],
			dodge: Optional[int],
			health: Optional[int],
			inventory: Optional[Inventory],
			atk_avg: Optional[float],
			atk_cnt: Optional[int],
			dmg_avg: Optional[float],
			dmg_cnt: Optional[int],
			skills: Optional[Dict[str, int]]
	):
		super().__init__(name=None, atk=None, defense=defense, dodge=dodge, health=health)
		self.id = pid
		self.guildId = gid
		self.userId = uid
		self.member: Optional[Member] = None
		self.weightLimit = weight_limit or 100
		self.joined = joined
		self.clarks = clarks or 0
		self.leftHand: Optional[Weapon] = None
		self.rightHand: Optional[Weapon] = None
		self.inventory = inventory or Inventory()
		self.attackAverage = atk_avg or 0
		self.attackCount = atk_cnt or 0
		self.damageAverage = dmg_avg or 0
		self.damageCount = dmg_cnt or 0
		self.skills = skills or {}
		self.isDirty = False

	def __eq__(self, o):
		return isinstance(o, Player) and self.userId == o.userId and self.guildId == o.guildId

	# Sends a message and/or embed to the player as a DM, returning a boolean indicating success or failure.
	async def send(self, message: Optional[str], embed: Optional[Embed], file: Optional[File]) -> bool:
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
		"""
		Un-equips the item in the player's left hand.

		Also un-equips the right hand if the item is two-handed.
		"""

		item = self.leftHand
		self.leftHand = None
		if item is not None and item.isTwoHanded:
			self.rightHand = None

	# Un-equips the item in the player's right hand.
	def disarm_right(self) -> None:
		"""
		Un-equips the item in the player's right hand.

		Also un-equips the left hand if the item is two-handed.
		"""

		item = self.rightHand
		self.rightHand = None
		if item is not None and item.isTwoHanded:
			self.leftHand = None

	# Equips an item in the left hand, removing the currently equipped item if necessary.
	def equip_left(self, weapon: Weapon) -> None:
		"""
		Equips an item in the left hand, removing the currently equipped item if necessary.

		Also equips to the right hand if the weapon is two-handed.
		"""

		if self.leftHand is not None:
			self.disarm_left()

		self.leftHand = weapon
		if weapon is not None and weapon.isTwoHanded:
			self.rightHand = weapon

	# Equips an item in the right hand, removing the currently equipped item if necessary.
	def equip_right(self, weapon: Weapon) -> None:
		"""
		Equips an item in the right hand, removing the currently equipped item if necessary.

		Also equips to the left hand if the weapon is two-handed.
		"""

		if self.rightHand is not None:
			self.disarm_right()

		self.rightHand = weapon
		if weapon is not None and weapon.isTwoHanded:
			self.leftHand = weapon

	# Returns the attack and damage bonus for a given skill as a tuple.
	def get_skill_bonus(self, skill: str) -> Tuple[int, int]:
		"""Returns a tuple containing the attack bonus and damage bonus for a given skill."""

		atk = floor(self.get_skill_level(skill) / 2)
		dmg = floor(self.get_skill_level(skill) / 4)
		return atk, dmg

	# Updates the player's attack and damage averages.
	def update_averages(self, left: Optional[CombinedRoll], right: Optional[CombinedRoll]):
		"""Updates the player's attack and damage averages."""

		a_count = (1 if left else 0) + (1 if right else 0)
		d_count = (1 if left and not left.isMiss else 0) + (1 if right and not right.isMiss else 0)
		if self.attackCount + a_count > 0:
			self.attackAverage = fsum([
				self.attackCount * self.attackAverage,
				left.attack.result if left and left.attack else 0,
				right.attack.result if right and right.attack else 0
			]) / (self.attackCount + a_count)
			self.attackCount += a_count
		if self.damageCount + d_count > 0:
			self.damageAverage = fsum([
				self.damageCount * self.damageAverage,
				left.damage.result if left and left.damage else 0,
				right.damage.result if right and right.damage else 0
			]) / (self.damageCount + d_count)
			self.damageCount += d_count
		self.isDirty = True

	# Returns the skill level for the given skill name.
	def get_skill_level(self, skill: str) -> int:
		"""Return the skill level for the given skill."""

		if skill not in self.skills.keys():
			return 1

		return floor((25 + (5 * (125 + self.skills[skill])) ** 0.5) / 50)

	# Increments the given skill's experience level.
	def gain_skill_experience(self, skill: str) -> None:
		"""Applies experience gain for the given skill."""

		if skill not in self.skills.keys():
			self.skills[skill] = 0

		amt = (10 + floor(10 * (self.get_skill_level(skill) ** 0.5)))
		if "two-handed" in skill:
			amt *= 2

		self.skills[skill] += amt
		self.isDirty = True

	def get_combat_rolls(self, weapon: Optional[Weapon], monster: Monster) -> CombinedRoll:
		"""Returns a CombinedRoll for the given weapon's attack and damage rolls."""

		bonus = self.get_skill_bonus("unarmed" if weapon is None else weapon.skill)
		attack = AttackRoll(
			roll=Dice.d20(),
			skill_bonus=bonus[0]
		)
		damage = DamageRoll(
			roll=Dice.d4() if weapon is None else Dice.quick_roll(weapon.attack),
			weapon_bonus=0 if weapon is None else weapon.bonus,
			skill_bonus=bonus[1]
		)
		return CombinedRoll(attack, damage, monster)

	def do_attack(self, monster: Monster) -> Tuple[str, int]:
		"""
		Performs an attack against the given monster, without modifying the monster's attributes.

		Returns a tuple containing the attack message and the total damage done.
		"""

		two_handed = self.leftHand and self.leftHand.isTwoHanded
		left = self.get_combat_rolls(self.leftHand, monster)
		right: Optional[CombinedRoll] = None if two_handed else self.get_combat_rolls(self.rightHand, monster)
		t_dmg = left.result + (right.result if right else 0) - monster.defense

		if left.isMiss and (right is None or right.isMiss):
			t_dmg = 0
		elif t_dmg < 0:
			t_dmg = 1

		msg = f"{self.member.mention}'s attack:" \
			f"```\nAttack: {left.attack}{' | ' + str(right.attack) if right else ''} " \
			f"vs Dodge: {monster.dodge} --> " \
			f"{left.get_hit_string()}{' | ' + right.get_hit_string() if right else ''}" \

		if not left.isMiss or (right and not right.isMiss):
			msg += f"\nDamage: {left.damage}{' | ' + str(right.damage) if right else ''}"

			if not left.isMiss:
				self.gain_skill_experience(self.leftHand.skill)

			if right and not right.isMiss:
				self.gain_skill_experience(self.rightHand.skill)

			msg += f" vs Defense: {monster.defense} --> {t_dmg}"

		msg += "```\n"
		self.update_averages(left, right)
		return msg, t_dmg

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
		"""
		Adds an item to the player's inventory, if they can afford the weight.

		Returns a boolean value indicating if the item was added.
		"""

		if self.get_weight() + item.weight > self.weightLimit:
			return False

		item.playerId = self.id
		self.isDirty = True
		return self.inventory.add(item)

	# Removes an item from the player's inventory, if present.
	def take_item(self, item: Item) -> bool:
		"""
		Removes an item from the player's inventory, if present.

		Returns a boolean indicating if the item was found and removed.
		"""

		if item == self.inventory[str(item.id)]:
			item.playerId = None
			self.isDirty = True
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
		"""Adds or updates a player object in the database."""

		if not self.isDirty:
			return

		try:
			self.id = MongoDB.players.insert_one(self.to_dict()).inserted_id
			self.isDirty = False
		except DuplicateKeyError:
			MongoDB.players.update_one({'_id': self.id}, {'$set': self.to_dict()})

	@classmethod
	# Retrieves a player object from the database, or None if it does not exist.
	def load(cls, **kwargs) -> Optional["Player"]:
		"""Retrieves a player object from the database, or None if it does not exist."""

		p = None
		if 'guildId' in kwargs.keys() and 'userId' in kwargs.keys():
			p = MongoDB.players.find_one({"guildId": kwargs['guildId'], "id": kwargs['userId']})
		elif 'pDict' in kwargs.keys():
			p = kwargs['pDict']

		return cls.from_dict(p)

	@classmethod
	# Retrieves a player object given a dictionary representation.
	def from_dict(cls, p: dict) -> Optional["Player"]:
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
