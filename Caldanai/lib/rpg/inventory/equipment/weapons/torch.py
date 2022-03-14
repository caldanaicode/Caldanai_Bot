from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="torch",
			desc="This handy stick lets you feel less scared in the dark.",
			unit_weight=0.3,
			unit_value=1,
			image=None,
			quality=quality,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="torch",
			atk="1d6",
			atk_msg="pokes",
			bonus=bonus,
			dmg_type=DamageTypes.BLUDGEONING | DamageTypes.FIRE | DamageTypes.COMBINED
		)
