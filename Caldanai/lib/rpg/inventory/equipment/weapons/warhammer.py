from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="warhammer",
			desc="An old favorite of many.",
			unit_weight=2,
			unit_value=5,
			image="warhammer128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="warhammer",
			atk="1d10",
			is_magic=False,
			is_ranged=False,
			atk_msg="bonks",
			bonus=bonus,
			dmg_type="bludgeoning"
		)
