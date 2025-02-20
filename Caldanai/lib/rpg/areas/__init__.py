import importlib

from Caldanai.Logger import get_logger
from Caldanai.lib.rpg.helpers.enums import Directions


_log = get_logger(__name__)


class Area:
    def __init__(self):
        self.name = ""
        self.brief = ""
        self.verbose = ""
        self.directions = {}

    def get_look_direction(self, direction: Directions):
        if direction in self.directions:
            return self.directions[direction]

        filtered = list(filter(lambda d: d & direction, self.directions.keys()))
        if len(filtered):
            return self.directions[filtered[0]]

        return "There is nothing of note in that direction."

    @classmethod
    def from_plugin(cls, plugin_name: str):
        """Creates a new area from a plugin."""

        try:
            room = importlib.import_module(f"Caldanai.lib.rpg.areas.{plugin_name}").AreaPlugin()
            return room

        except Exception as e:
            _log.error(f"Unable to load AreaPlugin: {plugin_name}\n\t{e}")
            raise
