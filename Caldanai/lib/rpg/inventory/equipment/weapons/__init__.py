import importlib

from Caldanai.Logger import stdout
from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.equipment import Equipment
from Caldanai.lib.rpg.inventory.rarity import Rarity, Rarities
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
			rarity: Rarity = None,
			article: str = None,
			slots: EquipmentSlots = EquipmentSlots.EITHER_HELD,
			plugin: str = None,
			atk: str = "1d4",
			is_magic: bool = False,
			is_ranged: bool = False,
			atk_msg: str = None,
			bonus: int = None,
			dmg_type: str = None,
	):
		super().__init__(
			iid, name, desc, unit_weight, unit_value, image, rarity, article, "Weapon", slots, plugin
		)
		self.attack = atk.lower()
		self.is_magic = is_magic
		self.is_ranged = is_ranged
		self.damage_type = dmg_type
		self.attack_msg = atk_msg
		self.skill: str = f"{'two-handed ' if slots & EquipmentSlots.MULTI_SLOT else 'one-handed '}" \
			f"{'magic ' if is_magic else ''}{'ranged ' if is_ranged else ''}{dmg_type}"

		dice = int(self.attack.split('d')[0])
		self.bonus = bonus or (round(dice * self.rarity.multiplier) if self.rarity.name != 'junk' else 0)

	def get_embed(self) -> tuple:
		embed, file = super().get_embed()

		fields = (
			("Skill", self.skill.title(), False),
			("Is Ranged", self.is_ranged, True),
			("Is Magic", self.is_magic, True),
			("Is Two-Handed", bool(self.slots & EquipmentSlots.MULTI_SLOT), True),
			("\u200b", "\u200b", True),
			("Damage Type", self.damage_type, True),
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
				Rarities.from_name(data['rarity']) if 'rarity' in data.keys() else None,
				data['bonus'] if 'bonus' in data.keys() else None
			)

			return item

		except:
			stdout(f"Unable to load WeaponPlugin: {data}")
			return None
