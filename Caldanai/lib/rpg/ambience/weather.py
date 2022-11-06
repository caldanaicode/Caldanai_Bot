class Weather:
	def __init__(
			self,
			min_duration: int = 60,			# Minimum duration in game-minutes.
			max_duration: int = 2880,		# Maximum duration in game-minutes.
	):
		self.min_duration = min_duration
		self.max_duration = max_duration

