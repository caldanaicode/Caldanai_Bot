import importlib

from discord import Embed, File

from Caldanai.Logger import stdout
from Caldanai.db.__init__ import MongoDB
from Caldanai.lib.rpg.inventory.items import Item
from Caldanai.lib.rpg.inventory.rarity import Rarity, Rarities
from bson.objectid import ObjectId


class Weapon(Item):
	def __init__(
			self,
			iid: ObjectId = None,
			name: str = "",
			desc: str = "",
			unit_weight: float = 1.0,
			unit_value: int = 0,
			image: str = None,
			rarity: Rarity = None,
			atk: str = "1d4",
			is_2handed: bool = False,
			is_magic: bool = False,
			is_ranged: bool = False,
			atk_msg: str = None,
			bonus: int = None,
			article: str = None,
			dmg_type: str = None,
			plugin: str = None
	):
		super().__init__(iid, name, desc, unit_weight, unit_value, image, rarity, article, item_type="Weapon",
						 plugin=plugin)
		self.attack = atk.lower()
		self.is_2handed = is_2handed
		self.is_magic = is_magic
		self.is_ranged = is_ranged
		self.damage_type = dmg_type
		self.attack_msg = atk_msg
		self.skill: str = f"{'two-handed ' if is_2handed else 'one-handed '}{'magic ' if is_magic else ''}" \
			f"{'ranged ' if is_ranged else ''}{dmg_type}"

		dice = int(self.attack.split('d')[0])
		self.bonus = bonus or (round(dice * self.rarity.multiplier) if self.rarity.name != 'junk' else 0)

	def get_embed(self) -> tuple:
		embed, file = super().get_embed()

		fields = (
			("Skill", self.skill.title(), False),
			("Is Ranged", self.is_ranged, True),
			("Is Magic", self.is_magic, True),
			("Is Two-Handed", self.is_2handed, True),
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
			item = importlib.import_module(f'Caldanai.lib.rpg.inventory.weapons.{plugin_name}').WeaponPlugin(
				data['_id'] if '_id' in data.keys() else None,
				Rarities.from_name(data['rarity']) if 'rarity' in data.keys() else None,
				data['bonus'] if 'bonus' in data.keys() else None
			)

			return item

		except:
			stdout(f"Unable to load WeaponPlugin: {data}")
			return None
