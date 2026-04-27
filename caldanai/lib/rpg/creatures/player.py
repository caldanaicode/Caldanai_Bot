from dataclasses import dataclass, field
from math import floor
from typing import Dict, Tuple, Optional, List, Union

import pandas

from discord import Member, Embed, File

from caldanai.lib.rpg import parse
from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_builder import node, paired
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.mixins import Equippable as _Equippable
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.foot import FootPlugin
from caldanai.lib.rpg.creatures.body_parts.hand import HandPlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.neck import NeckPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.equipment_routing import (
    ALL_PLACEMENTS,
    PLACEMENT_DISPLAY_ORDER,
    SLOT_TO_PART_KEY,
    keys_on_part,
    resolve_placements,
)
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
@dataclass
class ItemResolution:
    """Outcome of :meth:`Player.resolve_item_query`.

    Three observable shapes:

    - ``items`` populated, ``ambiguity_candidates`` empty — clean
      match. In single-select modes there will be exactly one
      item; ``"sell"`` returns any number.
    - ``items`` empty, ``ambiguity_candidates`` populated —
      multiple plausible matches; the caller should surface the
      candidate list and let the user retry with a narrower
      query. Only single-select modes (``equip`` / ``stow`` /
      ``item``) produce this shape.
    - Both empty — no match at all.

    This tri-state is why the resolver returns a dataclass rather
    than a bare ``List[Item]``: empty vs. ambiguous vs. success
    need distinct operator-facing messages.
    """

    items: List[Item] = field(default_factory=list)
    ambiguity_candidates: List[str] = field(default_factory=list)


def _expand_quality_suffix(query: str) -> str:
    """Expand a trailing ``.<partial>`` to the full quality suffix
    when the partial is an unambiguous prefix of one known
    quality-ish name (``best`` plus every :class:`Qualities`
    name).

    ``wand.b`` → ``wand.best``, ``wand.s`` → ``wand.superior``,
    ``wand.mas`` → ``wand.masterwork``. Numeric suffixes
    (``wand.2``) pass through unchanged — they resolve via
    ``Inventory.filter``'s index path. Ambiguous partials or
    unknown suffixes also pass through unchanged so the normal
    handlers can try the query as-is (or fail naturally).
    """
    from caldanai.lib.rpg.helpers.enums import Qualities

    if "." not in query:
        return query
    base, _, suffix = query.rpartition(".")
    if not suffix or suffix.isdigit():
        return query
    # Already a full quality name → nothing to expand.
    if suffix.upper() in Qualities.__members__:
        return query
    if suffix == "best":
        return query
    candidates = ["best"] + [q.name.lower() for q in Qualities]
    matches = [c for c in candidates if c.startswith(suffix)]
    if len(matches) == 1:
        return f"{base}.{matches[0]}"
    return query


def _candidate_labels(items: List[Item]) -> List[str]:
    """Build operator-facing disambiguation strings — ``"sword.1
    (fine)"``, ``"sword.2 (superior)"`` — so the hint we surface
    names each candidate in a way the player can retype to
    uniquely select one. Falls back to plain item names when
    quality / index info is unavailable."""
    labels: List[str] = []
    by_name: Dict[str, int] = {}
    for item in items:
        by_name[item.name] = by_name.get(item.name, 0) + 1
    seen: Dict[str, int] = {}
    for item in items:
        seen[item.name] = seen.get(item.name, 0) + 1
        if by_name[item.name] > 1:
            # Multiple items share this name — disambiguate with
            # the quality-suffix form the filter already
            # understands (``sword.fine``), falling back to
            # position (``sword.1``).
            quality = getattr(item, "quality", None)
            quality_name = getattr(quality, "name", "").lower() if quality else ""
            if quality_name:
                labels.append(f"{item.name}.{quality_name}")
            else:
                labels.append(f"{item.name}.{seen[item.name]}")
        else:
            labels.append(item.name)
    return labels


# Player anatomy as a body-tree. Fixed ``health_max`` per part
# overrides each plugin's default dice roll so every player starts
# with the same deterministic HP pool — character build stays
# consistent across sessions and across the playerbase.
#
# Values chosen to roughly match prior rolled averages while
# landing on cleaner round numbers:
#   head  3d10 (avg 16.5) → 15
#   torso 6d10 (avg 33)   → 30
#   arm   2d8  (avg 9)    → 10
#   leg   2d10 (avg 11)   → 12
#   eye   1d6  (avg 3.5)  → 4
#   neck  1d8  (avg 4.5)  → 8 (vestigial — mounting point for
#                              amulet / jewelry equipment; see
#                              ``body_parts/neck.py``)
#
# DB-persisted ``health_max`` still wins via
# ``_apply_body_parts_health`` (dict-of-dict shape) — players who
# had rolled maxes before this change keep whatever's in their save
# until the next save cycle, after which the deterministic values
# are written back.
PLAYER_BODY_TREE = node(TorsoPlugin, name="torso", health_max=30, children=[
    node(NeckPlugin, name="neck", health_max=8, children=[
        node(HeadPlugin, name="head", health_max=15, children=[
            *paired(EyePlugin, "eye", health_max=4),
        ]),
    ]),
    *paired(
        ArmPlugin, "arm", health_max=10,
        children_builder=lambda side: [
            node(HandPlugin, name=f"hand.{side}", health_max=6),
        ],
    ),
    *paired(
        LegPlugin, "leg", health_max=12,
        children_builder=lambda side: [
            node(FootPlugin, name=f"foot.{side}", health_max=8),
        ],
    ),
])


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


#: Q.6 schema version for player skill XP. Bumped when the XP formula
#: changes; :func:`_migrate_skills_if_needed` one-time-rescales legacy
#: players so existing levels stay intact and future gains feel
#: continuous. See ``Part HP and Bleed Refactor.md``.
SKILLS_SCHEMA_VERSION: int = 2

#: Upper bound on the number of saved gear loadouts per player.
#: Referenced by both ``Player.save_loadout`` (guards against the
#: player creating a fourth label) and the ``$loadout`` command
#: (surfaces the cap in help text and error messages). Bump here
#: when we want to widen the cap — nothing else needs updating.
MAX_LOADOUTS: int = 3

#: Rate ratio between new (Q.6) and old XP formulas at the canonical
#: calibration point: skill level 10, torso hit for 15 damage
#: (torso ``bleed_rate=0.7``). See the Q.6 design doc for the full
#: parity sample. Used as the divisor in the one-time migration
#: top-up so in-level progress rescales (new_xp = old_xp / ratio).
MIGRATION_RATE_RATIO: float = 36 / 41


def _level_threshold(level: int) -> int:
    """Inverse of :meth:`Player.get_skill_level` — the minimum XP
    needed to be at ``level``. The forward formula is
    ``level = min(20, floor((25 + sqrt(5 * (125 + xp))) / 50))``, so
    the threshold for ``level`` is ``((50 * level - 25) ** 2) / 5 - 125``.

    Level 1 threshold is 0, matching the default for unknown skills
    (which :meth:`get_skill_level` returns 1 for when the skill isn't
    in the dict)."""
    if level <= 1:
        return 0
    return int(((50 * level - 25) ** 2) / 5 - 125)


def _migrate_skills_if_needed(player: "Player") -> None:
    """Apply the Q.6 one-time XP rescale once per Player load.

    Gated by ``player.skills_schema_version``. Idempotent — a second
    call is a no-op because the version is bumped in step.

    Rescales each skill's in-level progress by dividing by
    :data:`MIGRATION_RATE_RATIO`, so progress that earned X XP under
    the old formula now represents X/ratio XP under the new one —
    keeping players at the same level but preserving their relative
    position inside the level."""
    current = getattr(player, "skills_schema_version", 1)
    if current >= SKILLS_SCHEMA_VERSION:
        return
    for skill, xp in list(player.skills.items()):
        level = player.get_skill_level(skill)
        floor_xp = _level_threshold(level)
        progress = xp - floor_xp
        if progress <= 0:
            continue
        rescaled = progress / MIGRATION_RATE_RATIO
        player.skills[skill] = int(floor_xp + rescaled)
    player.skills_schema_version = SKILLS_SCHEMA_VERSION
    player.is_dirty = True


class Player(Creature):
    """A simple Player object for tracking player data"""

    BODY_TREE = PLAYER_BODY_TREE

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
        part_equipment: Optional[Dict[str, Dict[str, str]]] = None,
        last_active: Optional[datetime] = None,
        health_regen: Optional[int] = 0,
        body_parts_health: Optional[Dict[str, int]] = None,
        social: Optional[Dict[str, object]] = None,
        skills_schema_version: Optional[int] = None,
        loadouts: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
        known_recipes: Optional[List[str]] = None,
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
        # starting anatomy, materialized from ``PLAYER_BODY_TREE``
        # by ``Creature.__init__``. Left/right pairs are identical
        # by construction — no symmetrization step. Persisted per-
        # part health / health_max from the DB still wins via
        # ``_apply_body_parts_health`` applied over the flat view.
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
        # Crafting: recipe outputs the player has learned. Used by
        # recipes that declare ``requires_known = True`` (advanced
        # recipes that drop as scrolls). Basic recipes don't check
        # this set, so an empty set is fine for fresh players.
        self.known_recipes: set = set(known_recipes or [])
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

        # Phase B3 (2026-04-22): equipment placements now live on
        # each :class:`Equippable` body-part node directly — each
        # node carries a ``placements`` dict keyed by its
        # ``PLACEMENT_KEYS`` declaration and populated at
        # materialization time by ``BodyPartPlugin.__init__``. The
        # ``self.part_equipment`` name is preserved as a computed
        # property (see below) returning a ``{part_name: node.placements}``
        # view where the inner dicts are LIVE REFERENCES to each
        # node's storage — so dict-style reads and writes continue
        # to work for back-compat.
        #
        # Rehydrate persisted placements onto nodes. The DB shape
        # is ``{part: {key: item_id_str}}`` (None entries stripped);
        # look each item up in this player's inventory and write
        # straight to the owning node's placements dict.
        if part_equipment:
            for part_name, keys in part_equipment.items():
                part = self.get_part(part_name)
                if part is None or not isinstance(part, _Equippable):
                    # Skip parts this player doesn't have (e.g. a
                    # legacy doc with a part since removed from the
                    # anatomy). The migration tool is responsible for
                    # dropping those entries, so hitting this in
                    # production means the migration didn't run.
                    continue
                for key, item_id in keys.items():
                    if key not in part.placements:
                        continue
                    if item_id:
                        item = self.inventory[str(item_id)]
                        if item is not None:
                            part.placements[key] = item

        # Q.6 skills-schema versioning. Absent in legacy documents;
        # defaults to v1 when skills exist (triggers one-time migration)
        # or the current schema when there are no skills (brand-new
        # player — migration is a no-op).
        if skills_schema_version is not None:
            self.skills_schema_version = int(skills_schema_version)
        elif self.skills:
            self.skills_schema_version = 1
        else:
            self.skills_schema_version = SKILLS_SCHEMA_VERSION
        _migrate_skills_if_needed(self)
        # Clear is_dirty if migration was a no-op (brand-new player or
        # already-migrated document) — the caller's "fresh Player is
        # clean" contract holds. Legacy documents that actually got
        # their XP rescaled stay dirty so the next save persists the
        # migration.
        if skills_schema_version is not None and skills_schema_version >= SKILLS_SCHEMA_VERSION:
            self.is_dirty = False
        elif not self.skills:
            self.is_dirty = False

        # Saved gear loadouts (2026-04-22 QoL follow-up to stage
        # 2a). Each entry is ``{label: part_equipment_shape}``
        # where the shape mirrors the DB form of
        # ``part_equipment`` — ``{part_name: {key: item_id_str}}``
        # with empty placements omitted. Capped at
        # :data:`MAX_LOADOUTS` (see ``save_loadout``).
        self.loadouts: Dict[str, Dict[str, Dict[str, str]]] = dict(loadouts or {})

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
        # Capture injury state BEFORE damage so we can detect
        # parts that newly transition to USELESS from this call.
        # Only NEWLY-useless parts drop gear — a part that was
        # already useless before this hit doesn't re-drop (its
        # gear went back to inventory on the first transition).
        already_useless = {
            p.name for p in (self.body_parts or [])
            if p.get_injury_level() == InjuryLevels.USELESS
        }

        was_alive = self.health > 0
        super().apply_damage(
            amount,
            dmg_type=dmg_type,
            target_part=target_part,
        )
        self.is_dirty = True

        # Stage 2a (2026-04-22): items on destroyed parts return
        # to the inventory pool. Items stay in inventory — the
        # placements are the only thing that cleared — so the
        # player hasn't LOST anything, they've just lost the USE
        # of it until the part heals. Matches the project memo
        # rationale ("NOT lost or broken, temporary loss of
        # access"). 2026-04-25 follow-up: each per-part drop now
        # surfaces a flavor line via ``BodyPart.gear_drop_flavor``
        # so the player sees what fell off (silent before — they
        # had to ``$gear`` to discover their sword wasn't equipped
        # anymore).
        drop_lines: List[str] = []
        for part in list(self.body_parts or []):
            if (
                part.get_injury_level() == InjuryLevels.USELESS
                and part.name not in already_useless
            ):
                dropped = self._drop_gear_on_destroyed_part(part.name)
                line = part.gear_drop_flavor(dropped, self)
                if line:
                    drop_lines.append(line)

        # Death / revive lines append after the drop narration so
        # the reader sees gear leave first ("X slips from your now-
        # useless arm." then "You crumple to the ground.") — the
        # equipment beat lands while the player is still alive in
        # the narrative, matching the in-fiction order.
        tail = ""
        if was_alive and self.is_dead():
            tail = parse("@1 crumples to the ground lifelessly!", self)
        elif not was_alive and not self.is_dead():
            mention = f"<@!{self.member.id}>" if self.member is not None else self.name
            tail = parse(f"{mention} suddenly gasps raggedly as life returns to @1o!", self)

        return "\n".join([*drop_lines, tail]) if drop_lines else tail

    # ------------------------------------------------------------------
    # Equipment access (Phase B3)
    #
    # Storage is per-node: each :class:`Equippable` body part owns
    # a ``placements`` dict. :attr:`part_equipment` remains as the
    # legacy-compatible nested-dict view, with inner dicts being
    # LIVE REFERENCES to node storage — reads and writes continue
    # to work. New code should prefer :meth:`place` /
    # :meth:`clear_placement` for clarity.
    # ------------------------------------------------------------------

    @property
    def part_equipment(self) -> Dict[str, Dict[str, Optional[Equipment]]]:
        """Nested-dict view over each :class:`Equippable` body
        part's current equipment placements.

        Inner dicts are LIVE REFERENCES to each node's
        ``placements`` dict, so mutations through this view
        (``player.part_equipment["head"]["worn"] = item``) write
        directly to the node. That's the back-compat contract for
        the hundred-plus call sites predating B3; new code should
        go through :meth:`place` / :meth:`clear_placement` instead.

        Outer dict is rebuilt per access from the current tree
        topology, so hydra-style runtime regrowth reflects in the
        view on the next read.
        """
        return {
            n.name: n.placements
            for n in self.body_parts
            if isinstance(n, _Equippable)
        }

    def place(self, part_name: str, key: str, item: Optional[Equipment]) -> None:
        """Set the equipment at ``part_name.key`` to ``item``.

        Preferred write API over the legacy
        ``player.part_equipment[part][key] = item`` dict-access
        pattern. Raises ``KeyError`` when the part doesn't exist
        or the key isn't declared on the part's plugin — the
        strict form is deliberate so typos surface at the call
        site rather than silently corrupting placement state.
        """
        part = self.get_part(part_name)
        if part is None or not isinstance(part, _Equippable):
            raise KeyError(
                f"No Equippable part named {part_name!r} on {self.name}"
            )
        if key not in part.placements:
            raise KeyError(
                f"Part {part_name!r} does not accept placement key {key!r}; "
                f"valid keys: {sorted(part.placements)}"
            )
        part.placements[key] = item

    def clear_placement(self, part_name: str, key: str) -> None:
        """Clear the equipment at ``part_name.key`` (set to
        ``None``). Thin wrapper over :meth:`place` for readability
        at call sites that semantically mean "remove"."""
        self.place(part_name, key, None)

    def _drop_gear_on_destroyed_part(self, part_name: str) -> List[Equipment]:
        """Return every item at ``part_name``'s placements to the
        inventory pool, returning the list of dropped items so the
        caller can narrate the drop. Items already live in
        ``self.inventory`` — ``part_equipment`` holds *references*
        to inventory items — so the drop is accomplished by clearing
        the placements via :meth:`remove`. ``remove`` walks every
        placement holding a given ``Item`` instance, so multi-placed
        items (two-handed weapons, paired gear) come off fully even
        when only one of their placements is at the destroyed part:
        the weapon "can no longer be wielded with one good arm,"
        so the other arm stops holding it too.

        Called from :meth:`apply_damage` on the frame a part
        transitions to USELESS.

        **Load-bearing invariant**: this is the ONLY path that
        drops player gear on part destruction. Any future code
        that sets ``part.health = 0`` directly (admin command,
        cheat, test hack) bypasses the drop. Today
        ``$spawn destroy`` only targets monsters (which have no
        ``part_equipment``), so this hole is theoretical; if the
        admin surface ever grows a player-side part-destroy
        command, wire it through this method too.

        :return: Unique items that were dropped (deduplicated for
            multi-placed gear). Empty list when the part has no
            equipment or doesn't exist.
        """
        # Operates on this part's OWN placements only. The Phase D
        # subtree-cascade ("a hand under a destroyed arm is also
        # unreachable") is handled by the caller: the
        # ``apply_damage`` loop iterates every newly-useless part,
        # and cascaded descendants report ``get_injury_level() ==
        # USELESS`` automatically (via the ``ancestor.health <= 0``
        # check on :meth:`BodyPart.get_injury_level`). So each node
        # in the destroyed subtree gets its own drop call — and its
        # own per-part flavor line via :meth:`BodyPart.gear_drop_flavor`,
        # attributing the drop to the right part name. A wand held
        # by ``hand.left`` under a destroyed ``arm.left`` narrates
        # against ``hand.left`` instead of being conflated into the
        # arm's flavor.
        part_placements = self.part_equipment.get(part_name)
        if not part_placements:
            return []
        items: List[Equipment] = []
        seen: set = set()
        for key, item in part_placements.items():
            if item is None:
                continue
            if id(item) in seen:
                continue
            seen.add(id(item))
            items.append(item)
        for item in items:
            self.remove(item)
        return items

    # ------------------------------------------------------------------
    # Gear loadouts — save / load / clear / list
    # ------------------------------------------------------------------
    #
    # Players can snapshot the current ``part_equipment`` under a
    # label ("combat", "travel", "town", etc.) and restore it
    # later with a single command — useful because stage 2a
    # (destroyed-part drops gear) significantly increased the
    # frequency of having to re-equip everything. Capacity capped
    # at :data:`MAX_LOADOUTS`.
    #
    # Save stores ITEM IDs, not copies — so selling or trading an
    # item naturally invalidates the saved reference, which is
    # pruned by :meth:`_purge_item_refs` (hooked into the
    # inventory-removal path via :meth:`take_item`).

    def _normalize_label(self, label: str) -> str:
        """Canonical form for case-insensitive lookup. ``"Combat"``
        and ``"combat"`` and ``"COMBAT"`` all hit the same slot.
        Storage preserves the player's original casing — we only
        normalize at comparison time."""
        return (label or "").strip().casefold()

    def get_loadout(self, label: str) -> "Optional[Dict[str, Dict[str, str]]]":
        """Case-insensitive EXACT lookup of a saved loadout by
        label. Returns the raw ``{part: {key: item_id}}`` dict or
        ``None`` when no slot matches. For fuzzy prefix lookups
        (``$loadout load comb`` → ``combat``), see
        :meth:`resolve_loadout_label`."""
        target = self._normalize_label(label)
        if not target:
            return None
        for stored_label, payload in self.loadouts.items():
            if self._normalize_label(stored_label) == target:
                return payload
        return None

    def resolve_loadout_label(
        self, query: str,
    ) -> "Tuple[Optional[str], List[str]]":
        """Resolve ``query`` to a stored loadout label, supporting
        case-insensitive prefix matching for ``$loadout load`` and
        ``$loadout clear``. Returns ``(stored_label, candidates)``:

        - ``(exact_label, [])`` — the query casefolds to a saved
          label exactly. Takes priority so a player with both
          ``"a"`` and ``"abc"`` saved can still load just ``"a"``
          without triggering ambiguity.
        - ``(prefix_label, [])`` — exactly one saved label starts
          with the casefolded query. Fuzzy match succeeds.
        - ``(None, [lbl1, lbl2, …])`` — multiple saved labels
          start with the casefolded query; caller should surface
          the candidates and let the player pick.
        - ``(None, [])`` — no match at all.

        ``save`` intentionally does NOT route through this; it
        uses the label as-typed so a player saving ``"comb"``
        doesn't accidentally overwrite ``"combat"``.
        """
        target = self._normalize_label(query)
        if not target:
            return None, []

        # Exact casefold match wins unconditionally — avoids
        # ambiguity blocking ``$loadout load a`` when both
        # ``"a"`` and ``"abc"`` are saved.
        for stored_label in self.loadouts:
            if self._normalize_label(stored_label) == target:
                return stored_label, []

        prefix_matches = [
            stored_label for stored_label in self.loadouts
            if self._normalize_label(stored_label).startswith(target)
        ]
        if len(prefix_matches) == 1:
            return prefix_matches[0], []
        if len(prefix_matches) > 1:
            return None, prefix_matches
        return None, []

    def save_loadout(self, label: str) -> "Tuple[bool, str]":
        """Snapshot current ``part_equipment`` under ``label``.

        Rules:
        - Label must be non-empty (post-strip).
        - Case-insensitive: saving ``"Combat"`` after ``"combat"``
          OVERWRITES the existing slot and adopts the new casing.
        - Capacity capped at :data:`MAX_LOADOUTS`. Attempting to
          create a *new* label (not an overwrite) when every slot
          is full returns a failure tuple naming the full set.

        Returns ``(success, message)``. ``message`` names the
        resulting label on success or explains the failure.
        """
        clean = (label or "").strip()
        if not clean:
            return False, "Loadout label can't be empty."
        target = self._normalize_label(clean)

        # Find a pre-existing slot with the same casefolded label
        # so we can overwrite rather than add a second entry.
        existing_key: Optional[str] = None
        for stored_label in list(self.loadouts.keys()):
            if self._normalize_label(stored_label) == target:
                existing_key = stored_label
                break

        if existing_key is None and len(self.loadouts) >= MAX_LOADOUTS:
            labels = ", ".join(f"`{lbl}`" for lbl in self.loadouts.keys())
            return False, (
                f"You already have {MAX_LOADOUTS} loadouts saved "
                f"({labels}). Clear one before saving a new label."
            )

        # Serialize the current equipment shape the same way
        # ``to_dict`` does — non-None placements only, item ids as
        # strings. This matches the save-on-disk format, so a
        # reload hydrates without any intermediate translation.
        snapshot: Dict[str, Dict[str, str]] = {}
        for part_name, keys in self.part_equipment.items():
            for key, item in keys.items():
                if item is not None:
                    snapshot.setdefault(part_name, {})[key] = str(item.id)

        # Overwrite by dropping the old key and using the new
        # casing — last-write-wins on label formatting.
        if existing_key is not None and existing_key != clean:
            del self.loadouts[existing_key]
        self.loadouts[clean] = snapshot
        self.is_dirty = True
        return True, clean

    def load_loadout(
        self, label: str,
    ) -> "Tuple[bool, str, List[Equipment], List[str]]":
        """Apply a saved loadout: stow everything currently
        equipped, then re-equip every item referenced in the saved
        snapshot that's still in inventory.

        Items land on USELESS body parts too — ``equip`` itself
        doesn't gate on injury state; only combat does (see
        ``get_attack_sources``). The phantom weapon on a dead
        limb waits for healing to become usable, matching how
        manual ``$equip`` already behaves. That's a feature, not
        a bug: the player's saved loadout is fulfilled where
        possible, not arbitrarily dropped when some parts are
        injured.

        Returns ``(success, stored_label, restored, skipped)``:

        - ``success`` — ``False`` if no matching label exists.
        - ``stored_label`` — the label as originally saved
          (preserves casing so the confirmation message can echo
          the player's own form).
        - ``restored`` — display names of items actually equipped.
        - ``skipped`` — human-readable notes for items that
          couldn't land (no longer in inventory, destroyed arm,
          etc.).
        """
        payload = self.get_loadout(label)
        if payload is None:
            return False, label, [], []

        # Resolve the stored label with its original casing for
        # the return tuple.
        target = self._normalize_label(label)
        stored_label = next(
            (
                lbl for lbl in self.loadouts
                if self._normalize_label(lbl) == target
            ),
            label,
        )

        # Stow everything first so placements are free to fill.
        # Dedupe by identity — a two-hander on both arms is one
        # ``remove`` call, same as ``$stow all``.
        currently_equipped: List[Equipment] = []
        seen: set = set()
        for item in self._iter_equipped_items():
            if id(item) in seen:
                continue
            seen.add(id(item))
            currently_equipped.append(item)
        for item in currently_equipped:
            self.remove(item)

        restored: List[Equipment] = []
        skipped: List[str] = []

        # Dedupe item ids — a multi-placed item appears under
        # several (part, key) entries but should only be equipped
        # once via the normal equip path.
        unique_item_ids: List[str] = []
        seen_ids: set = set()
        for part_name, keys in payload.items():
            for key, item_id in keys.items():
                if item_id not in seen_ids:
                    seen_ids.add(item_id)
                    unique_item_ids.append(item_id)

        for item_id in unique_item_ids:
            item = self.inventory[item_id]
            if item is None or not isinstance(item, Equipment):
                skipped.append(
                    f"*(gone from inventory)* — id `{item_id[:8]}…`"
                )
                continue
            ok, msg = self.equip(item)
            if ok:
                restored.append(item)
            else:
                skipped.append(f"{item.get_full_name()} — {msg or 'could not equip'}")

        self.is_dirty = True
        return True, stored_label, restored, skipped

    def clear_loadout(self, label: str) -> "Tuple[bool, str]":
        """Delete the saved loadout matching ``label``
        case-insensitively. Returns ``(True, stored_label)`` on
        success (echoing the original casing) or ``(False, "")``
        when no slot matched."""
        target = self._normalize_label(label)
        if not target:
            return False, ""
        for stored_label in list(self.loadouts.keys()):
            if self._normalize_label(stored_label) == target:
                del self.loadouts[stored_label]
                self.is_dirty = True
                return True, stored_label
        return False, ""

    def _purge_item_refs(self, item: "Item") -> None:
        """Remove every saved-loadout reference to ``item`` so
        ``$loadout load`` doesn't try to equip something the
        player no longer owns.

        Invoked from :meth:`take_item` (the centralized
        "no longer owns this" path covering sell, future trade,
        admin removal, etc.). Empty part-entries are pruned after
        the purge; labels themselves stay as empty-payload
        entries so the player's saved slots aren't silently
        collapsed (a re-save into the same label is still
        possible).

        Sets ``is_dirty`` when an actual purge happens so future
        callsites that bypass ``take_item``'s own dirty-flag set
        (trade / admin-remove paths) still get the next save
        tick to persist the cleaned-up state.
        """
        target_id = str(item.id)
        purged = False
        for stored_label, payload in self.loadouts.items():
            for part_name in list(payload.keys()):
                keys = payload[part_name]
                for key in list(keys.keys()):
                    if keys[key] == target_id:
                        del keys[key]
                        purged = True
                if not keys:
                    del payload[part_name]
        if purged:
            self.is_dirty = True

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

        lh: Weapon = self.part_equipment.get("hand.left", {}).get("held")
        rh: Weapon = self.part_equipment.get("hand.right", {}).get("held")

        # Detect a two-handed weapon on EITHER arm — pre-2026-04-22
        # this only checked ``lh``, which meant a right-arm-only
        # phantom (bow at arm.right.held with a one-hander at
        # arm.left.held) fell through to the dual-firing path and
        # let a player swing both as single-hand attacks, bypassing
        # the "two-handed requires both arms" restriction. The
        # replace_equipment fix makes that state unreachable via
        # normal equip flow, but defense-in-depth matters for a
        # combat-affecting invariant — any future hook that could
        # orphan a multi-slot item (admin spawn tools, save-load
        # corruption, etc.) gets caught here too.
        two_handed_weapon: "Optional[Weapon]" = None
        if lh and EquipmentSlots.MULTI_SLOT & lh.slots:
            two_handed_weapon = lh
        elif rh and EquipmentSlots.MULTI_SLOT & rh.slots:
            two_handed_weapon = rh

        left_ok = self._is_arm_usable("arm.left")
        right_ok = self._is_arm_usable("arm.right")

        sources: List[AttackSource] = []
        if two_handed_weapon is not None:
            # Two-handed weapons require both arms. If either arm is
            # useless, no source is emitted.
            if left_ok and right_ok:
                sources.append(
                    WeaponAttackSource(
                        two_handed_weapon,
                        label="Two-Handed",
                        reach=two_handed_weapon.reach,
                    )
                )
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
        # Check BOTH arms for the multi-slot flag — mirror of the
        # same defense-in-depth addition in ``get_attack_sources``.
        lh = self.part_equipment.get("hand.left", {}).get("held")
        rh = self.part_equipment.get("hand.right", {}).get("held")
        two_h = None
        if lh and EquipmentSlots.MULTI_SLOT & lh.slots:
            two_h = lh
        elif rh and EquipmentSlots.MULTI_SLOT & rh.slots:
            two_h = rh
        lh = two_h if two_h is not None else lh
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
        """Grants skill XP on hits (committed-damage bonus) or misses
        (flat floor), updates roll counts, and inherits the base hook's
        drain handling so a future life-drain weapon would heal
        naturally.

        Q.6: XP now scales with committed damage via the part's
        ``bleed_rate`` — a torso hit for 15 damage grants more XP than
        an eye hit for the same damage. Misses grant a flat 2 XP so
        low-skill players still progress while learning to connect.
        """
        super()._on_attack_resolved(source, result)
        if result.hit():
            part = getattr(result, "target_part", None)
            # Instance-level override wins (rare) but class-level
            # ``bleed_rate`` is the common path; partless routing
            # falls back to the neutral 1.0.
            bleed = getattr(part, "bleed_rate", 1.0) if part is not None else 1.0
            # hit=True even when damage=0 — trait-immune hits (physical
            # vs spirit, etc.) still represent committed connects and
            # earn base_hit_xp; only the damage-bonus goes to zero.
            self.gain_skill_experience(
                source.skill, damage=result.damage, bleed_rate=bleed, hit=True,
            )
        else:
            self.gain_skill_experience(source.skill, hit=False)
        self.update_roll_counts(result.combined)

    def _placement_is_blocked(self, part_name: str) -> bool:
        """True if ``part_name`` resolves to a part that's
        functionally destroyed (own health depleted OR a tree-
        ancestor destroyed — :meth:`BodyPart.is_destroyed`
        cascades). Equip refuses placement at blocked parts: a
        severed arm doesn't hold a sword, and a hand below a
        destroyed arm doesn't wear a glove. Without the gate,
        ``$equip wand@r`` succeeds on a destroyed right arm and
        the item silently rides a part the player no longer has.
        """
        part = self.get_part(part_name)
        if part is None:
            return False
        return part.is_destroyed()

    def replace_equipment(
        self, item: Equipment, part_name: str, key: str,
    ) -> Tuple[bool, Optional[Equipment]]:
        """Place ``item`` at ``(part_name, key)``, returning the
        previous occupant if any.

        Returns ``(True, replaced)`` when the placement is valid
        and ``replaced`` is whatever was there before (possibly
        ``None``). Returns ``(False, None)`` when the part or key
        is unknown for this player — callers should handle this
        as an equip-failure. The replaced item is left in the
        player's inventory; the caller gets it back so display
        messages can name what got swapped out.

        Multi-placed displacement: if the outgoing item was
        spread across multiple placements (two-handed weapon,
        paired gear sharing a single ``Item`` reference), every
        OTHER placement referencing it is cleared too. Otherwise
        a one-handed replacement at one arm leaves a phantom of
        the old two-hander lingering at the other arm — observed
        during playtest when swapping a bow for a one-handed
        rock, where ``arm.left.held`` kept showing the bow until
        the next restart.
        """
        if part_name not in self.part_equipment:
            return False, None
        if key not in self.part_equipment[part_name]:
            return False, None
        replaced = self.part_equipment[part_name][key]
        self.part_equipment[part_name][key] = item
        if replaced is not None and replaced is not item:
            for pn in self.part_equipment:
                for k in list(self.part_equipment[pn].keys()):
                    if (pn, k) == (part_name, key):
                        continue
                    if self.part_equipment[pn][k] is replaced:
                        self.part_equipment[pn][k] = None
        return True, replaced

    def _iter_equipped_items(self):
        """Yield every currently-equipped ``Item`` instance across
        every ``(part, key)``. Two-handed weapons appear twice
        (once per arm) because their references are shared."""
        for _, keys in self.part_equipment.items():
            for _, item in keys.items():
                if item is not None:
                    yield item

    def is_equipped(self, item: Equipment) -> bool:
        """True if this specific ``Item`` instance is currently
        placed anywhere in ``part_equipment``. Identity compare
        (not ``__eq__``) so two distinct items of the same plugin
        don't conflate."""
        for equipped in self._iter_equipped_items():
            if equipped is item:
                return True
        return False

    def find_equipped_by_placement(self, query: str) -> "Optional[Equipment]":
        """Resolve a placement-shaped query to the currently-
        equipped ``Item`` at that placement, or ``None``.

        Accepts three forms, in priority order:

        1. **Full** ``part.key`` — ``hand.left.held``, ``head.worn``,
           ``torso.outer``. Walks every split point between dots so
           a multi-segment key (``head.earring.left``) resolves
           correctly even though its key contains a dot.
        2. **Bare key** — ``worn``, ``held``, ``outer``. Scans
           anatomy in :data:`PLACEMENT_DISPLAY_ORDER` (head-to-toe)
           and returns the first occupied placement whose key
           matches. Ambiguous keys (``held`` with both hands
           occupied by different weapons) resolve to the left side
           by the display-order tie-break; a follow-up call picks
           up the right. For two-handed weapons the same ``Item``
           sits at both arms, so ``remove()`` on the returned
           instance clears both anyway — no need to repeat.
        3. **Full key-with-dots** — ``ear.left`` (matches
           ``head.ear.left``). Falls out of the bare-key scan
           automatically since that path matches on ``key``
           equality.

        Lookup cost is O(placements) — 24 entries currently, two
        dict lookups each. Cheap enough to run on every ``$stow`` /
        ``$unequip`` invocation without caching.
        """
        q = query.lower().strip()
        if not q:
            return None

        tokens = q.split(".")
        if len(tokens) >= 2:
            # Try every (part, key) split of the dotted query. Longer
            # part names win by iterating from the rightmost split
            # backward — ``arm.left.held`` resolves ``part=arm.left``
            # rather than ``part=arm``.
            for split in range(len(tokens) - 1, 0, -1):
                part_name = ".".join(tokens[:split])
                key = ".".join(tokens[split:])
                equipped = self.part_equipment.get(part_name, {}).get(key)
                if equipped is not None:
                    return equipped

        # Bare-key / key-with-dots scan — first occupied placement
        # whose key matches.
        for (part_name, key) in PLACEMENT_DISPLAY_ORDER:
            if key == q:
                equipped = self.part_equipment.get(part_name, {}).get(key)
                if equipped is not None:
                    return equipped

        return None

    def find_all_equipped_matching_placement(
        self, query: str,
    ) -> "List[Tuple[Equipment, Tuple[str, str]]]":
        """Return every ``(item, (part, key))`` where the placement
        query matches. Three patterns, tried in order:

        1. **Full ``part.key``** — resolves to a single specific
           placement. ``hand.left.held`` selects exactly that
           placement and bypasses all broadening.
        2. **Bare key** (``held``, ``ring``, ``outer``) — broadens
           to every occupied placement with that key across every
           part. ``$stow held`` clears both hands.
        3. **Bare part name** (``torso``, ``arm``, ``head``) —
           broadens to every occupied placement ON that part (or
           parts, if the query is a fuzzy-prefix match like
           ``arm`` covering ``arm.left`` and ``arm.right``).
           ``$stow torso`` clears worn + outer + accent together.

        Uses :data:`PLACEMENT_DISPLAY_ORDER` so head-before-torso
        and left-before-right is the stable iteration order. Two-
        handed weapons share their ``Item`` reference across both
        arms — the return deduplicates by identity so the same
        weapon only appears once even though it occupies two
        placements.

        Empty result = nothing equipped matches. Callers use the
        return length to decide between "act on the only match",
        "act on all matches" (stow mode), or "surface ambiguity"
        (item mode).
        """
        q = query.lower().strip()
        if not q:
            return []

        tokens = q.split(".")
        if len(tokens) >= 2:
            # Full ``part.key`` wins when it lands. Specific form
            # bypasses the broadening behavior — ``arm.left.held``
            # selects exactly that placement, never both arms.
            for split in range(len(tokens) - 1, 0, -1):
                part_name = ".".join(tokens[:split])
                key = ".".join(tokens[split:])
                equipped = self.part_equipment.get(part_name, {}).get(key)
                if equipped is not None:
                    return [(equipped, (part_name, key))]

        matches: "List[Tuple[Equipment, Tuple[str, str]]]" = []
        seen_ids: set = set()

        # Bare key / key-with-dots — scan anatomy in display order
        # and collect every occupied placement with that key.
        for (part_name, key) in PLACEMENT_DISPLAY_ORDER:
            if key == q:
                equipped = self.part_equipment.get(part_name, {}).get(key)
                if equipped is not None and id(equipped) not in seen_ids:
                    matches.append((equipped, (part_name, key)))
                    seen_ids.add(id(equipped))
        if matches:
            return matches

        # Bare part name — broaden to every occupied placement on
        # the matched part(s). Only tried when the bare-key pass
        # found nothing, so a key like ``held`` doesn't accidentally
        # trigger part-name lookup. ``self.find_parts`` handles
        # fuzzy-prefix matching (``arm`` → ``arm.left`` +
        # ``arm.right``), so a bare base-name naturally broadens
        # across sides. Single-token queries only — ``arm.held``
        # should go through the full part.key path or be a no-op,
        # not silently reinterpreted as a part name.
        if "." not in q:
            for part in self.find_parts(q):
                if not isinstance(part, _Equippable):
                    continue
                # Iterate placements in PLACEMENT_DISPLAY_ORDER so
                # the return order stays stable across the three
                # broadening branches.
                for (display_part, display_key) in PLACEMENT_DISPLAY_ORDER:
                    if display_part != part.name:
                        continue
                    equipped = part.placements.get(display_key)
                    if equipped is not None and id(equipped) not in seen_ids:
                        matches.append((equipped, (part.name, display_key)))
                        seen_ids.add(id(equipped))
        return matches

    def resolve_item_query(
        self, query: str, mode: str,
    ) -> "ItemResolution":
        """Resolve a single item-query token into matching ``Item``
        instances, honoring per-mode priority and ambiguity rules.

        ``mode`` values:

        - ``"equip"`` — item-first (inventory only, not equipped);
          single-match enforced. ``.best`` / ``.quality`` / ``.N``
          selectors honored.
        - ``"stow"`` — placement-first. Placement keys
          (``head.worn``, ``outer``, ``held``) resolve to the
          currently-equipped item at that placement. Items not
          equipped at all are NOT returned — stow's purpose is
          un-equipping, so an inventory-only match is a no-op.
          Single-match enforced.
        - ``"item"`` — item-first with a placement fallback. If
          the query isn't an inventory item name, try it as a
          placement and return the currently-equipped item there.
          Single-match.
        - ``"sell"`` — item-first, excludes currently-equipped
          items. Multiple matches allowed (the point of sell-by-
          name is to catch every instance). No ambiguity
          surfacing.

        Returns an :class:`ItemResolution`. Empty ``items`` +
        populated ``ambiguity_candidates`` means "multiple
        plausible matches — surface them and let the user retry."
        Empty ``items`` + empty ``ambiguity_candidates`` means "no
        match at all." Populated ``items`` means success; for
        single-select modes there will be exactly one entry.
        """
        from caldanai.lib.rpg.helpers.enums import Qualities
        from caldanai.lib.rpg.inventory.equipment import Equipment

        q = query.strip() if isinstance(query, str) else query
        if not q:
            return ItemResolution()

        # ---- ``stow`` mode: placement-first with bare-key broadening.
        # A full ``part.key`` query selects exactly that placement;
        # a bare key (``held`` / ``ring`` / ``worn``) stows EVERY
        # occupied placement with that key. This matches how players
        # think about it — "stow worn" clears every worn layer,
        # "stow held" clears everything you're holding.
        if mode == "stow":
            placements = self.find_all_equipped_matching_placement(str(q))
            if placements:
                return ItemResolution(items=[p[0] for p in placements])
            # Fallback: item-name that happens to match something
            # currently equipped.
            candidates = self._filter_matching_items(str(q))
            equipped_candidates = [
                item for item in candidates if self.is_equipped(item)
            ]
            if len(equipped_candidates) == 1:
                return ItemResolution(items=equipped_candidates)
            if len(equipped_candidates) > 1:
                return ItemResolution(
                    ambiguity_candidates=_candidate_labels(equipped_candidates),
                )
            return ItemResolution()

        # ---- ``equip`` / ``item`` / ``sell`` — item-first.
        candidates = self._filter_matching_items(str(q))

        if mode == "equip":
            # Equip works off the inventory pool minus items already
            # equipped — ``.best`` means "best UNEQUIPPED" so
            # ``$equip wand.best`` with the superior wand already on
            # fills a free slot with the next-best wand rather than
            # bouncing off "Item already equipped." A player who
            # specifically wants to re-equip an already-worn item
            # uses the full quality form (``$equip wand.superior``)
            # or the index form (``$equip wand.1``).
            candidates = self._filter_matching_items(
                str(q),
                predicate=lambda i: (
                    isinstance(i, Equipment) and not self.is_equipped(i)
                ),
            )
            if len(candidates) == 1:
                return ItemResolution(items=candidates)
            if len(candidates) > 1:
                return ItemResolution(
                    ambiguity_candidates=_candidate_labels(candidates),
                )
            return ItemResolution()

        if mode == "item":
            if len(candidates) == 1:
                return ItemResolution(items=candidates)
            if len(candidates) > 1:
                return ItemResolution(
                    ambiguity_candidates=_candidate_labels(candidates),
                )
            # No inventory match — fall back to placement lookup so
            # e.g. ``$item head.worn`` shows the currently-worn helm.
            # Bare-key queries (``held``) that match multiple occupied
            # placements surface ambiguity — unlike ``$stow held``,
            # we can't meaningfully show multiple item embeds in one
            # response, so the user needs to pick one.
            placements = self.find_all_equipped_matching_placement(str(q))
            if len(placements) == 1:
                return ItemResolution(items=[placements[0][0]])
            if len(placements) > 1:
                labels = [f"{p[1][0]}.{p[1][1]}" for p in placements]
                return ItemResolution(ambiguity_candidates=labels)
            return ItemResolution()

        if mode == "sell":
            # Sell excludes equipped items — you can't sell what
            # you're wearing. Re-filter via the predicate path so
            # ``.best`` picks the best UNEQUIPPED match rather
            # than globally-best-then-check (which would fail when
            # the global best happens to be worn).
            unequipped = self._filter_matching_items(
                str(q), predicate=lambda i: not self.is_equipped(i),
            )
            return ItemResolution(items=unequipped)

        raise ValueError(f"Unknown resolve_item_query mode: {mode!r}")

    def _filter_matching_items(
        self, query: str, predicate=None,
    ) -> List[Item]:
        """Item-name filter with ``.best`` support and quality-
        suffix prefix matching layered on top of ``Inventory.filter``.

        ``predicate``: optional callable ``(Item) -> bool``. When
        set, candidates are filtered BEFORE ``.best`` ranking so
        ``.best`` means "best within the mode-specific pool"
        rather than "global best, then check mode filter." This is
        what makes ``$sell wand.best`` do the intuitive thing even
        when the globally-best wand is equipped — it falls back to
        the best unequipped wand instead of failing with no match.

        Quality-suffix shortcuts: single-character (or longer)
        prefixes of quality names expand to the full form.
        ``wand.b`` → ``wand.best``, ``wand.s`` → ``wand.superior``,
        ``wand.m`` → ``wand.masterwork``. Each quality name
        currently starts with a unique letter, so one-char prefixes
        are unambiguous. Multi-char prefixes narrow further.
        """
        q = query.lower().strip()
        if not q:
            return []
        q = _expand_quality_suffix(q)

        if q.endswith(".best") and len(q) > 5:
            base = q[:-5]
            base_matches = [
                i for i in self.inventory.filter(base)
                if i is not None
            ]
            if predicate is not None:
                base_matches = [i for i in base_matches if predicate(i)]
            if not base_matches:
                return []
            base_matches.sort(
                key=lambda i: i.quality.value["multiplier"],
                reverse=True,
            )
            return [base_matches[0]]

        results = self.inventory.filter(q)
        filtered = [i for i in results if i is not None]
        if predicate is not None:
            filtered = [i for i in filtered if predicate(i)]
        return filtered

    def equip(self, item: Equipment, slot: EquipmentSlots = None) -> Tuple[bool, str]:
        """Equip ``item`` — either at a specific ``slot`` or
        auto-routed to the first available placement its mask
        supports.

        Returns ``(success, message)``. ``message`` describes any
        replaced item's full name on success (for "You equipped
        X, replacing Y" callsites), or the failure reason on
        failure.

        Three cases:

        1. **Multi-slot** (``item.slots & MULTI_SLOT``) — item
           fills every placement its mask resolves to. Two-handed
           weapons land at both ``arm.left.held`` and
           ``arm.right.held`` against the *same* ``Item``
           instance, so each arm's view sees it.
        2. **Specific slot** — caller passed a single-slot
           ``EquipmentSlots`` value (``LEFT_HELD``, ``HEAD``, etc.).
           Slot must be both in the item's compatible mask and
           map to a real placement on this player's anatomy.
        3. **Auto-equip** (``slot is None`` or "either held" /
           other aggregate) — scan the item's compatible
           placements in declaration order and drop it into the
           first empty one. If nothing is empty, refuse so the
           caller isn't silently thrashing equipped gear.
        """
        # Identity guard — reject re-equip of an item that's
        # already placed somewhere. Prevents a user from accidentally
        # stomping the same item on top of itself.
        if self.is_equipped(item):
            return False, "Item already equipped."

        dirty = False
        msg = ""

        # Case 1: multi-slot items (two-handed weapons, future
        # paired gear). Expand through the item's FULL mask and
        # fill every placement it resolves to. Same Item instance
        # reference shared across placements.
        if item.slots & EquipmentSlots.MULTI_SLOT:
            placements = resolve_placements(item.slots)
            if not placements:
                return False, "Unable to auto-equip: Multi-slot item matched no equipment slots."
            # Two-handers need every required placement intact —
            # half-equipping a bow on the surviving arm would
            # leave a phantom reference and a useless wield.
            if any(self._placement_is_blocked(pn) for (pn, _) in placements):
                return False, "Unable to equip: That gear can't ride a part this damaged."
            removed: List[Equipment] = []
            for (part_name, key) in placements:
                ok, replaced = self.replace_equipment(item, part_name, key)
                if ok:
                    dirty = True
                    if replaced is not None and replaced is not item:
                        removed.append(replaced)
            if dirty and removed:
                msg = item_list_to_string(removed)
            elif not dirty:
                msg = "Unable to auto-equip: Multi-slot item matched no equipment slots."

        # Case 3 (handled before case 2 because auto-equip also
        # triggers when ``slot`` is an aggregate like ``EITHER_HELD``
        # — ``exclude_from_output`` names the aggregates). Find the
        # first empty placement compatible with the item. Blocked
        # placements (severed arm, crushed hand) are skipped so a
        # `$equip glove` lands on the surviving hand rather than
        # the destroyed one.
        #
        # When no empty placement exists, fall back to a quality-
        # gated displace: replace the worst-quality current occupant
        # IF the new item is strictly higher quality. Lets `$equip
        # wand.best` upgrade through a fully-handed loadout without
        # forcing the player to specify @l/@r every time. Equal-or-
        # worse new items don't displace — wouldn't be an upgrade.
        elif slot is None or (slot.name and EquipmentSlots.exclude_from_output(slot.name)):
            compatible = resolve_placements(item.slots)
            for (part_name, key) in compatible:
                if self._placement_is_blocked(part_name):
                    continue
                if self.part_equipment.get(part_name, {}).get(key) is None:
                    ok, replaced = self.replace_equipment(item, part_name, key)
                    if ok:
                        dirty = True
                        if replaced is not None:
                            msg = replaced.get_full_name()
                        break

            if not dirty:
                # No empty slot — try to upgrade through the
                # weakest current occupant. Only the new item's
                # quality matters; ties stay put so we don't
                # cycle a masterwork through itself when ``.best``
                # picks the already-equipped piece.
                worst = None
                worst_part = None
                worst_key = None
                for (part_name, key) in compatible:
                    if self._placement_is_blocked(part_name):
                        continue
                    cur = self.part_equipment.get(part_name, {}).get(key)
                    if cur is None:
                        continue
                    if worst is None or cur.quality.value["multiplier"] < worst.quality.value["multiplier"]:
                        worst = cur
                        worst_part = part_name
                        worst_key = key
                if (
                    worst is not None
                    and item.quality.value["multiplier"] > worst.quality.value["multiplier"]
                ):
                    ok, replaced = self.replace_equipment(item, worst_part, worst_key)
                    if ok:
                        dirty = True
                        if replaced is not None:
                            msg = replaced.get_full_name()

            if not dirty:
                msg = (
                    "Unable to auto-equip: None of the slots that the item could fill are empty. Either specify "
                    "the slot, or unequip the item occupying the desired slot."
                )

        # Case 2: specific slot. Must be in the item's compatible
        # mask AND resolve to a placement this player has.
        else:
            if slot & item.slots:
                target = SLOT_TO_PART_KEY.get(slot)
                if target is not None:
                    part_name, key = target
                    if self._placement_is_blocked(part_name):
                        return False, "Unable to equip: That part is too damaged to hold gear right now."
                    ok, replaced = self.replace_equipment(item, part_name, key)
                    if ok:
                        dirty = True
                        if replaced is not None:
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
            part_equipment=p.get("part_equipment"),
            last_active=p["last_active"] if "last_active" in p.keys() else None,
            health_regen=p.get("health_regen", 0),
            body_parts_health=p.get("body_parts_health"),
            social=p.get("social"),
            skills_schema_version=p.get("skills_schema_version"),
            loadouts=p.get("loadouts"),
            known_recipes=p.get("known_recipes"),
        )

        # 2026-04-21 migration: legacy ``equip_slots`` docs are
        # not supported by the loader — the one-shot migration
        # tool (``tools/migrate_equipment_to_parts.py``) must
        # run before this code is deployed. Hitting this check
        # means a doc slipped through unmigrated.
        if "equip_slots" in p and "part_equipment" not in p:
            raise RuntimeError(
                f"Player {p.get('_id')!r} still has legacy "
                "``equip_slots`` field — run "
                "``python -m tools.migrate_equipment_to_parts`` "
                "before starting the bot."
            )

        return player

    def gain_skill_experience(
        self,
        skill: str,
        damage: int = 0,
        bleed_rate: float = 1.0,
        *,
        hit: bool = True,
    ) -> None:
        """Q.6 formula E — skill XP with a committed-damage bonus plus
        a flat miss-path grant.

        - Hit path (``hit=True``): ``base + bonus`` where
          ``base = 5 + floor(5 * level**0.5)`` and
          ``bonus = int(damage * bleed_rate * 1.5)``.
          Two-handed skills double both terms. A zero-damage hit
          (trait immunity like physical-vs-spirit) still grants the
          base XP — connecting is committed even when damage shrugs.
        - Miss path (``hit=False``): flat ``2`` XP, not level-scaled
          — gives low-skill players a progression floor when they miss.
        - Capped at level 20 (no XP past the ceiling).
        """

        if skill not in self.skills:
            self.skills[skill] = 0

        skill_level = self.get_skill_level(skill)
        if skill_level >= 20:
            return

        if not hit:
            amt = 2
        else:
            base = 5 + floor(5 * (skill_level ** 0.5))
            bonus = int(max(0, damage) * bleed_rate * 1.5)
            if "two-handed" in skill:
                base *= 2
                bonus *= 2
            amt = base + bonus

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
        # Walk every ``(part, key)`` placement. Multi-placement
        # items (two-handed weapons, pair items) appear multiple
        # times because their references are shared — the
        # ``items_checked`` identity-list dedupes so bonuses aren't
        # double-counted.
        for item in self._iter_equipped_items():
            if isinstance(item, Armor) and not any(
                checked is item for checked in items_checked
            ):
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
        """Total dodge: body-part emergence (leg/wing mobility) plus armor
        bonuses, minus penalties from low-quality armor.

        Defers to :meth:`Creature.get_dodge` so leg injuries degrade
        dodge the same way they do for monsters, adds any positive
        bonuses from equipped armor, then subtracts the low-quality
        dodge tax from junk/ordinary pieces (see
        :meth:`_get_low_quality_armor_dodge_penalty`). Clamped at 0.
        """
        base = Creature.get_dodge(self)
        armor = self.get_armor_bonuses("dodge").get("dodge", 0)
        penalty = self._get_low_quality_armor_dodge_penalty()
        return max(0, base + armor - penalty)

    def _get_low_quality_armor_dodge_penalty(self) -> int:
        """Sum of dodge penalties imposed by worn ORDINARY-or-lower armor.

        Pieces above ORDINARY quality are fitted well enough that
        their bulk doesn't cost mobility; junk and ordinary pieces
        are stiff or ill-shaped enough to drag the wearer's dodge
        down. The per-piece value lives on each Armor subclass as
        :attr:`Armor.LOW_QUALITY_DODGE_PENALTY` — heavier shells
        (jerkin, rerebrace, greave) take the real hit while small
        pieces (gloves, hoods, decorative bands) stay at 0.
        Multi-placement items are deduped by identity.
        """
        penalty = 0
        items_checked = []
        for item in self._iter_equipped_items():
            if not isinstance(item, Armor):
                continue
            if any(checked is item for checked in items_checked):
                continue
            items_checked.append(item)
            if item.quality.value["multiplier"] <= 1.0:
                penalty += item.LOW_QUALITY_DODGE_PENALTY
        return penalty

    def get_health_max(self) -> int:
        """Tallies the total max health value for the given creature."""
        d = self.get_armor_bonuses("health_max")
        if "health_max" in d.keys():
            return max(0, d["health_max"] + self.health_max)
        return self.health_max

    def get_equipment(self, guild_name: str, show_all: bool = False) -> Embed:
        """Returns a discord embed for the player's equipment slots.

        Display order follows :data:`PLACEMENT_DISPLAY_ORDER` —
        head down to feet — so the rendering reads anatomically.
        A multi-placement item (two-handed weapon, paired gear)
        appears once per placement so the player can see e.g. a
        longsword is tying up both hands.

        Placements are grouped per body part (one field per part)
        because Phase D's segmented anatomy has 27 placements —
        above Discord's 25-field embed limit. Per-part grouping
        keeps every layer visible under ``show_all`` without
        tripping error 50035.
        """
        embed = Embed(title=f"Player Equipment", description=f"for {self.name} on {guild_name}", color=0x00FFFF)

        fields = [
            ("Equipped", "---------------------------------------------------", False),
        ]

        # Group placements by part in display order. One field per
        # part holds every placement's line; empty placements only
        # render when ``show_all`` is on.
        part_buckets: "Dict[str, List[str]]" = {}
        part_order: "List[str]" = []
        for (part_name, key) in PLACEMENT_DISPLAY_ORDER:
            if part_name not in self.part_equipment:
                continue
            if key not in self.part_equipment[part_name]:
                continue
            item = self.part_equipment[part_name][key]
            if item is None and not show_all:
                continue
            value = item.get_full_name() if item is not None else "_(empty)_"
            line = f"`{key}`: {value}"
            if part_name not in part_buckets:
                part_buckets[part_name] = []
                part_order.append(part_name)
            part_buckets[part_name].append(line)

        for part_name in part_order:
            fields.append((part_name, "\n".join(part_buckets[part_name]), False))

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
            # Mark equipped items with their placement(s). Multi-
            # placement items (two-handed, paired) get one tag per
            # placement so the player sees everywhere the item is
            # occupying — avoids the "why can't I sell this?"
            # confusion when one of the placements is off-screen.
            seen_placements = set()
            for part_name in self.part_equipment:
                for key, equipped in self.part_equipment[part_name].items():
                    if equipped is item and (part_name, key) not in seen_placements:
                        msg += f" [{part_name}.{key}]"
                        seen_placements.add((part_name, key))
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

        lh: Weapon = self.part_equipment.get("hand.left", {}).get("held")
        rh: Weapon = self.part_equipment.get("hand.right", {}).get("held")

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
        """Unequip ``item`` from every placement it currently occupies.

        Multi-placement items (two-handed weapons, paired gear) get
        cleared from every ``(part, key)`` at once — no partial
        un-equip state where half a pair is still on.
        """

        dirty = False
        msg = ""

        if item is None:
            return "Nothing to remove."

        for part_name in self.part_equipment:
            for key in list(self.part_equipment[part_name].keys()):
                if self.part_equipment[part_name][key] is item:
                    self.part_equipment[part_name][key] = None
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

        Centralized "player no longer owns this item" choke
        point — called by ``sell`` today, future trade and admin
        removal paths. Every call also prunes any saved-loadout
        references so ``$loadout load`` doesn't try to equip an
        item that's been sold, traded away, or otherwise removed.
        """

        if item == self.inventory[item.id] and not self.is_equipped(item):
            self._purge_item_refs(item)
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
            # ``part_equipment`` stores item ids per (part, key),
            # omitting empty placements so never-equipped players
            # don't bloat their doc with every anatomy key set to
            # null. ``from_dict`` and the constructor default-fill
            # the rest on load.
            "part_equipment": {},
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
            "skills_schema_version": self.skills_schema_version,
            # Sorted list for stable serialization. Empty list is
            # stripped below so never-learned-anything players don't
            # bloat their doc.
            "known_recipes": sorted(self.known_recipes),
        }

        # Empty ``social`` stays out of the saved doc so never-touched
        # players don't gain a noisy field on first save.
        if not self.social:
            del d["social"]
        if not self.known_recipes:
            del d["known_recipes"]

        for part_name, keys in self.part_equipment.items():
            for key, item in keys.items():
                if item is not None:
                    d["part_equipment"].setdefault(part_name, {})[key] = str(item.id)

        # Saved gear loadouts. ALWAYS written (including when
        # empty) because ``DB.update_player`` uses ``$set`` —
        # omitting the key on empty wouldn't remove the field
        # from an existing doc, so clearing the last loadout
        # would leave the stale data behind (observed 2026-04-22
        # TEST playtest: bot restart resurrected "cleared"
        # loadouts because the DB still held the pre-clear value).
        # The one-time "noisy ``loadouts: {}`` on first save" cost
        # for legacy docs is worth paying for correct state sync.
        d["loadouts"] = {
            label: {
                part_name: dict(keys)
                for part_name, keys in payload.items()
                if keys
            }
            for label, payload in self.loadouts.items()
        }

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
