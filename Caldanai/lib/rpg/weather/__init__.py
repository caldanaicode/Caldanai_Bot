import importlib
from random import choice
from typing import List

from Caldanai.Logger import stdout


class Weather:
	def __init__(
			self,
			min_duration: int = 10,
			max_duration: int = 60,
			ambiance: List[str] = (),
			arrival: str = "",
			departure: str = ""
	):
		self.min_duration: int = max(1, max(min_duration, max_duration))
		self.max_duration: int = max(1, min(max_duration, min_duration))
		self.ambiance: List[str] = ambiance
		self.arrival: str = arrival
		self.departure: str = departure

		if self.min_duration > self.max_duration:
			tmp = self.min_duration
			self.min_duration = max_duration
			self.max_duration = tmp

	def get_ambiance(self):
		return choice(self.ambiance)

	@classmethod
	def from_plugin(cls, plugin_name: str):
		"""Creates a new weather pattern from a plugin."""

		try:
			weather = importlib.import_module(f'Caldanai.lib.rpg.inventory.armor.{plugin_name}').WeatherPlugin()
			return weather

		except:
			stdout(f"Unable to load WeatherPlugin: {plugin_name}")
			return None
