from enum import Enum


class Rarity:
	def __init__(self, name: str, color: int, frequency: float, multiplier: float):
		self.name = name
		self.color = color
		self.frequency = frequency
		self.multiplier = multiplier
	
	def to_dict(self):
		return {
			'name': self.name,
			'color': self.color,
			'frequency': self.frequency,
			'multiplier': self.multiplier
		}

	def __eq__(self, other):
		return isinstance(other, Rarity) and self.name == other.name and self.multiplier == other.multiplier
	
	@classmethod
	def load(cls, rarity: dict):
		return cls(
			name=rarity['name'],
			color=rarity['color'],
			frequency=rarity['frequency'],
			multiplier=rarity['multiplier']
		)
	
	@classmethod
	def junk(cls):
		return cls('junk', 0x777777, 0.60, 0.75)  # Gray

	@classmethod
	def common(cls):
		return cls('common', 0xffffff, 0.50, 1.00)  # White

	@classmethod	
	def uncommon(cls):
		return cls('uncommon', 0x00ff00, 0.25, 1.25)  # Green
	
	@classmethod
	def rare(cls):
		return cls('rare', 0x0000ff, 0.10, 1.50)  # Blue

	@classmethod
	def legendary(cls):
		return cls('legendary', 0x800080, 0.05, 1.75)  # Purple

	@classmethod
	def unique(cls):
		return cls('unique', 0xffd700, 0.01, 2.00)  # Gold


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
		for x in Rarities:
			if v_normalized <= x.value.frequency:
				rarity = x.value
		return rarity

	@classmethod
	def from_name(cls, name: str):
		for x in Rarities:
			if x.name.lower() == name.lower():
				return x.value
		return None