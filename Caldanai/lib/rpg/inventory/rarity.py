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
