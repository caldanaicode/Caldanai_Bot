from enum import Enum, IntFlag, auto


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

    def __str__(self):
        result = []

        if (self != 0 and (self & (self - 1)) == 0) or self in (DamageTypes.ALL, DamageTypes.ANY):
            return self.name.lower()

        if self & DamageTypes.RANGED:
            result.append("ranged")

        if self & DamageTypes.MAGICAL:
            result.append("magical")

        for t in DamageTypes:
            if t in (DamageTypes.ALL, DamageTypes.ANY, DamageTypes.COMBINED, DamageTypes.MAGICAL, DamageTypes.RANGED):
                continue

            if self & t:
                if t & DamageTypes.COMBINED and self != t:
                    continue

                result.append(t.name.lower())

        return " ".join(result)

    @property
    def emoji(self) -> str:
        """Returns a string of emoji representing this damage type.

        Combined flags produce concatenated emoji in a consistent order
        (ranged → magical → physical → elemental). Returns an empty string
        for zero-value flags or flags without an emoji mapping.
        """
        if int(self) == 0:
            return ""
        parts = []
        for base in _DAMAGE_TYPE_EMOJI_ORDER:
            if self & base and base in _DAMAGE_TYPE_EMOJI:
                parts.append(_DAMAGE_TYPE_EMOJI[base])
        return "".join(parts)


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
}

# Display order for combined damage types — ranged/magical modifiers first,
# then physical attack shapes, then elemental flavors.
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
    MULTI_SLOT = 1
    """Indicates that an item equips to multiple slots simultaneously."""
    FEET = 1 << 1
    SHINS = 1 << 2
    LEGS = 1 << 3
    WAIST = 1 << 4
    ABDOMEN = 1 << 5
    TORSO = 1 << 6
    SHOULDERS = 1 << 7
    ARMS = 1 << 8
    FOREARMS = 1 << 9
    GLOVES = 1 << 10
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
    TWO_HANDED = MULTI_SLOT | LEFT_HELD | RIGHT_HELD
    EITHER_HELD = LEFT_HELD | RIGHT_HELD
    LEFT_SIDE = LEFT_EAR | LEFT_RING | LEFT_HELD
    RIGHT_SIDE = RIGHT_EAR | RIGHT_RING | RIGHT_HELD
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
        )


class InjuryLevels(IntFlag):
    NONE = 0
    MINOR = 1
    MODERATE = 1 << 1
    SEVERE = 1 << 2
    USELESS = 1 << 3


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
    """Creature size category. Affects dodge/defense modifiers and part HP scaling."""
    TINY     = {"dodge_mod": 1.5, "defense_mod": 0.5, "hp_scale": 0.25}
    SMALL    = {"dodge_mod": 1.25, "defense_mod": 0.75, "hp_scale": 0.5}
    MEDIUM   = {"dodge_mod": 1.0, "defense_mod": 1.0, "hp_scale": 1.0}
    LARGE    = {"dodge_mod": 0.75, "defense_mod": 1.25, "hp_scale": 2.0}
    HUGE     = {"dodge_mod": 0.5, "defense_mod": 1.5, "hp_scale": 4.0}
    COLOSSAL = {"dodge_mod": 0.25, "defense_mod": 2.0, "hp_scale": 8.0}


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
    CLEAR = 0
    """No particular weather effects, nice clear sky"""
    CLOUDY = 1
    """Clouds without precipitation"""
    FOG = 1 << 1
    """Extremely low clouds with no wind"""
    PRECIPITATION = 1 << 2
    """Rain / Snow, depending on environment and season"""
    WIND = 1 << 3
    """Windy"""


class WeatherSeverities(IntFlag):
    LIGHT = 1
    MODERATE = 1 << 1
    HEAVY = 1 << 2
    SEVERE = 1 << 3


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
