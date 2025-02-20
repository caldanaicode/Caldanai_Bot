from typing import Tuple
from bson import ObjectId
from discord import Embed, File

from Caldanai.lib.rpg.inventory import Item
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities


class Equipment(Item):
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
        item_type: str = "Equipment",
        slots: EquipmentSlots = None,
        plugin: str = None,
    ):
        super().__init__(
            iid, name, desc, unit_weight, unit_value, image, quality, article, item_type=item_type, plugin=plugin
        )
        self.slots: EquipmentSlots = slots

    def get_embed(self) -> Tuple[Embed, File]:
        embed, file = super().get_embed()
        slots = []
        for slot in EquipmentSlots:
            if slot and slot in self.slots and not EquipmentSlots.exclude_from_output(slot.name):
                slots.append(slot.name)

        embed.insert_field_at(0, name="Slots", value=" | ".join(slots), inline=True)
        return embed, file
