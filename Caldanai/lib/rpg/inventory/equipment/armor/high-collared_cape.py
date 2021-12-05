from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.armor import Armor


class ArmorPlugin(Armor):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None):
		super().__init__(
			iid=iid,
			name="high-collared cape",
			desc="With ragged edges and a few holes, this cape has seen better days.",
			unit_weight=1.0,
			unit_value=1,
			image=None,
			quality=quality,
			article="a",
			slots=EquipmentSlots(EquipmentSlots.MULTI_SLOT | EquipmentSlots.NECK | EquipmentSlots.CAPE),
			bonuses={
				"dodge": -1,
				"defense": -1,
				"health_max": 5
			}
		)
