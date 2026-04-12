import importlib

from caldanai.logger import get_logger


_log = get_logger(__name__)


class Ambience:
    def __init__(
        self,
        min_duration: int = 10,
        max_duration: int = 60,
        frequency: int = 300,
        arrival_msg: str = "",
        departure_msg: str = "",
        sunrise_msg: str = "",
        sunset_msg: str = "",
    ):
        self.min_duration: int = max(1, max(min_duration, max_duration))
        self.max_duration: int = max(1, min(max_duration, min_duration))
        self.frequency: int = max(1, frequency)

        if self.min_duration > self.max_duration:
            tmp = self.min_duration
            self.min_duration = max_duration
            self.max_duration = tmp

    def get_ambience(self) -> str:
        return ""

    @classmethod
    def from_plugin(cls, plugin_name: str):
        """Creates a new weather pattern from a plugin."""

        try:
            weather = importlib.import_module(f"caldanai.lib.rpg.inventory.armor.{plugin_name}").WeatherPlugin()
            return weather

        except:
            _log.error(f"Unable to load WeatherPlugin: {plugin_name}")
            return None
