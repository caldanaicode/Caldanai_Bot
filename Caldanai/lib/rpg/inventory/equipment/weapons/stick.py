from bson import ObjectId

from Caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities
from Caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class WeaponPlugin(Weapon):
	def __init__(self, iid: ObjectId = None, quality: Qualities = None, bonus: int = None):
		super().__init__(
			iid=iid,
			name="stick",
			desc="It's brown. It's sticky. It's a simple stick, probably from some nearby tree. It's only slightly "
				"better than being bare-handed.",
			unit_weight=0.3,
			unit_value=0,
			image="stick128.png",
			quality=quality,
			article="a",
			slots=EquipmentSlots.EITHER_HELD,
			plugin="stick",
			atk="1d4",
			is_magic=False,
			is_ranged=False,
			atk_msg="pokes",
			bonus=bonus,
			dmg_type="piercing"
		)
