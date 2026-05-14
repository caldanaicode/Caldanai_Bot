import importlib
from typing import Dict, Tuple

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import EquipmentSlots, Qualities, DamageTypes, Reach
from caldanai.lib.rpg.inventory.equipment import Equipment
from bson.objectid import ObjectId


_log = get_logger(__name__)


class Weapon(Equipment):
    # Per-class reach declaration. Bow / wand override to
    # ``Reach.RANGED``; thrown / polearm subclasses may override
    # to ``Reach.THROWN`` / ``Reach.REACH``. The ``reach`` property
    # below reads this; reach is no longer derived from a damage-
    # type bit (the old ``DamageTypes.RANGED`` carrier-bit pattern
    # was removed when reach was lifted to its own axis on
    # ``AttackSource`` and the ``RANGED_TRAITS`` / ``RANGED_NARRATIONS``
    # dispatch overlay landed).
    REACH: Reach = Reach.MELEE

    def __init__(
        self,
        iid: ObjectId = None,
        name: str = "",
        desc: str = "",
        unit_weight: float = 1.0,
        unit_value: int = 0,
        image: str = None,
        quality: Qualities = None,
        article: str = None,
        slots: EquipmentSlots = EquipmentSlots.EITHER_HELD,
        plugin: str = None,
        atk: str = "1d4",
        atk_msg: str = None,
        bonus: int = None,
        dmg_type: DamageTypes = None,
    ):
        super().__init__(iid, name, desc, unit_weight, unit_value, image, quality, article, "Weapon", slots, plugin)
        self.attacks: Dict[str, Tuple[DamageTypes, str, str, float]] = {}
        self.attack = atk.lower()
        self.damage_type = dmg_type
        self.attack_msg = atk_msg
        # Skill key folds the slot prefix + reach word + canonical
        # damage type into one stable string. Reach contributes the
        # "ranged" word for bow / wand (was previously baked into
        # the damage type via the ``DamageTypes.RANGED`` carrier-bit
        # which is gone now). Real elemental compounds (torch:
        # ``BLUDGEONING | FIRE | COMBINED``) still surface "combined"
        # via :attr:`DamageTypes.canonical`; player-facing display
        # strips that marker via ``DamageTypes.display_skill_name``.
        slot_word = "two-handed " if slots & EquipmentSlots.MULTI_SLOT else "one-handed "
        reach_word = "ranged " if self.reach == Reach.RANGED else ""
        type_word = self.damage_type.canonical if self.damage_type else ""
        self.skill: str = f"{slot_word}{reach_word}{type_word}".strip()

        dice = Dice.__int__(self.attack.split("d")[0])
        self.bonus = bonus or int(dice * self.quality.value["multiplier"])

    @property
    def reach(self) -> Reach:
        """The attack reach classification — declared per weapon class
        via :attr:`REACH`. Defaults to ``Reach.MELEE`` on the base
        Weapon; bow / wand override to ``Reach.RANGED``; future
        thrown / polearm classes can override to ``Reach.THROWN`` /
        ``Reach.REACH``.

        Consumed by ``Player.get_attack_sources`` when building a
        ``WeaponAttackSource`` so ``effective_dodge_for_part`` honors
        the correct body-part exposure at the reach (wings expose at
        1.0 to ranged but 0.5 to melee), and consumed by
        ``Creature.get_trait_multiplier`` / ``get_hit_narration`` to
        consult the per-creature ``ranged_traits`` /
        ``RANGED_NARRATIONS`` overlay.
        """
        return self.REACH

    def get_embed(self) -> tuple:
        embed, file = super().get_embed()

        fields = (
            # Strip the technical "combined" marker before the player
            # sees the skill name in the weapon embed.
            ("Skill", DamageTypes.display_skill_name(self.skill).title(), False),
            ("Is Two-Handed", bool(self.slots & EquipmentSlots.MULTI_SLOT), True),
            ("\u200b", "\u200b", True),
            ("Damage Type", str(self.damage_type), True),
            ("Attack", f"{self.attack} + {self.bonus}", True),
        )
        for f, v, i in fields:
            embed.insert_field_at(0, name=f, value=v, inline=i)

        return embed, file

    @classmethod
    def from_plugin(cls, plugin_name: str, data: dict):
        """Creates a new weapon from a plugin with initial data."""

        try:
            item = importlib.import_module(f"caldanai.lib.rpg.inventory.equipment.weapons.{plugin_name}").WeaponPlugin(
                data["_id"] if "_id" in data.keys() else None,
                (
                    Qualities[data["quality"]]
                    if "quality" in data.keys() and data["quality"] in Qualities.__members__
                    else None
                ),
                data["bonus"] if "bonus" in data.keys() else None,
            )

            return item

        except Exception as e:
            _log.error(f"Unable to load WeaponPlugin: {data}\n\tReason: {e}")
            return None
