from bson import ObjectId
from discord import Embed, File

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.stackables import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity


class Equipment(Item):
	def __init__(
			self,
			iid: ObjectId = None,
			name: str = "",
			desc: str = "",
			unit_weight: float = 1.0,
			unit_value: int = 0,
			image: str = None,
			rarity: Rarity = None,
			article: str = None,
			item_type: str = 'Equipment',
			slots: EquipmentSlots = 0,
			plugin: str = None
	):
		super().__init__(
			iid, name, desc, unit_weight, unit_value, image, rarity, article, item_type=item_type, plugin=plugin
		)
		self.slots: EquipmentSlots = slots

	def get_embed(self) -> (Embed, File):
		embed, file = super().get_embed()
		slots = []
		for slot in EquipmentSlots:
			if slot & self.slots:
				slots.append(slot.name.replace('_', ' ').title())

		embed.insert_field_at(0, name="Slots", value=' | '.join(slots), inline=True)
		return embed, file
