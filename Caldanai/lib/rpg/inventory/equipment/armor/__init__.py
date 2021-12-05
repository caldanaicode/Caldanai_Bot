import importlib
from typing import Dict

from bson import ObjectId
from discord import Embed, File

from Caldanai.Logger import stdout
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment import Equipment


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
			bonuses: Dict[str, int] = None
	):
		super().__init__(
			iid, name, desc, unit_weight, unit_value, image, quality, article, 'Armor', slots, plugin
		)

		self.bonuses: Dict[str, int] = {}
		for stat, bonus in bonuses.items():
			self.bonuses[stat] = int(bonus * self.quality.value['multiplier'])

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
				Qualities[data['quality']] if 'quality' in data.keys() and data['quality'] in Qualities.__members__
				else None
			)

			return item

		except Exception as e:
			stdout(f"Unable to load ArmorPlugin: {data}\n\tReason: {e}")
			return None
