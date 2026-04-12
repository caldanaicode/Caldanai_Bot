import importlib
from typing import Tuple

from bson import ObjectId
from discord import Embed, File

from caldanai.logger import get_logger
from ....helpers.enums import Qualities, TrophicLevels
from ...usables import Usable


_log = get_logger(__name__)


class Consumable(Usable):
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
            uses_max: int = 1,
            uses_left: int = 1,
            trophic_levels: TrophicLevels = TrophicLevels.OMNIVORE
    ):
        super().__init__(
            iid, name, desc, unit_weight, unit_value, image, quality, article, plugin, "Consumable"
        )
        self.uses_max = max(uses_max, 0)
        self.uses_left = min(max(uses_left, 0), uses_max)
        self.trophic_levels = trophic_levels

    def get_embed(self) -> Tuple[Embed, File]:
        """Returns a tuple containing an Embed and File object for this item."""

        embed, file = super().get_embed()

        embed.insert_field_at(0, name="Uses Remaining", value=self.uses_left, inline=True)
        return embed, file

    def use(self, user) -> Tuple[str, bool]:
        """
        Uses the consumable item and returns a tuple containing a string intended for display and a boolean value
        indicating whether or not any uses remain.
        """

        self.uses_left -= 1
        return "", self.uses_left > 0

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["uses_max"] = self.uses_max
        d["uses_left"] = self.uses_left
        return d

    @classmethod
    def from_plugin(cls, plugin_name: str, data: dict):
        """Creates a new consumable from a plugin with initial data."""

        try:
            if "uses_max" in data.keys() and "uses_left" in data.keys():
                item = importlib.import_module(
                    f"caldanai.lib.rpg.inventory.usables.consumables.{plugin_name}"
                ).ConsumablePlugin(
                    data["_id"] if "_id" in data.keys() else None,
                    (
                        Qualities[data["quality"]]
                        if "quality" in data.keys() and data["quality"] in Qualities.__members__
                        else None
                    ),
                    data["uses_max"],
                    data["uses_left"],
                )

            else:
                item = importlib.import_module(
                    f"caldanai.lib.rpg.inventory.usables.consumables.{plugin_name}"
                ).ConsumablePlugin(
                    data["_id"] if "_id" in data.keys() else None,
                    (
                        Qualities[data["quality"]]
                        if "quality" in data.keys() and data["quality"] in Qualities.__members__
                        else None
                    ),
                )

            return item

        except Exception as e:
            _log.error(f"Unable to load ConsumablePlugin: {data}\n\tReason: {e}")
            return None
