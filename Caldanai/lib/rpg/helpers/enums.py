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
	PHYSICAL = 0x1			# General physical damage
	BLUDGEONING = 0x2		# Better for breaking body parts / mangling limbs / stunning
	PIERCING = 0x4			# Better for destroying organs
	SLASHING = 0x8			# Better for causing bleed / poison effects
	UNASPECTED = 0x10		# General non-elemental magical damage
	FIRE = 0x20				# Better for inflicting burns and does more damage against burn victims
	WATER = 0x40			# Better for healing, but can also turn the victims body against itself.
	EARTH = 0x80			# Better for buffs, but can also be used to petrify and fashion magical + physical weapons
	AIR = 0x100				# Better for utilities, and various effects when combined with other magics.


class Directions(IntFlag):
	EAST = 0x1
	NORTH = 0x2
	WEST = 0x4
	SOUTH = 0x8
	NORTHEAST = NORTH | EAST
	NORTHWEST = NORTH | WEST
	SOUTHEAST = SOUTH | EAST
	SOUTHWEST = SOUTH | WEST


class EquipmentSlots(IntFlag):
	NONE = 0x0
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
			EquipmentSlots.MULTI_SLOT.name, EquipmentSlots.NONE.name, EquipmentSlots.RIGHT_SIDE.name,
			EquipmentSlots.TWO_HANDED.name, EquipmentSlots.LEFT_SIDE.name, EquipmentSlots.EITHER_SIDE.name,
			EquipmentSlots.EITHER_HELD.name
		)


class InjuryLevels(IntFlag):
	NONE = 0x0
	MINOR = 0x1
	MODERATE = 0x2
	SEVERE = 0x4


class Pronouns(Enum):
	SUBJECTIVE = 'subjective'
	OBJECTIVE = 'objective'
	POSSESSIVE = 'possessive'
	ADJECTIVE = 'adjective'
	REFLEXIVE = 'reflexive'


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
	DEFENSE = 'defense'
	DODGE = 'dodge'
	HEALTH_MAX = 'health_max'


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
