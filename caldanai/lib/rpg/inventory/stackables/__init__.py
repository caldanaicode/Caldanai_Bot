import importlib

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory import Item
from bson.objectid import ObjectId


_log = get_logger(__name__)


class Stackable(Item):
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
        plural: str = None,
        count: int = 1,
        plugin: str = None,
        item_type: str = "Stackable",
    ):
        super().__init__(iid, name, desc, unit_weight, unit_value, image, quality, article, plugin, item_type)
        self.plural = plural
        self.count = count

    def get_weight(self) -> float:
        return self.unit_weight * self.count

    def get_value(self) -> int:
        return self.unit_value * self.count

    def can_stack(self, other: "Stackable"):
        return (
            self.id != other.id
            and self.item_type == other.item_type
            and self.quality == other.quality
            and self.plugin == other.plugin
        )

    def stack(self, other: "Stackable") -> bool:
        if not self.can_stack(other):
            return False

        self.count += other.count
        return True

    def get_article_or_count(self, next_word: str = None, count: int = None) -> str:
        article = self.get_article(next_word)
        count = count or self.count
        if count == 1:
            return article

        return f"{count} {next_word}"

    def get_full_name(self, count: int = None) -> str:
        return (
            f"{self.get_article_or_count(self.quality.name.lower(), count)}"
            f" {self.name if (count == 1 or (count is None and self.count == 1)) else self.plural}"
        )

    def to_dict(self) -> dict:
        """Returns the database-friendly dictionary for this item."""

        d = super().to_dict()

        d["count"] = self.count

        if self.id is None:
            del d["_id"]
        return d

    @classmethod
    def from_plugin(cls, plugin_name: str, data: dict):
        """Creates a new item from a plugin with initial data."""

        try:
            item = importlib.import_module(f"caldanai.lib.rpg.inventory.stackables.{plugin_name}").StackablePlugin(
                data["_id"] if "_id" in data.keys() else None,
                (
                    Qualities[data["quality"]]
                    if "quality" in data.keys() and data["quality"] in Qualities.__members__
                    else None
                ),
                data["count"] if "count" in data.keys() else 1,
            )

            return item

        except Exception as e:
            _log.error(f"Unable to load StackablePlugin: {data}\n\tReason: {e}")
            return None
