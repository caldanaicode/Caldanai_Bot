import importlib
from typing import Dict

from bson import ObjectId
from discord import Embed, File

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from caldanai.lib.rpg.inventory.equipment import Equipment


_log = get_logger(__name__)


class Armor(Equipment):
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
        slots: EquipmentSlots = None,
        plugin: str = None,
        bonuses: Dict[str, int] = None,
    ):
        super().__init__(iid, name, desc, unit_weight, unit_value, image, quality, article, "Armor", slots, plugin)

        self.bonuses: Dict[str, int] = {}
        for stat, bonus in (bonuses or {}).items():
            self.bonuses[stat] = int(bonus * self.quality.value["multiplier"])

    def get_embed(self) -> tuple[Embed, File]:
        embed, file = super().get_embed()
        for k, v in self.bonuses.items():
            embed.insert_field_at(0, name=k, value=v, inline=True)
        return embed, file

    @classmethod
    def from_plugin(cls, plugin_name: str, data: dict):
        """Creates a new armor from a plugin with initial data.

        Resolves the plugin file by stem: flat
        ``...armor.patchwork_bracer`` first (legacy unsorted layout),
        then a recursive search through ``armor/<set>/<stem>.py``
        subdirectories so set-organized pieces register without
        needing to thread the subdir name through call sites.
        Plugin stems must remain globally unique across the armor
        tree — duplicates would silently shadow each other under
        the flat ``Inventory.ITEMS`` registry anyway."""

        iid = data["_id"] if "_id" in data.keys() else None
        quality = (
            Qualities[data["quality"]]
            if "quality" in data.keys() and data["quality"] in Qualities.__members__
            else None
        )

        # Try the legacy flat path first — fast path for the
        # pre-set-reorg pieces (cape, tee_shirt, mushroom_hat, etc.).
        try:
            mod = importlib.import_module(
                f"caldanai.lib.rpg.inventory.equipment.armor.{plugin_name}"
            )
            return mod.ArmorPlugin(iid, quality)
        except ModuleNotFoundError:
            pass
        except Exception as e:
            _log.error(f"Unable to load ArmorPlugin: {data}\n\tReason: {e}")
            return None

        # Recursive search through set-organized subdirs.
        from glob import glob
        from os import path as _ospath
        armor_root = _ospath.dirname(__file__)
        pattern = _ospath.join(armor_root, "**", f"{plugin_name}.py")
        for filepath in glob(pattern, recursive=True):
            rel = _ospath.relpath(filepath, armor_root)
            # Skip the flat layer (already tried above).
            if _ospath.sep not in rel:
                continue
            module_path = (
                "caldanai.lib.rpg.inventory.equipment.armor."
                + rel[:-3].replace(_ospath.sep, ".")
            )
            try:
                mod = importlib.import_module(module_path)
                return mod.ArmorPlugin(iid, quality)
            except Exception as e:
                _log.error(f"Unable to load ArmorPlugin: {data}\n\tReason: {e}")
                return None

        _log.error(f"Unable to load ArmorPlugin: {data}\n\tReason: stem '{plugin_name}' not found")
        return None
