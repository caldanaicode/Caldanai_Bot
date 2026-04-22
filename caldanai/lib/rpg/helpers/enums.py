from enum import Enum, IntFlag, auto
from typing import Optional


class AggressionLevels(IntFlag):
    PASSIVE = 0
    """Never attacks"""
    VENGEFUL = 1
    """Hit & run"""
    RAMPAGE = 2
    """Attacks until defeated or left alone"""
    SURVIVE = 4
    """Attacks until low health, then flees"""
    RANDOM = 8
    """Might flee or attack with every turn"""


class CombatRanges(IntFlag):
    PERSONAL = 1
    """Touch range"""
    MELEE = 2
    """Melee weapon range (disadvantage at personal)"""
    RANGED = 4
    """Thrown or Fired (disadvantage at melee or closer)"""


class DamageTypes(IntFlag):
    """Enumeration containing damage types"""

    COMBINED = 1
    """Determines whether combined flags represent doing all types of damage provided."""
    RANGED = 1 << 1
    """Whether damage counts as ranged"""
    MAGICAL = 1 << 2
    """Whether damage counts as magical"""

    BLUDGEONING = 1 << 3
    """Better for breaking body parts / mangling limbs / stunning"""
    PIERCING = 1 << 4
    """Better for destroying organs"""
    SLASHING = 1 << 5
    """Better for causing bleed / poison effects"""

    DARK = 1 << 6
    """Darkness-based damage, can invert elements, and useful against light-based critters"""
    LIGHT = 1 << 7
    """Light-based damage, useful against dark-based critters"""
    FIRE = 1 << 8
    """Better for inflicting burns and does more damage against burn victims"""
    WATER = 1 << 9
    """Better for healing, but can also turn the victims body against itself"""
    EARTH = 1 << 10
    """Better for buffs, but can also be used to petrify and fashion magical + physical weapons"""
    AIR = 1 << 11
    """Better for utilities, and various effects when combined with other magics"""
    MATHEMAGICAL = 1 << 12
    """Damage dealt through the power of mathematics. Primes hit different."""

    # Combinations
    ANY = RANGED | MAGICAL | BLUDGEONING | PIERCING | SLASHING | DARK | LIGHT | FIRE | WATER | EARTH | AIR | MATHEMAGICAL
    """Indicates any damage type"""
    ALL = COMBINED | ANY
    """Indicates all damage types combined (which should be rare)"""

    # ------------------------------------------------------------------
    # Compound elemental aliases.
    #
    # Each alias bundles its component bits with ``COMBINED`` so trait
    # matching treats the value as an atomic compound. Without
    # ``COMBINED``, a ``DARK | WATER`` trait would fire on pure-water
    # OR pure-dark attacks via the bit-overlap branch in
    # ``Creature.get_trait_multiplier``; WITH ``COMBINED``, it only
    # fires on damage that's been declared as a compound event of
    # those bits — i.e. an actual ice attack.
    #
    # NOT a storage drop-in for legacy values: the alias int value
    # is ``WATER | DARK | COMBINED``, which differs from a legacy
    # ``WATER | DARK`` by exactly the COMBINED bit (value 1). So
    # legacy stored ints (or skill names derived from them) do NOT
    # auto-rename — they need explicit migration. Skill-name
    # migration lives in ``Player._migrate_skill_keys``.
    # ------------------------------------------------------------------

    ICE       = WATER | DARK  | COMBINED
    POISON    = DARK  | AIR   | COMBINED
    LIGHTNING = LIGHT | AIR   | COMBINED
    ACID      = EARTH | WATER | COMBINED

    def __str__(self):
        if int(self) == 0:
            return ""

        cls = type(self)

        # Single-bit values and the ALL/ANY special cases keep their
        # canonical name as-is.
        if (self & (self - 1)) == 0:
            return cls(int(self)).name.lower()
        if self == DamageTypes.ALL or self == DamageTypes.ANY:
            return self.name.lower()

        val = int(self)

        # First pass: greedy-match compound elemental aliases (any
        # multi-bit member that includes the COMBINED bit, excluding
        # ALL itself which is the "everything" sentinel). Largest
        # bitmask first so a hypothetical multi-element compound
        # would consume its bits before sub-aliases do.
        compound_aliases = sorted(
            (
                m for name, m in cls.__members__.items()
                if name != "ALL"
                and (m.value & (m.value - 1)) != 0  # multi-bit
                and (m.value & DamageTypes.COMBINED)
            ),
            key=lambda m: bin(m.value).count("1"),
            reverse=True,
        )
        matched_aliases = []
        for alias in compound_aliases:
            if (val & alias.value) == alias.value:
                matched_aliases.append(alias.name.lower())
                val &= ~alias.value

        # Second pass: legacy single-bit accumulation for whatever
        # bits the aliases didn't consume. RANGED / MAGICAL come first
        # to preserve the original output ordering ("ranged piercing"
        # rather than "piercing ranged").
        single_bits = []
        if val & DamageTypes.RANGED:
            single_bits.append("ranged")
            val &= ~int(DamageTypes.RANGED)
        if val & DamageTypes.MAGICAL:
            single_bits.append("magical")
            val &= ~int(DamageTypes.MAGICAL)
        for t in cls:
            if t in (cls.ALL, cls.ANY, cls.COMBINED, cls.MAGICAL, cls.RANGED):
                continue
            if (t.value & (t.value - 1)) != 0:
                continue  # multi-bit member (alias) — handled in pass 1
            if val & t:
                single_bits.append(t.name.lower())
                val &= ~int(t)

        # Single-bit components come first, then the alias name, so an
        # ice axe reads "slashing ice" rather than "ice slashing" —
        # matches the existing convention of physical-bit-first.
        return " ".join(single_bits + matched_aliases)

    @property
    def canonical(self) -> str:
        """Lossless canonical form for storage / keying — same as
        ``__str__`` but explicitly appends ``"combined"`` when the
        COMBINED bit is set without being absorbed by a compound
        alias.

        Used to derive skill keys (``one-handed bludgeoning fire
        combined`` for a torch) so that COMBINED-bit damage types
        don't share keys with their non-COMBINED counterparts. Player-
        facing display layers should call ``display_skill_name`` to
        strip the technical marker before showing.
        """
        base = str(self)
        if not (int(self) & DamageTypes.COMBINED):
            return base
        # COMBINED bit set. Did a compound alias absorb it?
        cls = type(self)
        alias_names = {
            m.name.lower() for m in cls.__members__.values()
            if m.name != "ALL"
            and (m.value & (m.value - 1)) != 0
            and (m.value & DamageTypes.COMBINED)
        }
        if any(word in alias_names for word in base.split()):
            return base  # alias name implies COMBINED
        return f"{base} combined".strip() if base else "combined"

    @staticmethod
    def display_skill_name(skill_key: str) -> str:
        """Strip internal ``"combined"`` markers from a skill key
        for player-facing display. ``"one-handed bludgeoning fire
        combined"`` → ``"one-handed bludgeoning fire"``. Idempotent;
        skill keys without the marker pass through unchanged."""
        return skill_key.replace(" combined", "").strip()

    @staticmethod
    def from_skill_key(skill_key: str) -> Optional["DamageTypes"]:
        """Reverse of ``canonical``: parse a skill key (e.g.
        ``"one-handed slashing ice"``, ``"two-handed bludgeoning
        fire combined"``) back into a ``DamageTypes`` bitmask.

        Tokenizes the key and OR-accumulates any word that matches
        a ``DamageTypes`` member name (case-insensitive). Words that
        don't match (``"one-handed"``, ``"two-handed"``, ``"unarmed"``,
        or skill keys without damage bits at all like ``"natural"``)
        contribute nothing. Returns ``None`` when no damage-type bits
        were found so callers can short-circuit.

        Intended for display layers that want to render an emoji
        or icon alongside a skill name without pre-storing the
        damage type separately.
        """
        if not skill_key:
            return None
        members = DamageTypes.__members__
        bits = DamageTypes(0)
        for word in skill_key.split():
            name = word.upper()
            if name in members:
                bits |= members[name]
        return bits if int(bits) else None

    @property
    def emoji(self) -> str:
        """Returns a string of emoji representing this damage type.

        Compound elemental aliases (ICE, POISON, LIGHTNING, ACID)
        get their own dedicated emoji; the rest of the bits fall back
        to single-bit emoji concatenation in the canonical order
        (ranged → magical → physical → elemental). Mirrors the
        alias-aware ``__str__`` so a SLASHING+ICE attack reads as
        "🔪🧊" rather than "🔪🌑💧".

        Returns an empty string for zero-value flags or flags without
        an emoji mapping.
        """
        if int(self) == 0:
            return ""
        cls = type(self)
        val = int(self)

        # Greedy-match compound aliases that have a dedicated emoji.
        # Largest bitmask first so a hypothetical multi-element compound
        # consumes its bits before sub-aliases do.
        compound_aliases = sorted(
            (
                m for name, m in cls.__members__.items()
                if name != "ALL"
                and (m.value & (m.value - 1)) != 0  # multi-bit
                and (m.value & DamageTypes.COMBINED)
                and m in _DAMAGE_TYPE_EMOJI
            ),
            key=lambda m: bin(m.value).count("1"),
            reverse=True,
        )
        matched_alias_emoji = []
        for alias in compound_aliases:
            if (val & alias.value) == alias.value:
                matched_alias_emoji.append(_DAMAGE_TYPE_EMOJI[alias])
                val &= ~alias.value

        # Single-bit fallback for whatever bits the aliases didn't claim.
        single_bit_emoji = []
        for base in _DAMAGE_TYPE_EMOJI_ORDER:
            if val & base and base in _DAMAGE_TYPE_EMOJI:
                single_bit_emoji.append(_DAMAGE_TYPE_EMOJI[base])
                val &= ~int(base)

        # Single-bit emoji first, then alias emoji — matches the
        # ordering of ``__str__`` ("slashing ice", "🔪🧊").
        return "".join(single_bit_emoji + matched_alias_emoji)


_DAMAGE_TYPE_EMOJI = {
    DamageTypes.RANGED: "🏹",
    DamageTypes.MAGICAL: "✨",
    DamageTypes.BLUDGEONING: "🔨",
    DamageTypes.PIERCING: "🪡",
    DamageTypes.SLASHING: "🔪",
    DamageTypes.DARK: "🌑",
    DamageTypes.LIGHT: "☀️",
    DamageTypes.FIRE: "🔥",
    DamageTypes.WATER: "💧",
    DamageTypes.EARTH: "🌍",
    DamageTypes.AIR: "💨",
    DamageTypes.MATHEMAGICAL: "🧮",
    # Compound elemental aliases — each gets a dedicated icon so
    # combat tables read at a glance ("🧊" for ice rather than the
    # overloaded "🌑💧" which used to also mean "moon + water").
    DamageTypes.ICE: "🧊",
    DamageTypes.POISON: "🧪",
    DamageTypes.LIGHTNING: "⚡",
    DamageTypes.ACID: "⚗️",
}

# Display order for the single-bit fallback loop in ``DamageTypes.emoji``.
# *Only single-bit damage types belong here* — compound aliases (ICE,
# POISON, LIGHTNING, ACID) are matched strictly (all-bits-present) in
# the compound-alias loop above; the fallback loop uses a loose
# ``val & base`` test that would spuriously fire on any alias that
# shares the COMBINED bit (e.g. a non-ice RANGED|MAGICAL|COMBINED wand
# would leak a 🧊). Ranged / magical modifiers first, then physical
# attack shapes, then elemental single bits.
_DAMAGE_TYPE_EMOJI_ORDER = (
    DamageTypes.RANGED,
    DamageTypes.MAGICAL,
    DamageTypes.BLUDGEONING,
    DamageTypes.PIERCING,
    DamageTypes.SLASHING,
    DamageTypes.DARK,
    DamageTypes.LIGHT,
    DamageTypes.FIRE,
    DamageTypes.WATER,
    DamageTypes.EARTH,
    DamageTypes.AIR,
    DamageTypes.MATHEMAGICAL,
)


class Directions(IntFlag):
    SPAN_DIRECTIONS = 1
    """Indicates that directions are combined."""
    NORTH = 1 << 1
    NORTHEAST = 1 << 2
    EAST = 1 << 3
    SOUTHEAST = 1 << 4
    SOUTH = 1 << 5
    SOUTHWEST = 1 << 6
    WEST = 1 << 7
    NORTHWEST = 1 << 8


class EquipmentSlots(IntFlag):
    # Flag for items that occupy multiple slots simultaneously.
    # Today that's two-handed weapons; historically it also
    # covered multi-part armor (high-collared cape's old
    # NECK+CAPE coverage). Kept available for future items that
    # span multiple placements — manacles, magical sets that
    # refuse to function alone, etc. Equip logic expands the item
    # into every slot its mask OR's in.
    MULTI_SLOT = 1
    """Indicates that an item equips to multiple slots simultaneously."""
    # 2026-04-22 rework: every left/right anatomical pair now has
    # its own bit. Old unsplit pair-slots (``ARMS``, ``FOREARMS``,
    # ``GLOVES``, ``LEGS``, ``SHINS``, ``FEET``) are preserved as
    # COMPOUND aliases — same bit math as ``EITHER_HELD``, so an
    # item declaring ``slots = ARMS`` still fits "either bracer
    # slot" without occupying both. A pair item that must span
    # both sides (e.g. a pair of gloves sold together) adds the
    # ``MULTI_SLOT`` flag to force multi-placement.
    #
    # Rationale: sided ownership composes with limb-loss better —
    # destroying the right arm sends only the right-side gear back
    # to inventory, not the left.
    LEFT_FOOT = 1 << 1
    LEFT_SHIN = 1 << 2
    LEFT_LEG = 1 << 3
    WAIST = 1 << 4
    # Gap left by 2026-04-21 cleanup: ABDOMEN (1 << 5) removed — no
    # items used it. Bit left unassigned rather than renumbering the
    # rest so persisted IntFlag values in Mongo keep their meaning.
    TORSO = 1 << 6
    # Gap: SHOULDERS (1 << 7) removed same sweep, same reason.
    LEFT_ARM = 1 << 8
    LEFT_FOREARM = 1 << 9
    LEFT_GLOVE = 1 << 10
    LEFT_HELD = 1 << 11
    RIGHT_HELD = 1 << 12
    LEFT_RING = 1 << 13
    RIGHT_RING = 1 << 14
    AMULET = 1 << 15
    CAPE = 1 << 16
    NECK = 1 << 17
    FACE = 1 << 18
    LEFT_EAR = 1 << 19
    RIGHT_EAR = 1 << 20
    HEAD = 1 << 21
    # 2026-04-22: new right-side bits to mirror their left
    # counterparts. Contiguous block so the enum's layout reads
    # "old single-side and neutral slots | new right-side pairs."
    RIGHT_ARM = 1 << 22
    RIGHT_FOREARM = 1 << 23
    RIGHT_GLOVE = 1 << 24
    RIGHT_LEG = 1 << 25
    RIGHT_SHIN = 1 << 26
    RIGHT_FOOT = 1 << 27
    # Compound aliases — "either side" shapes. Items declaring
    # these fit in one side at a time, just like ``EITHER_HELD``.
    # Add ``| MULTI_SLOT`` to the declaration to force both sides.
    ARMS = LEFT_ARM | RIGHT_ARM
    FOREARMS = LEFT_FOREARM | RIGHT_FOREARM
    GLOVES = LEFT_GLOVE | RIGHT_GLOVE
    LEGS = LEFT_LEG | RIGHT_LEG
    SHINS = LEFT_SHIN | RIGHT_SHIN
    FEET = LEFT_FOOT | RIGHT_FOOT
    TWO_HANDED = MULTI_SLOT | LEFT_HELD | RIGHT_HELD
    EITHER_HELD = LEFT_HELD | RIGHT_HELD
    LEFT_SIDE = (
        LEFT_EAR | LEFT_RING | LEFT_HELD | LEFT_ARM | LEFT_FOREARM
        | LEFT_GLOVE | LEFT_LEG | LEFT_SHIN | LEFT_FOOT
    )
    RIGHT_SIDE = (
        RIGHT_EAR | RIGHT_RING | RIGHT_HELD | RIGHT_ARM | RIGHT_FOREARM
        | RIGHT_GLOVE | RIGHT_LEG | RIGHT_SHIN | RIGHT_FOOT
    )
    EITHER_SIDE = LEFT_SIDE | RIGHT_SIDE

    @classmethod
    def exclude_from_output(cls, name: str):
        return name in (
            EquipmentSlots.MULTI_SLOT.name,
            EquipmentSlots.RIGHT_SIDE.name,
            EquipmentSlots.TWO_HANDED.name,
            EquipmentSlots.LEFT_SIDE.name,
            EquipmentSlots.EITHER_SIDE.name,
            EquipmentSlots.EITHER_HELD.name,
            # Compound "either-side" aliases — not distinct
            # placements, don't render as their own slot label
            # in item embeds.
            EquipmentSlots.ARMS.name,
            EquipmentSlots.FOREARMS.name,
            EquipmentSlots.GLOVES.name,
            EquipmentSlots.LEGS.name,
            EquipmentSlots.SHINS.name,
            EquipmentSlots.FEET.name,
        )


class InjuryLevels(IntFlag):
    NONE = 0
    MINOR = 1
    MODERATE = 1 << 1
    SEVERE = 1 << 2
    USELESS = 1 << 3


# Player-facing (dot, word, ansi_color_code) pairings for each injury
# level. Kept next to the enum so any command rendering injury state
# (e.g. ``$health``, future ``$profile`` injury section) imports one
# canonical mapping. The dot is a universal status gauge; the ANSI
# code colors the status word inside a ```ansi fence so the word
# itself reinforces the severity. ANSI doesn't have a distinct orange,
# so SEVERE shares red with USELESS — the dot still distinguishes them.
INJURY_LEVEL_DISPLAY = {
    InjuryLevels.NONE:     ("🟢", "unharmed",  "32"),  # green
    InjuryLevels.MINOR:    ("🟡", "bruised",   "33"),  # yellow
    InjuryLevels.MODERATE: ("🟠", "wounded",   "33"),  # yellow
    InjuryLevels.SEVERE:   ("🔴", "maimed",    "31"),  # red
    InjuryLevels.USELESS:  ("⚫", "destroyed", "30"),  # gray
}


class Pronouns(Enum):
    SUBJECTIVE = "subjective"
    """He, She, They, etc."""
    OBJECTIVE = "objective"
    """Her, Him, Them, etc."""
    POSSESSIVE = "possessive"
    """Hers, His, Their, etc."""
    ADJECTIVE = "adjective"
    """Her, His, Their, etc."""
    REFLEXIVE = "reflexive"
    """Herself, Himself, Themself, etc."""

    @property
    def form(self) -> str:
        """Single-character form letter used by the narration parser
        (``@1s``, ``@1o``, ``@1p``, ``@1a``, ``@1r``). First letter of
        the enum name, lowered. Override per-member if a future
        pronoun's initial would collide with an existing one."""
        return self.name[0].lower()


class Qualities(Enum):
    JUNK = {"color": 0x777777, "frequency": 0.6, "multiplier": 0.75}
    ORDINARY = {"color": 0xFFFFFF, "frequency": 0.5, "multiplier": 1.0}
    FINE = {"color": 0x00FF00, "frequency": 0.25, "multiplier": 1.25}
    QUALITY = {"color": 0x0000FF, "frequency": 0.10, "multiplier": 1.5}
    SUPERIOR = {"color": 0x800080, "frequency": 0.05, "multiplier": 1.75}
    MASTERWORK = {"color": 0xFFD700, "frequency": 0.01, "multiplier": 2.0}

    @classmethod
    def from_scale(cls, value: int, minimum: int = 1, maximum: int = 100) -> "Qualities":
        lb = min(minimum, maximum)
        ub = max(minimum, maximum)
        v = lb if value < lb else ub if value > maximum else value
        normalized = round((v - lb + 1) / (ub - lb + 1), 2)
        quality = max(
            list(filter(lambda q: q.value["frequency"] <= normalized, Qualities)), key=lambda q: q.value["frequency"]
        )
        return quality


class Roles(Enum):
    ACTIVE = "Active RPG Player"
    COMBAT_MAIN = "RPG Combatant"
    INACTIVE = "Inactive RPG Player"
    ALL = "RPG Player"


class Seasons(Enum):
    BRIGHTBLOOM = 0
    SOLSTIME = 1
    LEAFGLOW = 2
    FROSTFALL = 3


class Stat(Enum):
    """Canonical creature stat identifiers.

    Used as keys in body-part debuff tables
    (``{Stat.DODGE: -3, Stat.ATTACK: -1}``) and by ``Creature`` stat getters
    that aggregate ``part.get_stat_modifier(stat, owner=self)`` across parts.
    """

    ATTACK = auto()
    DEFENSE = auto()
    DODGE = auto()
    HEALTH_MAX = auto()
    HIT = auto()


class Size(Enum):
    """Creature size category. Affects dodge/defense modifiers, part
    HP scaling, and relative-size targeting difficulty.

    Fields
    ======

    - ``dodge_mod`` — multiplier on the creature's own rolled dodge
      (smaller creatures are nimbler overall).
    - ``defense_mod`` — multiplier on rolled defense (bigger creatures
      have more mass to shrug off blows).
    - ``hp_scale`` — body-part HP multiplier applied by
      ``Creature._scale_part_hp``.
    - ``attack_scale`` — proxy for silhouette size when computing
      cross-size targeting difficulty. Used in ``Creature.do_attack``
      as ``attacker_scale / target_scale`` (clamped) so a TINY
      attacker finds a HUGE target's parts easier to reach, and a
      HUGE attacker finds a TINY target's parts harder to pinpoint.
      The ratio is clamped to ``[0.5, 2.0]`` at the call site so
      extreme disparities (pixie vs colossal dragon) don't trivialize
      the math.
    """
    TINY     = {"dodge_mod": 1.5,  "defense_mod": 0.5, "hp_scale": 0.25, "attack_scale": 0.5}
    SMALL    = {"dodge_mod": 1.25, "defense_mod": 0.75, "hp_scale": 0.5,  "attack_scale": 0.75}
    MEDIUM   = {"dodge_mod": 1.0,  "defense_mod": 1.0,  "hp_scale": 1.0,  "attack_scale": 1.0}
    LARGE    = {"dodge_mod": 0.75, "defense_mod": 1.25, "hp_scale": 2.0,  "attack_scale": 1.25}
    HUGE     = {"dodge_mod": 0.5,  "defense_mod": 1.5,  "hp_scale": 4.0,  "attack_scale": 1.5}
    COLOSSAL = {"dodge_mod": 0.25, "defense_mod": 2.0,  "hp_scale": 8.0,  "attack_scale": 1.75}


class Reach(Enum):
    """How an attack reaches its target.

    Used by ``AttackSource.reach`` to declare the reach class of an
    attack, and by body-part ``exposure`` tables
    (``Dict[Reach, float]``) to express how exposed a part is to each
    reach type — e.g. a dragon's head might be
    ``{Reach.MELEE: 0.05, Reach.THROWN: 0.5, Reach.RANGED: 1.0}``.
    """

    MELEE = auto()
    """Default for unarmed and most weapons."""
    REACH = auto()
    """Polearms, whips — melee with extended reach."""
    THROWN = auto()
    """Daggers, javelins, improvised thrown attacks."""
    RANGED = auto()
    """Bows, crossbows, magic."""


class Stats(Enum):
    ATTACK = "attack"
    DEFENSE = "defense"
    DODGE = "dodge"
    HEALTH_MAX = "max health"


class TimesOfDay(IntFlag):
    DAWN = 1
    MORNING = 1 << 1
    NOON = 1 << 2
    AFTERNOON = 1 << 3
    EVENING = 1 << 4
    DUSK = 1 << 5
    NIGHT = 1 << 6


class TimePartitions(IntFlag):
    """Enumeration defining the times of days."""

    AURORAL = TimesOfDay.DAWN
    """Active at dawn"""

    DIURNAL = (
        TimesOfDay.DAWN
        | TimesOfDay.MORNING
        | TimesOfDay.NOON
        | TimesOfDay.AFTERNOON
        | TimesOfDay.EVENING)
    """Active from dawn through evening"""

    CREPUSCULAR = TimesOfDay.EVENING | TimesOfDay.DUSK
    """Active during evening and dusk"""

    NOCTURNAL = TimesOfDay.DUSK | TimesOfDay.NIGHT
    """Active at dusk and night"""

    CATHEMERAL = AURORAL | DIURNAL | CREPUSCULAR | NOCTURNAL
    """Active at any time of day or night"""


class WeatherPatterns(IntFlag):
    CLEAR = 1
    """No active weather components — explicitly a flag so monster
    ``weather_partition`` masks can opt-in to clear-weather spawning."""
    CLOUDY = 1 << 1
    """Clouds without precipitation"""
    FOG = 1 << 2
    """Extremely low clouds with no wind"""
    PRECIPITATION = 1 << 3
    """Rain / Snow, depending on environment and season"""
    WIND = 1 << 4
    """Windy"""
    ALL = CLEAR | CLOUDY | FOG | PRECIPITATION | WIND
    """Default for ``weather_partition`` — monster spawns in any weather."""


class WeatherSeverities(Enum):
    """Intensity of a single weather component. Ordered: LIGHT < MODERATE
    < HEAVY < SEVERE. Plain ``Enum`` rather than ``IntFlag`` because a
    single component has one severity level at a time — combining
    LIGHT | HEAVY has no meaningful interpretation. Weather state
    holds ``Dict[WeatherPatterns, WeatherSeverities]`` so different
    components can have independent severities (heavy rain with only
    light wind, etc.)."""
    LIGHT = 1
    MODERATE = 2
    HEAVY = 3
    SEVERE = 4


class TrophicLevels(IntFlag):
    HERBIVORE = 0x1
    CARNIVORE = 0x2
    INSECTIVORE = 0x4
    PISCIVORE = 0x8
    FRUGIVORE = 0x10
    FOLIVORE = 0x20
    GRANIVORE = 0x40
    NECTARIVORE = 0x80
    DETRITIVORE = 0x100
    NECROPHAGOUS = 0x200
    OMNIVORE = HERBIVORE | CARNIVORE
