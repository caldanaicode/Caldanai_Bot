from enum import Enum, IntFlag


class AggressionLevels(Enum):
	PASSIVE = 0			# Never attacks
	VENGEFUL = 1		# Hit & run
	RAMPAGE = 2			# Attacks until defeated or left alone


class CombatRanges(IntFlag):
	PERSONAL = 0x1		# Touch range
	MELEE = 0x2			# Melee weapon range (disadvantage at personal)
	RANGED = 0x4		# Thrown or Fired (disadvantage at melee or closer)


class DamageTypes(IntFlag):
	COMBINED = 0x1			# Determines whether combined flags represent doing all types of damage provided.
	PHYSICAL = 0x2			# General physical damage
	BLUDGEONING = 0x4		# Better for breaking body parts / mangling limbs / stunning
	PIERCING = 0x8			# Better for destroying organs
	SLASHING = 0x10			# Better for causing bleed / poison effects
	UNASPECTED = 0x20		# General non-elemental magical damage
	FIRE = 0x40				# Better for inflicting burns and does more damage against burn victims
	WATER = 0x80			# Better for healing, but can also turn the victims body against itself.
	EARTH = 0x100			# Better for buffs, but can also be used to petrify and fashion magical + physical weapons
	AIR = 0x200				# Better for utilities, and various effects when combined with other magics.


class Directions(IntFlag):
	SPAN_DIRECTIONS = 0x1
	NORTH = 0x2
	NORTHEAST = 0x4
	EAST = 0x8
	SOUTHEAST = 0x10
	SOUTH = 0x20
	SOUTHWEST = 0x40
	WEST = 0x80
	NORTHWEST = 0x100


class EquipmentSlots(IntFlag):
	MULTI_SLOT = 0x1
	FEET = 0x2
	SHINS = 0x4
	LEGS = 0x8
	WAIST = 0x10
	ABDOMEN = 0x20
	TORSO = 0x40
	SHOULDERS = 0x80
	ARMS = 0x100
	FOREARMS = 0x200
	GLOVES = 0x400
	LEFT_HELD = 0x800
	RIGHT_HELD = 0x1000
	LEFT_RING = 0x2000
	RIGHT_RING = 0x4000
	AMULET = 0x8000
	CAPE = 0x10000
	NECK = 0x20000
	FACE = 0x40000
	LEFT_EAR = 0x80000
	RIGHT_EAR = 0x100000
	HEAD = 0x200000
	TWO_HANDED = MULTI_SLOT | LEFT_HELD | RIGHT_HELD
	EITHER_HELD = LEFT_HELD | RIGHT_HELD
	LEFT_SIDE = LEFT_EAR | LEFT_RING | LEFT_HELD
	RIGHT_SIDE = RIGHT_EAR | RIGHT_RING | RIGHT_HELD
	EITHER_SIDE = LEFT_SIDE | RIGHT_SIDE

	@classmethod
	def exclude_from_output(cls, name: str):
		return name in (
			EquipmentSlots.MULTI_SLOT.name, EquipmentSlots.RIGHT_SIDE.name, EquipmentSlots.TWO_HANDED.name,
			EquipmentSlots.LEFT_SIDE.name, EquipmentSlots.EITHER_SIDE.name, EquipmentSlots.EITHER_HELD.name
		)


class InjuryLevels(IntFlag):
	NONE = 0x0
	MINOR = 0x1
	MODERATE = 0x2
	SEVERE = 0x4
	USELESS = 0x8


class Pronouns(Enum):
	SUBJECTIVE = 'subjective'
	OBJECTIVE = 'objective'
	POSSESSIVE = 'possessive'
	ADJECTIVE = 'adjective'
	REFLEXIVE = 'reflexive'


class Qualities(Enum):
	JUNK = {'color': 0x777777, 'frequency': 0.6, 'multiplier': 0.75}
	ORDINARY = {'color': 0xffffff, 'frequency': 0.5, 'multiplier': 1.0}
	FINE = {'color': 0x00ff00, 'frequency': 0.25, 'multiplier': 1.25}
	QUALITY = {'color': 0x0000ff, 'frequency': 0.10, 'multiplier': 1.5}
	SUPERIOR = {'color': 0x800080, 'frequency': 0.05, 'multiplier': 1.75}
	MASTERWORK = {'color': 0xffd700, 'frequency': 0.01, 'multiplier': 2.0}

	@classmethod
	def from_scale(cls, value: int, minimum: int = 1, maximum: int = 100) -> 'Qualities':
		lb = min(minimum, maximum)
		ub = max(minimum, maximum)
		v = lb if value < lb else ub if value > maximum else value
		normalized = round((v - lb + 1) / (ub - lb + 1), 2)
		quality = max(
			list(filter(lambda q: q.value['frequency'] <= normalized, Qualities)),
			key=lambda q: q.value['frequency']
		)
		return quality


class Roles(Enum):
	ACTIVE = 'Active RPG Player'
	COMBAT_MAIN = 'RPG Main Channel Combatant'
	INACTIVE = 'Inactive RPG Player'
	ALL = 'RPG Player'


class Seasons(Enum):
	BRIGHTBLOOM = 0
	SOLSTIME = 1
	LEAFGLOW = 2
	FROSTFALL = 3


class Stats(Enum):
	ATTACK = 'attack'
	DEFENSE = 'defense'
	DODGE = 'dodge'
	HEALTH_MAX = 'max health'


class TimesOfDay(IntFlag):
	DAWN = 0x1
	MORNING = 0x2
	NOON = 0x4
	AFTERNOON = 0x8
	EVENING = 0x10
	DUSK = 0x20
	NIGHT = 0x40


class TimePartitions(IntFlag):
	AURORAL = TimesOfDay.DAWN
	DIURNAL = TimesOfDay.DAWN | TimesOfDay.MORNING | TimesOfDay.NOON | TimesOfDay.AFTERNOON | TimesOfDay.EVENING
	CREPUSCULAR = TimesOfDay.EVENING | TimesOfDay.DUSK
	NOCTURNAL = TimesOfDay.DUSK | TimesOfDay.NIGHT
	CATHEMERAL = AURORAL | DIURNAL | CREPUSCULAR | NOCTURNAL


class WeatherPatterns(IntFlag):
	CLEAR = 0x0				# No particular weather effects, nice clear sky
	CLOUDY = 0x1			# Clouds without precipitation
	FOG = 0x2				# Extremely low clouds with no wind
	PRECIPITATION = 0x4		# Rain / Snow, depending on environment and season
	WIND = 0x8				# Windy


class WeatherSeverities(IntFlag):
	LIGHT = 0x1
	MODERATE = 0x2
	HEAVY = 0x4
	SEVERE = 0x8
