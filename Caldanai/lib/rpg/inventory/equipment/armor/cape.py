from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.equipment.armor import Armor
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ArmorPlugin(Armor):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None):
		super().__init__(
			iid=iid,
			name="cape",
			desc="This cape is short, yet stylish. Wearing this may impart minor delusions of grandeur.",
			unit_weight=1.0,
			unit_value=1,
			image=None,
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.CAPE,
			bonuses={
				"dodge": 1,
			}
		)
