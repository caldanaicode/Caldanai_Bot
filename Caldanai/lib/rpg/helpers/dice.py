from random import randint, choice

from Caldanai.Logger import stdout


class Dice:
	@staticmethod
	def quick_roll(ndn: str) -> int:
		count = sides = 0
		try:
			count, sides = map(int, ndn.lower().split('d'))
		except Exception as e:
			stdout(e)

		result = 0
		for _ in range(count):
			result += randint(1, sides)
		return result

	@staticmethod
	def coin_toss() -> str:
		return choice(["heads", "tails"])

	@staticmethod
	def d4() -> int:
		return randint(1, 4)

	@staticmethod
	def d6() -> int:
		return randint(1, 6)

	@staticmethod
	def d8() -> int:
		return randint(1, 8)

	@staticmethod
	def d10() -> int:
		return randint(1, 10)

	@staticmethod
	def d12() -> int:
		return randint(1, 12)

	@staticmethod
	def d20() -> int:
		return randint(1, 20)
