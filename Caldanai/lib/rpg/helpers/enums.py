from enum import Enum, IntFlag

from Caldanai.lib.rpg.inventory.rarity import Rarity


class AggressionLevels(Enum):
	PASSIVE = 0			# Never attacks
	VENGEFUL = 1		# Hit & run
	RAMPAGE = 2			# Attacks until defeated or left alone


class Directions(IntFlag):
	EAST = 0x1
	NORTH = 0x2
	WEST = 0x3
	SOUTH = 0x4
	NORTHEAST = NORTH | EAST
	NORTHWEST = NORTH | WEST
	SOUTHEAST = SOUTH | EAST
	SOUTHWEST = SOUTH | WEST


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


class Rarities(Enum):
	Junk = Rarity.junk()
	Common = Rarity.common()
	Uncommon = Rarity.uncommon()
	Rare = Rarity.rare()
	Legendary = Rarity.legendary()
	Unique = Rarity.unique()

	@classmethod
	def from_scale(cls, value: int, minimum: int = 1, maximum: int = 100) -> Rarity:
		lb = min(minimum, maximum)
		ub = max(minimum, maximum)
		v = lb if value < lb else ub if value > ub else value
		v_normalized = (v - lb)/(ub - lb)
		if v_normalized < 0 or v_normalized > 1:
			raise Exception("The value does not fall within the provided range.")

		rarity = Rarities.Junk.value
		for x in list(Rarities):
			if v_normalized <= x.value.frequency:
				rarity = x.value
		return rarity

	@classmethod
	def from_name(cls, name: str):
		for x in list(Rarities):
			if x.value.name.lower() == name.lower():
				return x.value
		return None


class Seasons(Enum):
	BRIGHTBLOOM = 0
	SOLSTIME = 1
	LEAFGLOW = 2
	FROSTFALL = 3


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

