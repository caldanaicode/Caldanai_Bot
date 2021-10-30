from math import floor
from typing import Dict, Tuple, Optional, List
from io import BytesIO

import pandas
import matplotlib.pyplot as plt

from discord import Member, Embed, File
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll, CombinedRoll
from Caldanai.lib.rpg.inventory import Inventory
from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.weapons import Weapon
from datetime import datetime


class Player(Creature):
	"""A simple Player object for tracking player data"""

	def __init__(
			self, *,
			pid: Optional[int] = None,
			gid: Optional[int] = None,
			uid: Optional[int] = None,
			weight_limit: Optional[int] = None,
			joined: Optional[datetime] = None,
			clarks: Optional[int] = 0,
			defense: Optional[int] = 10,
			dodge: Optional[int] = 10,
			health: Optional[int] = 20,
			health_max: Optional[int] = 20,
			inventory: Optional[Inventory] = None,
			rolls: Optional[Dict[str, List[int]]] = None,
			skills: Optional[Dict[str, int]] = None,
			gender: Optional[str] = None,
			pronouns: Optional[str] = None,
			armor_slots: Optional[Dict[str, Item]] = None
	):
		super().__init__(
			name=None, atk=None, defense=defense, dodge=dodge, health=health, health_max=health_max, gender=gender, pronouns=pronouns
		)
		self.id = pid
		self.guild_id = gid
		self.user_id = uid
		self.member: Optional[Member] = None
		self.weight_limit = weight_limit or 100
		self.joined = joined
		self.clarks = clarks
		self.left_hand: Optional[Weapon] = None
		self.right_hand: Optional[Weapon] = None
		self.inventory = inventory or Inventory()
		self.skills = skills or {}
		self.is_dirty = False
		self.rolls = rolls or {
			"d4": [0] * 4, "d6": [0] * 6, "d8": [0] * 8, "d10": [0] * 10, "d12": [0] * 12, "d20": [0] * 20
		}
		self.health_regen = 0
		self.equip_slots: Dict[str, Optional[Item]] = {
			"head": None, "neck": None, "torso": None, "back": None, "arms": None, "wrists": None,
			"ring1": None, "ring2": None, "waist": None, "legs": None, "shins": None, "feet": None
		}

		if armor_slots is not None:
			for slot, item_id in armor_slots.items():
				self.equip_slots[slot] = self.inventory[str(item_id)] if item_id is not None else None

	def __eq__(self, o):
		return isinstance(o, Player) and self.user_id == o.user_id and self.guild_id == o.guild_id

	def disarm_left(self) -> None:
		"""
		Un-equips the item in the player's left hand.

		Also un-equips the right hand if the item is two-handed.
		"""

		item = self.left_hand
		self.left_hand = None
		if item is not None and item.is_2handed:
			self.right_hand = None
		self.is_dirty = True

	def disarm_right(self) -> None:
		"""
		Un-equips the item in the player's right hand.

		Also un-equips the left hand if the item is two-handed.
		"""

		item = self.right_hand
		self.right_hand = None
		if item is not None and item.is_2handed:
			self.left_hand = None
		self.is_dirty = True

	def equip_left(self, weapon: Weapon) -> None:
		"""
		Equips an item in the left hand, removing the currently equipped item if necessary.

		Also equips to the right hand if the weapon is two-handed.
		"""

		if self.left_hand is not None:
			self.disarm_left()

		self.left_hand = weapon
		if weapon is not None and weapon.is_2handed:
			self.right_hand = weapon
		self.is_dirty = True

	def equip_right(self, weapon: Weapon) -> None:
		"""
		Equips an item in the right hand, removing the currently equipped item if necessary.

		Also equips to the left hand if the weapon is two-handed.
		"""

		if self.right_hand is not None:
			self.disarm_right()

		self.right_hand = weapon
		if weapon is not None and weapon.is_2handed:
			self.left_hand = weapon
		self.is_dirty = True

	def get_skill_bonus(self, skill: str) -> Tuple[int, int]:
		"""Returns a tuple containing the attack bonus and damage bonus for a given skill."""

		atk = floor(self.get_skill_level(skill) / 2)
		dmg = floor(self.get_skill_level(skill) / 4)
		return atk, dmg

	def update_roll_count(self, sides: int, value: int):
		"""Updates the player's roll count for an individual die roll."""

		if sides <= 1 or 1 > value or value > sides or f'd{sides}' not in self.rolls.keys():
			return

		self.rolls[f'd{sides}'][value - 1] += 1
		self.is_dirty = True

	def update_roll_counts(self, left: Optional[CombinedRoll], right: Optional[CombinedRoll]):
		"""Updates the player's attack and damage averages."""

		if left and left.attack:
			self.update_roll_count(20, left.attack.rolls[0])
			if not left.isMiss:
				for r in left.damage.rolls:
					self.update_roll_count(left.damage.sides, r)
		if right and right.attack:
			self.update_roll_count(20, right.attack.rolls[0])
			if not right.isMiss:
				for r in right.damage.rolls:
					self.update_roll_count(right.damage.sides, r)

	def get_skill_level(self, skill: str) -> int:
		"""Return the skill level for the given skill."""

		if skill not in self.skills.keys():
			return 1

		return floor((25 + (5 * (125 + self.skills[skill])) ** 0.5) / 50)

	def gain_skill_experience(self, skill: str) -> None:
		"""Applies experience gain for the given skill."""

		if skill not in self.skills.keys():
			self.skills[skill] = 0

		amt = (10 + floor(10 * (self.get_skill_level(skill) ** 0.5)))
		if "two-handed" in skill:
			amt *= 2

		self.skills[skill] += amt
		self.is_dirty = True

	def get_combat_rolls(self, weapon: Optional[Weapon], creature: Creature) -> CombinedRoll:
		"""Returns a CombinedRoll for the given weapon's attack and damage rolls."""

		bonus = self.get_skill_bonus("unarmed" if weapon is None else weapon.skill)
		attack = AttackRoll(skill_bonus=bonus[0])
		damage = DamageRoll(
			dice=Dice.d4() if weapon is None else Dice.from_ndn(weapon.attack),
			weapon_bonus=0 if weapon is None else weapon.bonus,
			skill_bonus=bonus[1]
		)
		return CombinedRoll(attack, damage, creature.dodge)

	def do_attack(self, creature: Creature) -> Tuple[str, int]:
		"""
		Performs an attack against the given creature, without modifying the monster's attributes.

		Returns a tuple containing the attack message and the total damage done.
		"""

		two_handed = self.left_hand and self.left_hand.is_2handed
		left = self.get_combat_rolls(self.left_hand, creature)
		right: Optional[CombinedRoll] = None if two_handed else self.get_combat_rolls(self.right_hand, creature)
		raw_dmg = left.result + (right.result if right else 0)
		t_dmg = 0 if left.isMiss and (right is None or right and right.isMiss) else max(1, raw_dmg - creature.defense)

		msg = f"{self.member.mention}'s attack:```diff\nAttack vs Dodge ({creature.dodge}): " \
			f"\n{'-' if left.isMiss else '+'}    {' Left' if right else 'Two-Handed'}: {left.attack} " \
			f"({left.get_hit_string()})"
		msg += f"\n{'-' if right.isMiss else '+'}    Right: {right.attack} ({right.get_hit_string()})" if right else ""

		if not left.isMiss or (right and not right.isMiss):
			msg += f"\n\nDamage:\n{'-' if left.isMiss else '+'}    {' Left' if right else 'Two-Handed'}:" \
				f" {left.damage} * {'0' if left.isMiss else '2' if left.isCritical else '1'} = {left.result}"
			msg += f"\n{'-' if right.isMiss else '+'}    Right: {right.damage} * " \
				f"{'0' if right.isMiss else '2' if right.isCritical else '1'} = {right.result}" if right else ""

			if not left.isMiss:
				self.gain_skill_experience(self.left_hand.skill if self.left_hand else "unarmed")

			if right and not right.isMiss:
				self.gain_skill_experience(self.right_hand.skill if self.right_hand else "unarmed")

			msg += f"\n\nTotal ({raw_dmg}) vs Defense ({creature.defense}) = {t_dmg}"

		msg += "```\n"
		self.update_roll_counts(left, right)
		return msg, t_dmg

	def get_profile(self, guild_name: str) -> Embed:
		"""Returns a discord Embed for the player's profile."""

		embed = Embed(
			title=f"Player Profile",
			description=f"for {self.name} on {guild_name}",
			color=0x00ffff
		)
		fields = [
			("Equipped", "---------------------------------------------------", False),
			("Left Hand", "None" if self.left_hand is None else f"{self.left_hand.get_full_name()}", True),
			("Right Hand", "None" if self.right_hand is None else f"{self.right_hand.get_full_name()}", True),
			("\u200b", "\u200b", False)
		]

		for slot, item in self.equip_slots.items():
			if item is not None:
				fields.append((slot.capitalize(), item.get_full_name(), True))

		fields += [
			("\u200b", "\u200b", False),
			("Stats", "---------------------------------------------------", False),
			("Left Hand", f"{self.left_hand.attack} + {self.left_hand.bonus}" if self.left_hand is not None
				else "1d4", True),
			("Right Hand", f"{self.right_hand.attack} + {self.right_hand.bonus}" if self.right_hand is not None
				else "1d4", True),
			("\u200b", "\u200b", True),
			("Defense", self.defense, True),
			("Dodge", self.dodge, True),
			("Health", f"{self.health} / {self.health_max}", True),
			("\u200b", "\u200b", False),
			("General", "---------------------------------------------------", False),
			("Gender", self.gender.lower(), True),
			("Pronouns", '/'.join(self.pronouns.values()), True),
			("\u200b", "\u200b", True),
			("Clarks", f'{self.clarks:,}', True),
			("Weight", f'{self.get_weight():,} / {self.weight_limit:,}', True),
			("\u200b", "\u200b", True),
			("Joined", self.joined, False)
		]

		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)

		return embed

	def get_skill_display(self) -> Embed:
		embed = Embed(
			title="Skills",
			description=f'for {self.name}',
			color=0x00ffff
		)

		fields = []

		for skill in self.skills.keys():
			bonuses = self.get_skill_bonus(skill)
			msg = f"Current XP: {self.skills[skill]:,}\nAttack Bonus: {bonuses[0]}\nDamage Bonus: {bonuses[1]}"
			fields.append((f"{skill} ({self.get_skill_level(skill)})", msg, True))

		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)

		return embed

	def get_chart_attacks(self) -> Tuple[Embed, File]:
		"""Returns a discord Embed and File for the player's natural rolls."""

		embed = Embed(
			title=f"d20 Rolls",
			description=f'for {self.name}',
			color=0x00ffff
		)

		rolls = 0
		total = 0
		for idx, count in enumerate(self.rolls['d20']):
			rolls += count
			total += (idx + 1) * count

		mean = total / rolls if rolls > 0 else 0

		embed.add_field(name="Count", value=f"{rolls:,}", inline=True)
		embed.add_field(name="Mean", value=f"{mean:.2f}", inline=True)

		cyan = (0., 1., 0.7, 1.)

		series = pandas.Series(self.rolls['d20'], index=range(1, 21), dtype='int')
		ax = series.plot(kind='bar')
		ax.set_xlabel('Rolls')
		ax.set_ylabel('Count')
		ax.xaxis.label.set_color(cyan)
		ax.yaxis.label.set_color(cyan)
		ax.set_ybound(lower=0)
		ax.tick_params(axis='both', colors=cyan)
		ax.grid(True, axis='y', color=cyan, alpha=0.25)
		for spine in ax.spines.values():
			spine.set_color(cyan)

		buffer = BytesIO()
		plt.savefig(buffer, format='png', transparent=True)
		plt.close()
		buffer.seek(0)
		file = File(buffer, filename='plot.png')
		embed.set_image(url="attachment://plot.png")

		return embed, file

	def get_weight(self):
		"""Returns the cumulative weight of the player's inventory."""

		return self.inventory.get_weight()

	def give_item(self, item: Item) -> bool:
		"""
		Adds an item to the player's inventory, if they can afford the weight.

		Returns a boolean value indicating if the item was added.
		"""

		if self.get_weight() + item.get_weight() > self.weight_limit:
			return False

		self.inventory.add(item)
		self.is_dirty = True
		return True

	def take_item(self, item: Item, count: int = 1) -> Optional[Item]:
		"""
		Removes an item from the player's inventory, if present.

		Returns the item that was found and removed, or None if the item was not found.
		"""

		if item == self.inventory[item.id]:
			if item == self.left_hand:
				self.disarm_left()
			elif item == self.right_hand:
				self.disarm_right()

			self.inventory.remove(item, count)
			self.is_dirty = True
			return item
		return None

	def get_inventory(self) -> str:
		"""Returns a string containing a formatted display of the player's inventory."""

		msg = ''
		inv = self.inventory.all()
		for idx, item in enumerate(inv):
			msg += f"\n{idx}: {item.get_full_name()}" \
				f"{' [left hand]' if item == self.left_hand else ''}{' [right hand]' if item == self.right_hand else ''}"

		if len(msg) == 0:
			msg = '\nYou have no items.'

		return msg

	def sell(self, item: Item, count: int = 1, all: bool = False) -> str:
		"""
		Sells the given item if the player has it.
		"""

		if item is None:
			return "No item was specified."

		if all:
			count = item.count

		if count is None:
			count = 1

		value = item.unit_value * count
		sold = self.take_item(item, count)

		if sold:
			self.clarks += value
			return f"You sold {item.get_full_name(count)} for {value} clark{'s' if value != 1 else ''}."

		return f"Item not found."

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		self.is_dirty = True
		if was_alive and self.is_dead():
			return f"{self.name} crumples to the ground lifelessly!"

		if not was_alive and not self.is_dead():
			return f"{self.member.mention} suddenly gasps raggedly as life returns to {self.pronouns['object']}!"

		return ""

	def to_dict(self) -> dict:
		"""Returns a dictionary of the player's attributes."""

		d = {
			'_id': self.id,
			'user_id': self.user_id,
			'guild_id': self.guild_id,
			'name': self.name,
			'defense': self.defense,
			'dodge': self.dodge,
			'health': self.health,
			'health_max': self.health_max,
			'weight_limit': self.weight_limit,
			'joined': self.joined,
			'clarks': self.clarks,
			'left_hand': self.left_hand.id if self.left_hand is not None else None,
			'right_hand': self.right_hand.id if self.right_hand is not None else None,
			'rolls': self.rolls,
			'skills': self.skills,
			'gender': self.gender,
			'pronouns': ','.join(list(self.pronouns.values())),
			'items': self.inventory.to_list(),
			'equip_slots': {}
		}

		for slot, item in self.equip_slots.items():
			d['equip_slots'][slot] = item.id if item is not None else None

		if self.id is None:
			del d['_id']

		return d

	@classmethod
	def from_dict(cls, p: dict) -> Optional["Player"]:
		if p is None:
			return None

		player = cls(
			pid=p['_id'],
			gid=p['guild_id'],
			uid=p['user_id'],
			weight_limit=p['weight_limit'],
			joined=p['joined'],
			clarks=p['clarks'],
			defense=p['defense'],
			dodge=p['dodge'],
			health=p['health'],
			health_max=p['health_max'],
			inventory=Inventory.from_list(p['items']),
			rolls=p['rolls'],
			skills=p['skills'],
			gender=p['gender'] if 'gender' in p.keys() else None,
			pronouns=p['pronouns'] if 'pronouns' in p.keys() else None,
			armor_slots=p['equip_slots'] if 'equip_slots' in p.keys() else None
		)

		if player.inventory[str(p['left_hand'] if 'left_hand' in p.keys() else p['leftHand'])] is not None:
			player.equip_left(player.inventory[str(p['left_hand'] if 'left_hand' in p.keys() else p['leftHand'])])

		if player.inventory[str(p['right_hand'] if 'right_hand' in p.keys() else p['rightHand'])] is not None:
			player.equip_right(player.inventory[str(p['right_hand'] if 'right_hand' in p.keys() else p['rightHand'])])

		return player
