from Caldanai.lib.rpg.weather import Weather


class WeatherPlugin(Weather):
	def __init__(self):
		super().__init__(
			arrival=f"The sky slowly clears until nothing disturbs its vast expanse.",
		)
