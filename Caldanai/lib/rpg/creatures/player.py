from math import floor
from typing import Dict, Tuple, Optional, List, Union
from io import BytesIO

import pandas
import matplotlib.pyplot as plt

from discord import Member, Embed, File

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll, CombinedRoll
from Caldanai.lib.rpg.inventory import Inventory, Item, Consumable, Armor
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon
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
			defense: Optional[int] = 6,
			dodge: Optional[int] = 6,
			health: Optional[int] = 20,
			health_max: Optional[int] = 20,
			inventory: Optional[Inventory] = None,
			rolls: Optional[Dict[str, List[int]]] = None,
			skills: Optional[Dict[str, int]] = None,
			gender: Optional[str] = None,
			pronouns: Optional[str] = None,
			equip_slots: Optional[Dict[str, Item]] = None
	):
		super().__init__(
			name=None, atk=None, defense=defense, dodge=dodge, health=health,
			health_max=health_max, gender=gender, pronouns=pronouns
		)
		self.id = pid
		self.guild_id = gid
		self.user_id = uid
		self.member: Optional[Member] = None
		self.weight_limit = weight_limit or 100
		self.joined = joined
		self.clarks = clarks
		self.inventory = inventory or Inventory()
		self.skills = skills or {}
		self.is_dirty = False
		self.rolls = rolls or {
			"d4": [0] * 4, "d6": [0] * 6, "d8": [0] * 8, "d10": [0] * 10, "d12": [0] * 12, "d20": [0] * 20
		}
		self.health_regen = 0
		self.equip_slots: Dict[str, Optional[Equipment]] = {}

		for slot in EquipmentSlots:
			if not EquipmentSlots.exclude_from_output(slot.name):
				exists = equip_slots and slot.name in equip_slots.keys()
				self.equip_slots[slot.name] = self.inventory[str(equip_slots[slot.name])] if exists else None

	def __eq__(self, o):
		return isinstance(o, Player) and self.user_id == o.user_id and self.guild_id == o.guild_id

	def remove(self, slots: EquipmentSlots) -> str:
		"""Removes any items from the given equipment slots, if any are present."""

		dirty = False
		msg = ""

		if not slots:
			msg = "Unable to remove item: No slots provided."

		else:
			_slots = [s.name for s in EquipmentSlots if s in slots]
			if EquipmentSlots.MULTI_SLOT in _slots:
				removed = []
				_slots.remove(EquipmentSlots.MULTI_SLOT)
				for name in _slots:
					self.equip_slots[name] = None
					removed.append(name)
					dirty = True

				if dirty:
					msg = "Removed multi-slot item from " + '|'.join(removed)
				else:
					msg = "Unable to remove multi-slot item: No slots provided with multi-slot flag."

			else:
				if len(_slots) == 1:
					self.equip_slots[_slots[0]] = None
					dirty = True
					msg = f"Removed single-slot item from {_slots[0]}."

				if not dirty:
					msg = "Unable to remove single-slot item: Ambiguous slot selection provided."

		if dirty:
			self.is_dirty = True
			self.health = min(self.health, self.get_health_max())

		return msg

	def equip(self, item: Equipment, slot: EquipmentSlots = None) -> str:
		"""
		Attempts to auto-equip an item to a slot if no slot is provided, otherwise attempts to equip to the
		provided slot.

		:param item: The item to equip.
		:param slot: The slot(s) to which it should equip.
		:return: A string indicating the result of the attempt.
		"""

		dirty = False
		msg = parse(f"@1 has equipped {item.get_full_name()}", self)

		if item.slots & EquipmentSlots.MULTI_SLOT:
			for s in EquipmentSlots:
				if s & item.slots:
					self.equip_slots[s.name] = item
					dirty = True
			if not dirty:
				msg = "Unable to auto-equip: Multi-slot item matched no equipment slots."

		elif slot is None:
			for key, value in self.equip_slots.items():
				if item.slots & EquipmentSlots[key] and value is None:
					self.equip_slots[key] = item
					dirty = True
					break
			if not dirty:
				msg = "Unable to auto-equip: Either specify the equipment slot, or un-equip the item from the " \
					"desired slot."
		else:
			if slot & item.slots and slot.name:
				self.equip_slots[slot.name] = item
				dirty = True

			if not dirty:
				msg = "Unable to equip: The item does not fit in that slot." \

		if dirty:
			self.is_dirty = True
			self.health = min(self.health, self.get_health_max())

		return msg

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

		return min(20, floor((25 + (5 * (125 + self.skills[skill])) ** 0.5) / 50))

	def gain_skill_experience(self, skill: str) -> None:
		"""Applies experience gain for the given skill."""

		if skill not in self.skills.keys():
			self.skills[skill] = 0

		skill_level = self.get_skill_level(skill)

		if skill_level < 20:
			amt = (10 + floor(10 * (skill_level ** 0.5)))
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

		lh: Weapon = self.equip_slots[EquipmentSlots.LEFT_HELD.name]
		rh: Weapon = self.equip_slots[EquipmentSlots.RIGHT_HELD.name]
		two_handed = lh and EquipmentSlots.MULTI_SLOT & lh.slots
		left = self.get_combat_rolls(lh, creature)
		right: Optional[CombinedRoll] = None if two_handed else self.get_combat_rolls(rh, creature)
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
				self.gain_skill_experience(lh.skill if lh else "unarmed")

			if right and not right.isMiss:
				self.gain_skill_experience(rh.skill if rh else "unarmed")

			msg += f"\n\nTotal ({raw_dmg}) vs Defense ({creature.defense}) = {t_dmg}"

		msg += "```\n"
		self.update_roll_counts(left, right)
		return msg, t_dmg

	def get_defense(self) -> int:
		"""Tallies the total defense value for the given player."""
		total = self.defense
		for item in self.equip_slots.values():
			if item and isinstance(item, Armor) and item.bonuses and 'defense' in item.bonuses.keys():
				total += item.bonuses['defense']

		return max(0, total)

	def get_dodge(self) -> int:
		"""Tallies the total dodge value for the given player."""
		total = self.dodge
		for item in self.equip_slots.values():
			if item and isinstance(item, Armor) and item.bonuses and 'dodge' in item.bonuses.keys():
				total += item.bonuses['dodge']

		return max(0, total)

	def get_health_max(self) -> int:
		"""Tallies the total max health value for the given creature."""
		total = self.health_max
		for item in self.equip_slots.values():
			if item and isinstance(item, Armor) and item.bonuses and 'health_max' in item.bonuses.keys():
				total += item.bonuses['health_max']

		return max(1, total)

	def get_equipment(self, guild_name: str) -> Embed:
		"""Returns a discord embed for the player's equipment slots."""
		embed = Embed(
			title=f"Player Equipment",
			description=f"for {self.name} on {guild_name}",
			color=0x00ffff
		)

		fields = [
			("Equipped", "---------------------------------------------------", False),
		]

		for slot, item in self.equip_slots.items():
			if not EquipmentSlots.exclude_from_output(slot):
				#if slot == EquipmentSlots.RIGHT_HELD.name \
				#	or slot == EquipmentSlots.LEFT_HELD.name \
				#	and EquipmentSlots.MULTI_SLOT in item.slots:
				#	continue
				fields.append((slot, item.get_full_name() if item else "None", True))

		for f, v, i in fields:
			embed.add_field(name=f, value=v, inline=i)

		return embed

	def get_profile(self, guild_name: str) -> Embed:
		"""Returns a discord Embed for the player's profile."""

		embed = Embed(
			title=f"Player Profile",
			description=f"for {self.name} on {guild_name}",
			color=0x00ffff
		)

		lh: Weapon = self.equip_slots[EquipmentSlots.LEFT_HELD.name]
		rh: Weapon = self.equip_slots[EquipmentSlots.RIGHT_HELD.name]

		fields = [
			("\u200b", "\u200b", False),
			("Stats", "---------------------------------------------------", False),
			("Left Hand", f"{lh.attack} + {lh.bonus}" if lh else "1d4", True),
			("Right Hand", f"{rh.attack} + {rh.bonus}" if rh else "1d4", True),
			("\u200b", "\u200b", True),
			("Defense", self.get_defense(), True),
			("Dodge", self.get_dodge(), True),
			("Health", f"{self.health} / {self.get_health_max()}", True),
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

		Returns the item that was found and removed, or None if the item was not found or was equipped.
		"""

		if item == self.inventory[item.id] and item not in self.equip_slots.values():
			self.inventory.remove(item, count)
			self.is_dirty = True
			return item
		return None

	def get_inventory(self, filtr: str = None) -> str:
		"""Returns a string containing a formatted display of the player's inventory."""

		msg = ''
		inv = self.inventory.filter(filtr)

		lh = self.equip_slots[EquipmentSlots.LEFT_HELD.name]
		rh = self.equip_slots[EquipmentSlots.RIGHT_HELD.name]

		for idx, item in enumerate(inv):
			msg += f"\n{idx}: {item.get_full_name()}" \
				f"{' [left hand]' if item == lh else ''}{' [right hand]' if item == rh else ''}"

		if len(msg) == 0 and not filtr:
			msg = '\nYou have no items.'
		elif len(msg) == 0 and filtr:
			msg = '\nNo items matched the provided filter.'

		return msg

	def sell(self, item: Item, count: int = 1, _all: bool = False) -> str:
		"""
		Sells the given item if the player has it.
		"""

		if item is None:
			return "No item was specified."

		sold = False
		value = 0

		if _all and isinstance(item, Stackable):
			count = item.count
			value = item.unit_value * count
			sold = self.take_item(item, count)
		elif not count or count == 1:
			value = item.unit_value
			sold = self.take_item(item)

		name = item.get_full_name(count) if isinstance(item, Stackable) else item.get_full_name()

		if sold:
			self.clarks += value
			return f"You sold {name} for {value} clark{'s' if value != 1 else ''}."

		return f"Item not found."

	def apply_damage(self, amount: int) -> str:
		was_alive = self.health > 0
		super().apply_damage(amount)
		self.is_dirty = True
		if was_alive and self.is_dead():
			return parse("@1 crumples to the ground lifelessly!", self)

		if not was_alive and not self.is_dead():
			return parse(f"{self.member.mention} suddenly gasps raggedly as life returns to @1o!", self)

		return ""

	def use_item(self, item: Union[int, str]) -> str:
		if isinstance(item, int):
			_item = self.inventory.get_by_index(item)
		else:
			_item, *_ = self.inventory.filter(item) or (None,)

		if _item and isinstance(_item, Consumable):
			msg, any_left = _item.use(self)
			if not any_left:
				self.inventory.remove(_item)
				self.is_dirty = True
			return msg

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
			'rolls': self.rolls,
			'skills': self.skills,
			'gender': self.gender,
			'pronouns': ','.join(list(self.pronouns.values())[:-1]),
			'items': self.inventory.to_list(),
			'equip_slots': {}
		}

		for slot, item in self.equip_slots.items():
			if not EquipmentSlots.exclude_from_output(slot):
				d['equip_slots'][slot] = item.id if item else None

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
			equip_slots=p['equip_slots'] if 'equip_slots' in p.keys() else None
		)

		left = player.inventory[str(p['equip_slots'][EquipmentSlots.LEFT_HELD.name])]
		right = player.inventory[str(p['equip_slots'][EquipmentSlots.RIGHT_HELD.name])]

		if left and isinstance(left, Weapon):
			player.equip(left, EquipmentSlots.LEFT_HELD)

		if right and isinstance(right, Weapon):
			player.equip(right, EquipmentSlots.RIGHT_HELD)

		return player
