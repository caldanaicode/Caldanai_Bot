from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="spear",
			desc="Stick them with the pointy end!",
			unit_weight=3.5,
			unit_value=15,
			image="spear128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.TWO_HANDED,
			plugin="spear",
			atk="2d10",
			is_magic=False,
			is_ranged=False,
			atk_msg="thrusts",
			bonus=bonus,
			dmg_type="piercing"
		)
