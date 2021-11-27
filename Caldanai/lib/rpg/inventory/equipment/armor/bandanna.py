from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.equipment.armor import Armor
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ArmorPlugin(Armor):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None):
		super().__init__(
			iid=iid,
			name="bandanna",
			desc="A multifunctional piece of patterned cloth.",
			unit_weight=0.2,
			unit_value=1,
			image="bandanna128.png",
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.FACE,
			bonuses={
				"dodge": 2,
				"health_max": -1
			}
		)
