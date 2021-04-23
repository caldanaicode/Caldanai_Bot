from random import randint


def quick_roll(ndn: str) -> int:
	try:
		count, sides = map(int, ndn.lower().split('d'))
	except Exception as e:
		print(e)
	
	result = 0
	for _ in range(count):
		result += randint(1, sides)
	return result