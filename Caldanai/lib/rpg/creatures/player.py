from math import floor
from typing import Dict, Tuple, Optional, List, Union
from io import BytesIO

import pandas
import matplotlib.pyplot as plt

from discord import Member, Embed, File

from Caldanai.lib.rpg import parse
from Caldanai.lib.rpg.creatures import Creature
from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.helpers.dice import Dice
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, DamageTypes
from Caldanai.lib.rpg.helpers.parser import item_list_to_string
from Caldanai.lib.rpg.helpers.rollData import AttackRoll, DamageRoll, CombinedRoll
from Caldanai.lib.rpg.inventory import Inventory, Item, Consumable, Armor, Usable
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.stackables import Stackable
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from datetime import datetime


class Player(Creature):
    """A simple Player object for tracking player data"""

    def __init__(
        self,
        *,
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
        equip_slots: Optional[Dict[str, Item]] = None,
        last_active: Optional[datetime] = None,
        health_regen: Optional[int] = 0,
    ):
        super().__init__(
            name=None,
            atk=None,
            defense=defense,
            dodge=dodge,
            health=health,
            health_max=health_max,
            gender=gender,
            pronouns=pronouns,
        )
        self.id = pid
        self.guild_id = gid
        self.user_id = uid
        self.member: Optional[Member] = None
        self.weight_limit = weight_limit or 100
        self.joined = joined
        self.last_active = last_active
        self.clarks = clarks
        self.inventory = inventory or Inventory()
        self.skills = skills or {}
        self.is_dirty = False
        self.rolls = rolls or {
            "d4": [0] * 4,
            "d6": [0] * 6,
            "d8": [0] * 8,
            "d10": [0] * 10,
            "d12": [0] * 12,
            "d20": [0] * 20,
        }
        self.health_regen = health_regen
        self.equip_slots: Dict[str, Optional[Equipment]] = {}

        for slot in EquipmentSlots:
            if not EquipmentSlots.exclude_from_output(slot.name):
                exists = equip_slots and slot.name in equip_slots.keys()
                self.equip_slots[slot.name] = self.inventory[str(equip_slots[slot.name])] if exists else None

    def __eq__(self, o):
        return isinstance(o, Player) and self.user_id == o.user_id and self.guild_id == o.guild_id

    def __hash__(self):
        return hash((self.user_id, self.guild_id))

    def apply_damage(
        self,
        amount: int,
        dmg_type: "Optional[DamageTypes]" = None,
        target_part: "Optional[BodyPart]" = None,
    ) -> str:
        was_alive = self.health > 0
        super().apply_damage(amount, dmg_type=dmg_type, target_part=target_part)
        self.is_dirty = True
        if was_alive and self.is_dead():
            return parse("@1 crumples to the ground lifelessly!", self)

        if not was_alive and not self.is_dead():
            mention = f"<@!{self.member.id}>" if self.member is not None else self.name
            return parse(f"{mention} suddenly gasps raggedly as life returns to @1o!", self)

        return ""

    def get_attack_sources(self) -> List["AttackSource"]:
        """Returns attack sources from the player's equipped weapons.

        Produces one source for the left/two-handed slot and (if not two-handed)
        one for the right. Uses WeaponAttackSource when a weapon is equipped
        and UnarmedAttackSource otherwise.
        """
        from Caldanai.lib.rpg.combat.attack_source import (
            AttackSource,
            UnarmedAttackSource,
            WeaponAttackSource,
        )

        lh: Weapon = self.equip_slots[EquipmentSlots.LEFT_HELD.name]
        rh: Weapon = self.equip_slots[EquipmentSlots.RIGHT_HELD.name]
        two_handed = lh and EquipmentSlots.MULTI_SLOT & lh.slots

        sources: List[AttackSource] = []
        primary_label = "Two-Handed" if two_handed else "Left"
        if lh:
            sources.append(WeaponAttackSource(lh, label=primary_label))
        else:
            sources.append(UnarmedAttackSource(label=primary_label))

        if not two_handed:
            if rh:
                sources.append(WeaponAttackSource(rh, label="Right"))
            else:
                sources.append(UnarmedAttackSource(label="Right"))

        return sources

    def _on_attack_resolved(self, source, result) -> None:
        """Grants skill XP on hits and updates roll counts for each resolved attack."""
        if result.hit():
            self.gain_skill_experience(source.skill)
        self.update_roll_counts(result.combined)

    def replace_equipment(self, item: Equipment, slot_name: str) -> Tuple[bool, Equipment]:
        """
        Replaces the item in the given slot with the provided item.

        :param item: The item to equip.
        :param slot_name: The slot name to which it should equip.
        :return: A tuple containing a boolean for success/fail and the item replaced, if any.
        """
        replaced = None
        if self.equip_slots[slot_name]:
            replaced = self.equip_slots[slot_name]
            self.remove(self.equip_slots[slot_name])
        self.equip_slots[slot_name] = item
        return True, replaced

    def equip(self, item: Equipment, slot: EquipmentSlots = None) -> Tuple[bool, str]:
        """
        Attempts to auto-equip an item to a slot if no slot is provided, otherwise attempts to equip to the
        provided slot.

        :param item: The item to equip.
        :param slot: The slot(s) to which it should equip.
        :return: A tuple containing a boolean for success/fail and a string indicating items replaced or error message.
        """

        dirty = False
        msg = ""

        # First ensure the item is not already equipped.
        for i in self.equip_slots.values():
            if i == item:
                return False, "Item already equipped."

        # Equip to all possible slots if multi-slot is flagged.
        if item.slots & EquipmentSlots.MULTI_SLOT:
            removed = []
            for s in EquipmentSlots:
                if s & item.slots and s.name in self.equip_slots:
                    d, replaced = self.replace_equipment(item, s.name)
                    if d:
                        dirty = True

                    if replaced:
                        removed.append(replaced)

            if dirty and removed:
                msg = item_list_to_string(removed)

            else:
                msg = "Unable to auto-equip: Multi-slot item matched no equipment slots."

        # Equip to the first possible slot, if no slot was specified.
        elif slot is None or (slot.name and EquipmentSlots.exclude_from_output(slot.name)):
            for key, value in self.equip_slots.items():
                if item.slots & EquipmentSlots[key]:
                    dirty, replaced = self.replace_equipment(item, key)
                    if replaced:
                        msg = replaced.get_full_name()
                    break

            if not dirty:
                msg = (
                    "Unable to auto-equip: None of the slots that the item could fill are empty. Either specify "
                    "the slot, or unequip the item occupying the desired slot."
                )

        # Equip to the specified slot.
        else:
            if slot & item.slots and slot.name:
                dirty, replaced = self.replace_equipment(item, slot.name)
                if replaced:
                    msg = replaced.get_full_name()

            if not dirty:
                msg = "Unable to equip: The item does not fit that slot."
        if dirty:
            self.is_dirty = True
            self.health = min(self.health, self.get_health_max())

        return dirty, msg

    @classmethod
    def from_dict(cls, p: dict) -> Optional["Player"]:
        if p is None:
            return None

        player = cls(
            pid=p["_id"],
            gid=p["guild_id"],
            uid=p["user_id"],
            weight_limit=p["weight_limit"],
            joined=p["joined"],
            clarks=p["clarks"],
            defense=p["defense"],
            dodge=p["dodge"],
            health=p["health"],
            health_max=p["health_max"],
            inventory=Inventory.from_list(p["items"]),
            rolls=p["rolls"],
            skills=p["skills"],
            gender=p["gender"] if "gender" in p.keys() else None,
            pronouns=p["pronouns"] if "pronouns" in p.keys() else None,
            equip_slots=p["equip_slots"] if "equip_slots" in p.keys() else None,
            last_active=p["last_active"] if "last_active" in p.keys() else None,
            health_regen=p.get("health_regen", 0),
        )

        eq = p.get("equip_slots") or {}
        left_id = eq.get(EquipmentSlots.LEFT_HELD.name)
        right_id = eq.get(EquipmentSlots.RIGHT_HELD.name)
        left = player.inventory[str(left_id)] if left_id else None
        right = player.inventory[str(right_id)] if right_id else None

        if left and isinstance(left, Weapon):
            player.equip(left, EquipmentSlots.LEFT_HELD)

        if right and isinstance(right, Weapon):
            player.equip(right, EquipmentSlots.RIGHT_HELD)

        return player

    def gain_skill_experience(self, skill: str) -> None:
        """Applies experience gain for the given skill."""

        if skill not in self.skills.keys():
            self.skills[skill] = 0

        skill_level = self.get_skill_level(skill)

        if skill_level < 20:
            amt = 10 + floor(10 * (skill_level**0.5))
            if "two-handed" in skill:
                amt *= 2

            self.skills[skill] += amt
            self.is_dirty = True

    def get_armor_bonuses(self, *names: str) -> Dict[str, int]:
        """
        Returns a dictionary containing the sums of all bonuses granted by equipment.
        :param names: If you wish to retrieve specific bonuses, provide their names.
        :return: A dictionary containing the sum of bonuses from all equipment worn.
        """

        result: Dict[str, int] = {}
        items_checked = []
        for slot, item in self.equip_slots.items():
            if isinstance(item, Armor) and item not in items_checked:
                items_checked.append(item)
                for bonus, value in item.bonuses.items():
                    if names and bonus not in names:
                        continue

                    if bonus not in result.keys():
                        result[bonus] = value
                    else:
                        result[bonus] += value

        return result

    def get_chart_attacks(self) -> Tuple[Embed, File]:
        """Returns a discord Embed and File for the player's natural rolls."""

        embed = Embed(title=f"d20 Rolls", description=f"for {self.name}", color=0x00FFFF)

        rolls = 0
        total = 0
        for idx, count in enumerate(self.rolls["d20"]):
            rolls += count
            total += (idx + 1) * count

        mean = total / rolls if rolls > 0 else 0

        embed.add_field(name="Count", value=f"{rolls:,}", inline=True)
        embed.add_field(name="Mean", value=f"{mean:.2f}", inline=True)

        cyan = (0.0, 1.0, 0.7, 1.0)

        series = pandas.Series(self.rolls["d20"], index=range(1, 21), dtype="int")
        ax = series.plot(kind="bar")
        ax.set_xlabel("Rolls")
        ax.set_ylabel("Count")
        ax.xaxis.label.set_color(cyan)
        ax.yaxis.label.set_color(cyan)
        ax.set_ybound(lower=0)
        ax.tick_params(axis="both", colors=cyan)
        ax.grid(True, axis="y", color=cyan, alpha=0.25)
        for spine in ax.spines.values():
            spine.set_color(cyan)

        buffer = BytesIO()
        plt.savefig(buffer, format="png", transparent=True)
        plt.close()
        buffer.seek(0)
        file = File(buffer, filename="plot.png")
        embed.set_image(url="attachment://plot.png")

        return embed, file

    def get_defense(self) -> int:
        """Tallies the total defense value for the given player."""
        d = self.get_armor_bonuses("defense")
        if "defense" in d.keys():
            return max(0, d["defense"] + self.defense)
        return self.defense

    def get_dodge(self) -> int:
        """Tallies the total dodge value for the given player."""
        d = self.get_armor_bonuses("dodge")
        if "dodge" in d.keys():
            return max(0, d["dodge"] + self.dodge)
        return self.dodge

    def get_health_max(self) -> int:
        """Tallies the total max health value for the given creature."""
        d = self.get_armor_bonuses("health_max")
        if "health_max" in d.keys():
            return max(0, d["health_max"] + self.health_max)
        return self.health_max

    def get_equipment(self, guild_name: str, show_all: bool = False) -> Embed:
        """Returns a discord embed for the player's equipment slots."""
        embed = Embed(title=f"Player Equipment", description=f"for {self.name} on {guild_name}", color=0x00FFFF)

        fields = [
            ("Equipped", "---------------------------------------------------", False),
        ]

        for slot, item in self.equip_slots.items():
            if not EquipmentSlots.exclude_from_output(slot):
                if item is None:
                    if show_all:
                        fields.append((slot, "None", True))
                else:
                    fields.append((slot, item.get_full_name(), True))

        for f, v, i in fields:
            embed.add_field(name=f, value=v, inline=i)

        return embed

    def get_inventory(self, filtr: str = None) -> str:
        """Returns a string containing a formatted display of the player's inventory."""

        msg = ""
        inv = self.inventory.filter(filtr)
        all_items = self.inventory.all()

        for item in inv:
            if item is None:
                continue
            try:
                absolute_idx = all_items.index(item)
            except ValueError:
                continue
            msg += f"\n{absolute_idx + 1}: {item.get_full_name()}"
            for s, i in self.equip_slots.items():
                msg += f"{' [' + s + ']' if i == item and not EquipmentSlots.exclude_from_output(s) else ''}"

        if len(msg) == 0 and not filtr:
            msg = "\nYou have no items."
        elif len(msg) == 0 and filtr:
            msg = "\nNo items matched the provided filter."

        return msg

    def get_profile(self, guild_name: str) -> Embed:
        """Returns a discord Embed for the player's profile."""

        embed = Embed(title=f"Player Profile", description=f"for {self.name} on {guild_name}", color=0x00FFFF)

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
            ("Pronouns", "/".join(self.pronouns.values()), True),
            ("\u200b", "\u200b", True),
            ("Clarks", f"{self.clarks:,}", True),
            ("Weight", f"{self.get_weight():,} / {self.weight_limit:,}", True),
            ("\u200b", "\u200b", True),
            ("Joined", self.joined, False),
        ]

        for f, v, i in fields:
            embed.add_field(name=f, value=v, inline=i)

        return embed

    def get_skill_bonus(self, skill: str) -> Tuple[int, int]:
        """Returns a tuple containing the attack bonus and damage bonus for a given skill."""

        atk = floor(self.get_skill_level(skill) / 2)
        dmg = floor(self.get_skill_level(skill) / 4)
        return atk, dmg

    def get_skill_display(self) -> Embed:
        embed = Embed(title="Skills", description=f"for {self.name}", color=0x00FFFF)

        fields = []

        for skill in self.skills.keys():
            bonuses = self.get_skill_bonus(skill)
            msg = f"Current XP: {self.skills[skill]:,}\nAttack Bonus: {bonuses[0]}\nDamage Bonus: {bonuses[1]}"
            fields.append((f"{skill} ({self.get_skill_level(skill)})", msg, True))

        for f, v, i in fields:
            embed.add_field(name=f, value=v, inline=i)

        return embed

    def get_skill_level(self, skill: str) -> int:
        """Return the skill level for the given skill."""

        if skill not in self.skills.keys():
            return 1

        return min(20, floor((25 + (5 * (125 + self.skills[skill])) ** 0.5) / 50))

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

    def remove(self, item: Equipment) -> str:
        """
        Removes an item from all slots that it occupies.

        :param item: The item to remove.
        :return: A string representing the result of the removal.
        """

        dirty = False
        msg = ""
        removed = []

        if item is None:
            return "Nothing to remove."

        for s in EquipmentSlots:
            if not EquipmentSlots.exclude_from_output(s.name) and s & item.slots and self.equip_slots[s.name] == item:
                self.equip_slots[s.name] = None
                removed.append(s.name)
                dirty = True

        if dirty:
            msg = f"Removed {item.get_full_name()}."
            self.is_dirty = True
            self.health = min(self.health, self.get_health_max())

        else:
            msg = f"{item.get_full_name().capitalize()} does not seem to be equipped."

        return msg

    def sell(self, item: Item, count: int = 1, _all: bool = False) -> Tuple[str, int]:
        """
        Sells the given item if the player has it.
        """

        if item is None:
            return "No item was specified.", 0

        sold = False
        value = 0

        if count is None or count == 0:
            count = 1

        if isinstance(item, Stackable):
            if _all:
                count = item.count

            value = item.unit_value * count
            sold = self.take_item(item, count)

        else:
            value = item.unit_value
            sold = self.take_item(item)

        name = item.get_full_name(count) if isinstance(item, Stackable) else item.get_full_name()

        if sold:
            self.clarks += value
            return f"You sold {name} for {value} clark{'s' if value != 1 else ''}.", value

        return f"Item not found", 0

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

    def on_hugged(self, actor: Creature, invocation: str) -> str:
        """
        Gets a creature's reaction to being hugged.

        :param actor: The Creature object initiating the hug.
        :param invocation: The calling command, such as 'hug', 'cuddle', or 'snuggle'.
        :return: A string representing the creature's reaction.
        """
        if self.is_dead():
            return parse("@1c's corpse rolls lifelessly in @2's arms.", self, actor)
        return parse("@1 glances at @2 and sidesteps @2a hug.", self, actor)

    def to_dict(self) -> dict:
        """Returns a dictionary of the player's attributes."""

        d = {
            "_id": self.id,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "name": self.name,
            "defense": self.defense,
            "dodge": self.dodge,
            "health": self.health,
            "health_max": self.health_max,
            "weight_limit": self.weight_limit,
            "joined": self.joined,
            "clarks": self.clarks,
            "rolls": self.rolls,
            "skills": self.skills,
            "gender": self.gender,
            "pronouns": ",".join(list(self.pronouns.values())[:-1]),
            "items": self.inventory.to_list(),
            "equip_slots": {},
            "last_active": self.last_active,
            "health_regen": self.health_regen,
        }

        for slot, item in self.equip_slots.items():
            if not EquipmentSlots.exclude_from_output(slot):
                d["equip_slots"][slot] = item.id if item else None

        if self.id is None:
            del d["_id"]

        return d

    def update_roll_count(self, sides: int, value: int):
        """Updates the player's roll count for an individual die roll."""

        if sides <= 1 or 1 > value or value > sides or f"d{sides}" not in self.rolls.keys():
            return

        self.rolls[f"d{sides}"][value - 1] += 1
        self.is_dirty = True

    def update_roll_counts(self, *rolls: Optional[CombinedRoll]):
        """Updates the player's attack and damage averages."""

        for roll in rolls:
            if roll and roll.attack:
                self.update_roll_count(20, roll.attack.rolls[0])
                if not roll.isMiss:
                    for r in roll.damage.rolls:
                        self.update_roll_count(roll.damage.sides, r)

    def use_item(self, item: Union[Usable, Consumable]) -> str:
        msg = "There does not seem to be a way to do that."
        if item and isinstance(item, Consumable):
            msg, any_left = item.use(self)
            if not any_left:
                self.inventory.remove(item)
                self.is_dirty = True

        elif item and isinstance(item, Usable):
            msg = item.use(self)

        return msg
