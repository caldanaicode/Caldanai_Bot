from random import randint
from typing import Tuple, Optional, Union

from Caldanai.Logger import stdout


class Dice:
	def __init__(self, count: int, sides: int):
		"""
		Create a new instance of a Dice object, and initializes the rolls and value as if the dice were rolled.

		:param count: The number of dice to use.
		:param sides: The number of sides for each die.
		"""
		self.count = count
		self.sides = sides
		self.value: int = 0
		self.rolls: Tuple[int] = self.roll()

	def __str__(self) -> str:
		s = f"{self.count}d{self.sides}"
		if len(self.rolls) > 0:
			s += f" ({', '.join(str(d) for d in self.rolls)})"
		if self.value:
			s += f" = {self.value}"
		return s

	def __repr__(self):
		return f"Dice <count={self.count}, sides={self.sides}, value={self.value}, " \
				f"rolls=[ {', '.join(map(str, self.rolls))} ]>"

	def roll(self) -> Tuple[int]:
		"""
		Rolls the dice in this instance and sets the value as the sum. Individual rolls are stored in the rolls
		variable.

		:return: A tuple containing the individual rolls.
		"""
		result: Tuple[int] = tuple(randint(1, self.sides) for _ in range(self.count))
		self.rolls = result
		self.value = sum(result)
		return result

	@staticmethod
	def quick_roll(ndn: str, keep: Optional[int] = None) -> int:
		"""
		Generates a random number between the number of dice, and the number of dice times the number of sides.
		Ignores intermediate rolls and returns only the result.

		:param ndn: The number of dice and the sides per dice, such as "1d6" or "2d10"
		:param keep: [Optional] The number of dice to keep. For instance, if ndn is "4d6" and keep is 3, then the 3
		highest rolls are kept.
		:return: The integer sum of the generated numbers.
		"""
		dice: Dice = Dice.from_ndn(ndn)
		if keep is not None and dice is not None and keep < dice.count:
			rolls = list(dice.rolls)
			rolls.sort()
			return sum(rolls[-keep:])
		return dice.value if dice else None

	def get_ndn(self):
		return f"{self.count}d{self.sides}"

	@classmethod
	def from_ndn(cls, ndn: str) -> Union["Dice", None]:
		"""
		Creates a new ndn instance of dice from a string.

		:param ndn: The number of dice and the sides per dice, such as "1d6" or "2d10"
		:return: The Dice instance created.
		"""
		try:
			count, sides = map(int, ndn.lower().split('d'))
		except Exception as e:
			stdout(e)
			return None

		if count < 1 or sides < 2:
			return None

		return cls(count, sides)

	@classmethod
	def d4(cls, count: int = 1) -> "Dice":
		"""
		Creates a new nd4 instance of Dice.

		:param count: An optional number of d4 to simulate. Defaults to 1.
		:return: The Dice instance created.
		"""
		return cls(1 if count is None or count < 0 else count, 4)

	@classmethod
	def d6(cls, count: Optional[int] = None) -> "Dice":
		"""
		Creates a new nd6 instance of Dice.

		:param count: An optional number of d6 to simulate. Defaults to 1.
		:return: The Dice instance created.
		"""
		return cls(1 if count is None or count < 0 else count, 6)

	@classmethod
	def d8(cls, count: Optional[int] = None) -> "Dice":
		"""
		Creates a new nd8 instance of Dice.

		:param count: An optional number of d8 to simulate. Defaults to 1.
		:return: The Dice instance created.
		"""
		return cls(1 if count is None or count < 0 else count, 8)

	@classmethod
	def d10(cls, count: Optional[int] = None) -> "Dice":
		"""
		Creates a new nd10 instance of Dice.

		:param count: An optional number of d10 to simulate. Defaults to 1.
		:return: The Dice instance created.
		"""
		return cls(1 if count is None or count < 0 else count, 10)

	@classmethod
	def d12(cls, count: Optional[int]) -> "Dice":
		"""
		Creates a new nd12 instance of Dice.

		:param count: An optional number of d12 to simulate. Defaults to 1.
		:return: The Dice instance created.
		"""
		return Dice(1 if count is None or count < 0 else count, 12)

	@classmethod
	def d20(cls, count: Optional[int] = None) -> "Dice":
		"""
		Creates a new nd20 instance of Dice.

		:param count: An optional number of d20 to simulate. Defaults to 1.
		:return: The Dice instance created.
		"""
		return cls(1 if count is None or count < 0 else count, 20)
