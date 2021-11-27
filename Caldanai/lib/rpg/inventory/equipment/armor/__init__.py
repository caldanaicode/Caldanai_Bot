import importlib
from typing import Dict

from bson import ObjectId
from discord import Embed, File

from Caldanai.Logger import stdout
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.rarity import Rarity, Rarities


class Armor(Equipment):
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
			slots: EquipmentSlots = EquipmentSlots.NONE,
			plugin: str = None,
			bonuses: Dict[str, int] = None
	):
		super().__init__(iid, name, desc, unit_weight, unit_value, image, rarity, article, 'Armor', slots, plugin)

		self.bonuses = {}
		for stat, bonus in bonuses.items():
			self.bonuses[stat] = (round(bonus * self.rarity.multiplier) if self.rarity.name != 'junk' else 0)

	def get_embed(self) -> (Embed, File):
		embed, file = super().get_embed()
		for k, v in self.bonuses.items():
			embed.insert_field_at(0, name=k, value=v, inline=True)
		return embed, file

	@classmethod
	def from_plugin(cls, plugin_name: str, data: dict):
		"""Creates a new armor from a plugin with initial data."""

		try:
			item = importlib.import_module(f'Caldanai.lib.rpg.inventory.equipment.armor.{plugin_name}').ArmorPlugin(
				data['_id'] if '_id' in data.keys() else None,
				Rarities.from_name(data['rarity']) if 'rarity' in data.keys() else None
			)

			return item

		except:
			stdout(f"Unable to load ArmorPlugin: {data}")
			return None
