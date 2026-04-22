from typing import Tuple
from bson import ObjectId
from discord import Embed, File

from caldanai.lib.rpg.creatures.equipment_routing import resolve_placements
from caldanai.lib.rpg.inventory import Item
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities


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
        """Item embed — renders equipment placements in the
        ``part.key`` form players see in ``$gear`` / ``$unequip``
        rather than the legacy ``HEAD`` / ``LEFT_HELD`` enum names
        that pre-date the equipment-on-parts migration.

        Two-handed / multi-slot items expand to every placement
        they occupy (e.g. a two-hander shows ``arm.left.held | arm.right.held``),
        matching how ``$gear`` renders the same item.
        """
        embed, file = super().get_embed()
        placements = resolve_placements(self.slots) if self.slots else []
        labels = [f"{part}.{key}" for (part, key) in placements]
        # Multi-slot items (two-handed weapons, paired gear) occupy
        # every placement simultaneously — ``a + b``. Single-slot
        # items with multiple compatible placements (a one-hander
        # that can go in either arm, a ring that fits either finger)
        # occupy exactly one — ``a | b``. The two read very
        # differently and the old ``| ``-only rendering conflated them.
        if self.slots and self.slots & EquipmentSlots.MULTI_SLOT:
            separator = " + "
        else:
            separator = " | "
        embed.insert_field_at(
            0,
            name="Slots",
            value=separator.join(labels) if labels else "—",
            inline=True,
        )
        return embed, file
