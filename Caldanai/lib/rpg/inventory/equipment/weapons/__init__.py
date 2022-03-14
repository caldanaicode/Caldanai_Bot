import importlib
from typing import Dict, Tuple

from Caldanai.Logger import stdout
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment import Equipment
from bson.objectid import ObjectId


class Weapon(Equipment):
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
			slots: EquipmentSlots = EquipmentSlots.EITHER_HELD,
			plugin: str = None,
			atk: str = "1d4",
			atk_msg: str = None,
			bonus: int = None,
			dmg_type: DamageTypes = None
	):
		super().__init__(
			iid, name, desc, unit_weight, unit_value, image, quality, article, "Weapon", slots, plugin
		)
		self.attacks: Dict[str, Tuple[DamageTypes, str, str, float]] = {}
		self.attack = atk.lower()
		self.damage_type = dmg_type
		self.attack_msg = atk_msg
		self.skill: str = f"{'two-handed ' if slots & EquipmentSlots.MULTI_SLOT else 'one-handed '}" \
			f"{str(self.damage_type) or ''}".strip()

		dice = int(self.attack.split('d')[0])
		self.bonus = bonus or int(dice * self.quality.value['multiplier'])

	def get_embed(self) -> tuple:
		embed, file = super().get_embed()

		fields = (
			("Skill", self.skill.title(), False),
			("Is Two-Handed", bool(self.slots & EquipmentSlots.MULTI_SLOT), True),
			("\u200b", "\u200b", True),
			("Damage Type", str(self.damage_type), True),
			("Attack", f"{self.attack} + {self.bonus}", True)
		)
		for f, v, i in fields:
			embed.insert_field_at(0, name=f, value=v, inline=i)

		return embed, file

	@classmethod
	def from_plugin(cls, plugin_name: str, data: dict):
		"""Creates a new weapon from a plugin with initial data."""

		try:
			item = importlib.import_module(f'Caldanai.lib.rpg.inventory.equipment.weapons.{plugin_name}').WeaponPlugin(
				data['_id'] if '_id' in data.keys() else None,
				Qualities[data['quality']] if 'quality' in data.keys() and data['quality'] in Qualities.__members__
				else None,
				data['bonus'] if 'bonus' in data.keys() else None
			)

			return item

		except Exception as e:
			stdout(f"Unable to load WeaponPlugin: {data}\n\tReason: {e}")
			return None
