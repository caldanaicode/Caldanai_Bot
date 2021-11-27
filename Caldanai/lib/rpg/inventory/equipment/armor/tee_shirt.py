from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots
from Caldanai.lib.rpg.inventory.equipment.armor import Armor
from Caldanai.lib.rpg.inventory.rarity import Rarity


class ArmorPlugin(Armor):
	def __init__(self, iid: ObjectId = None, rarity: Rarity = None):
		super().__init__(
			iid=iid,
			name="tee-shirt",
			desc="I killed a dragon and all I got was this lousy shirt. (Lice not included.)",
			unit_weight=0.6,
			unit_value=4,
			image="tee-shirt128.png",
			rarity=rarity,
			article="a",
			slots=EquipmentSlots.TORSO,
			bonuses={
				"dodge": 1,
				"health_max": 1,
				"defense": 1
			},
			plugin='tee_shirt'
		)
