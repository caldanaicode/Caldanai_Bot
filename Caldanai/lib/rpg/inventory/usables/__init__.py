import importlib

from Caldanai.Logger import get_logger
from Caldanai.lib.rpg.helpers.enums import Qualities
from Caldanai.lib.rpg.inventory import Item
from bson.objectid import ObjectId


_log = get_logger(__name__)


class Usable(Item):
    def __init__(
        self,
        iid: ObjectId = None,
        name: str = "",
        desc: str = "",
        unit_weight: float = 1.0,
        unit_value: int = 0,
        image: str = None,
        quality: Qualities = None,
        article: str = None,
        plugin: str = None,
        item_type: str = "Usable",
    ):
        super().__init__(iid, name, desc, unit_weight, unit_value, image, quality, article, plugin, item_type)

    def use(self, user) -> str:
        return "There doesn't seem to be a way to do that."

    def to_dict(self) -> dict:
        """Returns the database-friendly dictionary for this item."""

        d = super().to_dict()
        return d

    @classmethod
    def from_plugin(cls, plugin_name: str, data: dict):
        """Creates a new item from a plugin with initial data."""

        try:
            item = importlib.import_module(f"Caldanai.lib.rpg.inventory.usables.{plugin_name}").UsablePlugin(
                data["_id"] if "_id" in data.keys() else None,
                (
                    Qualities[data["quality"]]
                    if "quality" in data.keys() and data["quality"] in Qualities.__members__
                    else None
                ),
            )

            return item

        except Exception as e:
            _log.error(f"Unable to load UsablePlugin: {data}\n\tReason: {e}")
            return None
