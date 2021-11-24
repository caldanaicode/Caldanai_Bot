import importlib

from Caldanai.Logger import stdout
from Caldanai.lib.rpg.helpers.enums import Directions


class Area:
	def __init__(self):
		self.name = ""
		self.brief = ""
		self.verbose = ""
		self.directions = {}

	def get_look_direction(self, direction: Directions):
		if direction in self.directions.keys():
			return self.directions[direction]

		return "There is nothing of note in that direction"

	@classmethod
	def from_plugin(cls, plugin_name: str):
		"""Creates a new area from a plugin."""

		try:
			room = importlib.import_module(f'Caldanai.lib.rpg.areas.{plugin_name}').AreaPlugin()
			return room

		except:
			stdout(f"Unable to load AreaPlugin: {plugin_name}")
			raise
