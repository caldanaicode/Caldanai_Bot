from math import floor
from typing import Dict, Tuple, Optional, List, Union

import pandas

from discord import Member, Embed, File

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, DamageTypes, InjuryLevels
from caldanai.lib.rpg.helpers.parser import item_list_to_string
from caldanai.lib.rpg.helpers.plotting import CYAN_ACCENT, fig_to_file, style_axes_dark
from caldanai.lib.rpg.helpers.roll_data import CombinedRoll
from caldanai.lib.rpg.inventory import Inventory, Item, Consumable, Armor, Usable
from caldanai.lib.rpg.inventory.equipment import Equipment
from caldanai.lib.rpg.inventory.stackables import Stackable
from caldanai.lib.rpg.inventory.equipment.weapons import Weapon
from datetime import datetime


# Default humanoid anatomy for all players. Keyed by instance name
# (the persisted identifier) so health overrides can look parts up
# directly. Head and torso are critical (destruction kills outright);
# losing an arm, leg, or eye degrades stats via the emergence system
# but isn't lethal on its own. Persistence only saves each part's
# current health, keyed by instance name, so the schema evolves
# freely if we ever add or rename parts.
# Part spec: (plugin_name, fixed default health_max). Players share
# the same baseline anatomy — the random dice rolls on part plugins
# are kept for monsters (where anatomical variance is a gameplay
# feature) but overridden here so every player starts with the same
# deterministic HP pool per part. Values chosen to roughly match the
# prior rolled averages while landing on cleaner round numbers:
#   head 3d10 (avg 16.5) → 15
#   torso 6d10 (avg 33)  → 30
#   arm 2d8 (avg 9)      → 10
#   leg 2d10 (avg 11)    → 12
#   eye 1d6 (avg 3.5)    → 4
# Per-part armor scaling lands in a follow-up pass; for now the
# body-pool ``health_max`` bonus behavior is unchanged.
_DEFAULT_PARTS: Dict[str, Tuple[str, int]] = {
    "head":      ("head",  15),
    "torso":     ("torso", 30),
    "arm.left":  ("arm",   10),
    "arm.right": ("arm",   10),
    "leg.left":  ("leg",   12),
    "leg.right": ("leg",   12),
    "eye.left":  ("eye",    4),
    "eye.right": ("eye",    4),
}


def _build_default_body_parts() -> List[BodyPart]:
    """Construct a fresh humanoid body-part list at full health, with
    fixed ``health_max`` per part type. Every player gets identical
    starting anatomy so character build is deterministic across
    sessions and consistent across the playerbase.

    DB-persisted ``health_max`` still wins via
    ``_apply_body_parts_health`` (dict-of-dict shape) — players who
    had rolled maxes before this change keep whatever's in their save
    until the next save cycle, after which the deterministic values
    are written back.
    """
    return [
        BodyPart.make(plugin_name, name=instance_name, health_max=default_max)
        for instance_name, (plugin_name, default_max) in _DEFAULT_PARTS.items()
    ]


def _apply_body_parts_health(
    parts: List[BodyPart],
    overrides: Optional[Dict[str, object]],
) -> None:
    """Restore per-part persisted anatomy (``health_max``) and current
    ``health`` from a saved dict, clamped to ``[0, health_max]``.

    Two schemas are accepted for backwards compatibility:

    - **Current (dict-of-dict)**: ``{name: {"health": h, "health_max": hm}}``.
      Both fields are restored; this is the stable form that makes a
      character's anatomy deterministic across sessions.
    - **Legacy (dict-of-int)**: ``{name: h}``. Only current health was
      persisted — ``health_max`` was rerolled on every load, causing
      anatomy drift (and silent HP loss when a reroll came up lower
      than the saved health). Loading this shape applies just the
      current health clamped to the freshly-rolled max; the next save
      writes the new shape, so documents self-migrate in place.

    Unknown keys (renamed / removed parts) are silently ignored so the
    anatomy definition can evolve without bricking old saves.
    """
    if not overrides:
        return
    for part in parts:
        entry = overrides.get(part.name)
        if entry is None:
            continue
        if isinstance(entry, dict):
            # Current shape: restore max first so the health clamp
            # below uses the persisted max, not the fresh roll.
            saved_max = entry.get("health_max")
            if saved_max is not None:
                part.health_max = int(saved_max)
            saved_health = entry.get("health")
            if saved_health is not None:
                part.health = max(0, min(part.health_max, int(saved_health)))
        else:
            # Legacy shape: int health only, clamp to freshly-rolled max.
            part.health = max(0, min(part.health_max, int(entry)))


class Player(Creature):
    """A simple Player object for tracking player data"""

    def __init__(
        self,
        *,
        pid: Optional[int] = None,
        gid: Optional[int] = None,
        cid: Optional[int] = None,
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
        body_parts_health: Optional[Dict[str, int]] = None,
        social: Optional[Dict[str, object]] = None,
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
        # Humanoid anatomy. Every player gets the same deterministic
        # starting anatomy (see ``_DEFAULT_PARTS``), so there's no
        # symmetrization step — left/right pairs are identical by
        # construction. Persisted per-part health / health_max from
        # the DB still wins via ``_apply_body_parts_health``.
        self.body_parts = _build_default_body_parts()
        _apply_body_parts_health(self.body_parts, body_parts_health)
        self.uses_article = False  # "Caels", not "the Caels"
        self.id = pid
        self.guild_id = gid
        self.channel_id = cid  # game-scoped: which channel's game this player belongs to
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
        # Social-warmth preferences. See
        # ``caldanai.lib.rpg.helpers.warmth`` for shape / accessors.
        # Empty dict signals "use system defaults" — populated maps
        # are the only thing that gets written to the DB, so
        # never-tuned players don't grow a noisy field.
        self.social: Dict[str, object] = social if isinstance(social, dict) else {}
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
    ) -> Optional[str]:
        was_alive = self.health > 0
        super().apply_damage(
            amount,
            dmg_type=dmg_type,
            target_part=target_part,
        )
        self.is_dirty = True
        if was_alive and self.is_dead():
            return parse("@1 crumples to the ground lifelessly!", self)

        if not was_alive and not self.is_dead():
            mention = f"<@!{self.member.id}>" if self.member is not None else self.name
            return parse(f"{mention} suddenly gasps raggedly as life returns to @1o!", self)

        return ""

    def is_injured(self) -> bool:
        """Returns True if the player's body HP is below max or any
        body part's HP is below its max. Consolidates four previously
        inline predicates in the cogs (``_is_injured`` in info,
        ``_needs_healing`` / ad-hoc ``needs_body / needs_part`` checks
        in pray and unsmite)."""
        if self.health < self.get_health_max():
            return True
        for part in self.body_parts or []:
            if part.health < part.health_max:
                return True
        return False

    def heal_fully(self) -> None:
        """Restores body HP to max, every body part's HP to max, resets
        ``health_regen`` bookkeeping, and marks the player dirty. Used
        by divine full-heal effects (pray crit, unsmite) so they don't
        have to replicate the restore loop inline."""
        self.health = self.get_health_max()
        for part in self.body_parts or []:
            part.health = part.health_max
        self.health_regen = 0
        self.is_dirty = True

    def _is_arm_usable(self, instance_name: str) -> bool:
        """An arm at InjuryLevels.USELESS can no longer swing a weapon
        or throw a punch. A missing arm (not in body_parts) is treated
        as usable — falls back to the pre-anatomy behavior so tests and
        any future armless creatures don't break."""
        part = self.get_part(instance_name)
        if part is None:
            return True
        return part.get_injury_level() != InjuryLevels.USELESS

    def get_attack_sources(self) -> List[AttackSource]:
        """Returns attack sources for usable hands only.

        Produces one source for the left/two-handed slot and (if not
        two-handed) one for the right. Uses WeaponAttackSource when a
        weapon is equipped and UnarmedAttackSource otherwise.

        An arm at InjuryLevels.USELESS disables the attack from that
        hand entirely — no source is emitted and the attack table
        simply won't contain that row. A two-handed weapon requires
        BOTH arms; if either is USELESS, no attack fires at all. The
        companion ``get_disabled_attack_notes`` surfaces the reason
        so the attack rendering can show "Your right arm hangs limp
        and useless." instead of silently dropping the row.
        """
        from caldanai.lib.rpg.combat.attack_source import (
            AttackSource,
            UnarmedAttackSource,
            WeaponAttackSource,
        )

        lh: Weapon = self.equip_slots[EquipmentSlots.LEFT_HELD.name]
        rh: Weapon = self.equip_slots[EquipmentSlots.RIGHT_HELD.name]
        two_handed = bool(lh and EquipmentSlots.MULTI_SLOT & lh.slots)

        left_ok = self._is_arm_usable("arm.left")
        right_ok = self._is_arm_usable("arm.right")

        sources: List[AttackSource] = []
        if two_handed:
            # Two-handed weapons require both arms. If either arm is
            # useless, no source is emitted.
            if left_ok and right_ok:
                sources.append(WeaponAttackSource(lh, label="Two-Handed", reach=lh.reach))
            return sources

        if left_ok:
            if lh:
                sources.append(WeaponAttackSource(lh, label="Left", reach=lh.reach))
            else:
                sources.append(UnarmedAttackSource(label="Left"))

        if right_ok:
            if rh:
                sources.append(WeaponAttackSource(rh, label="Right", reach=rh.reach))
            else:
                sources.append(UnarmedAttackSource(label="Right"))

        return sources

    def get_disabled_attack_notes(self) -> List[str]:
        """Narrative lines explaining which attack slots are disabled
        by arm injury. Used by ``do_attack`` to surface why a hand
        didn't contribute to the sequence — silent dropping feels
        like a bug even when it's correct."""
        notes: List[str] = []
        left_arm = self.get_part("arm.left")
        right_arm = self.get_part("arm.right")

        if left_arm and left_arm.get_injury_level() == InjuryLevels.USELESS:
            notes.append("The left arm hangs limp and useless.")
        if right_arm and right_arm.get_injury_level() == InjuryLevels.USELESS:
            notes.append("The right arm hangs limp and useless.")

        # Two-handed weapon with any arm disabled: call out that the
        # weapon can't be wielded even if one arm is still good.
        lh = self.equip_slots.get(EquipmentSlots.LEFT_HELD.name)
        if lh and EquipmentSlots.MULTI_SLOT & lh.slots:
            if ((left_arm and left_arm.get_injury_level() == InjuryLevels.USELESS)
                    or (right_arm and right_arm.get_injury_level() == InjuryLevels.USELESS)):
                notes.append(f"{lh.get_full_name().capitalize()} cannot be wielded with a maimed arm.")
        return notes

    def do_attack(self, target, explicit_part_names=None):
        """Run the standard do_attack, then attach any disabled-slot
        notes to the resulting sequence so the rendering can surface
        why a hand didn't swing."""
        sequence = super().do_attack(target, explicit_part_names=explicit_part_names)
        notes = self.get_disabled_attack_notes()
        if notes:
            sequence.notes.extend(notes)
        return sequence

    def pick_actions(self) -> List[AttackSource]:
        """Pipeline stage 1 — players use equipment-aware sources.

        Bypasses the part-default action pool walk that
        :meth:`Creature.pick_actions` runs (players don't carry
        ``DEFAULT_ACTIONS`` dicts on humanoid parts yet) and returns
        :meth:`get_attack_sources` directly. Arm-injury handling and
        dual-wield / two-handed routing already live there."""
        return self.get_attack_sources()

    def render_table(self, results) -> str:
        """Pipeline stage 5 — same diff-block shape as
        :meth:`Creature.render_table`, but with disabled-arm notes
        attached to the synthetic ``AttackSequence`` so
        ``to_markdown`` surfaces them inside the diff block (parity
        with the legacy ``do_attack`` path's ``sequence.notes``).

        When no results landed and there are no notes, returns an
        empty string. When no results landed but notes exist (both
        arms USELESS on a two-handed weapon, say), a notes-only
        block is produced so the player still sees why nothing
        swung."""
        from caldanai.lib.rpg.combat.attack_result import AttackSequence

        notes = self.get_disabled_attack_notes()
        flat = list(results.all_results or []) if results is not None else []
        if not flat and not notes:
            return ""
        if flat:
            first_victim = getattr(flat[0], "victim", None) or self
            sequence = AttackSequence(
                attacker=self,
                target=first_victim,
                results=flat,
                multi_target=len({id(getattr(r, "victim", None)) for r in flat}) > 1,
                notes=list(notes),
            )
        else:
            # Notes-only path: no results means no attacker-target
            # axis, but the header still wants a target. Fall back to
            # ``self`` so ``_build_header`` has a coherent shape.
            sequence = AttackSequence(
                attacker=self,
                target=self,
                results=[],
                notes=list(notes),
            )
        return sequence.to_markdown()

    def _on_attack_resolved(self, source, result) -> None:
        """Grants skill XP on hits, updates roll counts, and inherits
        the base hook's drain handling (so a player wielding a
        future life-drain weapon would heal naturally)."""
        super()._on_attack_resolved(source, result)
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
            cid=p.get("channel_id"),  # None for legacy docs; set at runtime by PlayerManager
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
            body_parts_health=p.get("body_parts_health"),
            social=p.get("social"),
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

        series = pandas.Series(self.rolls["d20"], index=range(1, 21), dtype="int")
        ax = series.plot(kind="bar")
        ax.set_xlabel("Rolls")
        ax.set_ylabel("Count")
        ax.set_ybound(lower=0)
        style_axes_dark(ax, accent_color=CYAN_ACCENT, grid_axis="y")

        file = fig_to_file(ax.figure, filename="plot.png")
        embed.set_image(url="attachment://plot.png")

        return embed, file

    def get_defense(self) -> int:
        """Total defense: body-part emergence (torso functionality) plus armor bonuses.

        Defers to :meth:`Creature.get_defense` so torso injuries scale
        defense the same way they do for monsters, then adds any bonuses
        from equipped armor. Clamped at 0.
        """
        base = Creature.get_defense(self)
        armor = self.get_armor_bonuses("defense").get("defense", 0)
        return max(0, base + armor)

    def get_dodge(self) -> int:
        """Total dodge: body-part emergence (leg/wing mobility) plus armor bonuses.

        Defers to :meth:`Creature.get_dodge` so leg injuries degrade
        dodge the same way they do for monsters, then adds any bonuses
        from equipped armor. Clamped at 0.
        """
        base = Creature.get_dodge(self)
        armor = self.get_armor_bonuses("dodge").get("dodge", 0)
        return max(0, base + armor)

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
            if item.favorited:
                msg += " ★"

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
            # Damage-type emoji on its own row (self-explanatory; no
            # label text needed). Falls back silently when the skill
            # has no damage-type component (``unarmed``, ``natural``).
            dmg_type = DamageTypes.from_skill_key(skill)
            emoji_row = f"{dmg_type.emoji}\n" if dmg_type else ""
            msg = (
                f"{emoji_row}"
                f"Current XP: {self.skills[skill]:,}\n"
                f"Attack Bonus: {bonuses[0]}\n"
                f"Damage Bonus: {bonuses[1]}"
            )
            # Strip the technical "combined" marker before player-facing
            # display — DB key is canonical, display is friendly.
            display = DamageTypes.display_skill_name(skill)
            fields.append((f"{display} ({self.get_skill_level(skill)})", msg, True))

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
            return parse("@1cnp corpse rolls lifelessly in @2np arms.", self, actor)
        return parse("@1 glances at @2 and sidesteps @2a hug.", self, actor)

    def to_dict(self) -> dict:
        """Returns a dictionary of the player's attributes."""

        d = {
            "_id": self.id,
            "user_id": self.user_id,
            "guild_id": self.guild_id,
            "channel_id": self.channel_id,
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
            # Persist per-part anatomy (``health_max``) and current
            # ``health`` keyed by instance name. Both fields are saved
            # so anatomy is stable across sessions — see
            # ``_apply_body_parts_health`` for the load path and
            # legacy (int-only) back-compat.
            "body_parts_health": {
                p.name: {"health": p.health, "health_max": p.health_max}
                for p in self.body_parts
            },
            "social": self.social,
        }

        # Empty ``social`` stays out of the saved doc so never-touched
        # players don't gain a noisy field on first save.
        if not self.social:
            del d["social"]

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
