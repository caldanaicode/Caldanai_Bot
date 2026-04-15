"""Attack sources — anything that can produce an attack roll.

A weapon is an attack source. A fist is an attack source. A hydra head is an
attack source. Creatures expose a list of attack sources via
`get_attack_sources()`, and the combat system iterates them to resolve each
individual attack independently.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional, Tuple

from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach
from caldanai.lib.rpg.helpers.roll_data import AttackRoll, DamageRoll

if TYPE_CHECKING:
    from caldanai.lib.rpg.creatures import Creature
    from caldanai.lib.rpg.inventory.equipment.weapons import Weapon


class AttackSource(ABC):
    """Abstract base class for anything that can produce an attack."""

    def __init__(self, label: str = "", *, reach: Reach = Reach.MELEE):
        self._label = label
        self.reach = reach

    @property
    def label(self) -> str:
        """A display label for this attack source (e.g., 'Left', 'Right', 'Two-Handed', 'Head 1')."""
        return self._label

    @property
    @abstractmethod
    def damage_type(self) -> Optional[DamageTypes]:
        """The damage type this attack source deals."""
        ...

    @property
    @abstractmethod
    def skill(self) -> str:
        """The skill name used for XP gain and bonus calculation."""
        ...

    @abstractmethod
    def make_attack_rolls(self, attacker: "Creature") -> Tuple[AttackRoll, DamageRoll]:
        """Create the attack and damage rolls for this source, given the attacker."""
        ...


class WeaponAttackSource(AttackSource):
    """An attack source backed by an equipped Weapon."""

    def __init__(self, weapon: "Weapon", label: str = "", *, reach: Reach = Reach.MELEE):
        super().__init__(label=label, reach=reach)
        self.weapon = weapon

    @property
    def damage_type(self) -> Optional[DamageTypes]:
        return self.weapon.damage_type

    @property
    def skill(self) -> str:
        return self.weapon.skill

    def make_attack_rolls(self, attacker: "Creature") -> Tuple[AttackRoll, DamageRoll]:
        atk_bonus, dmg_bonus = _get_skill_bonus(attacker, self.skill)
        atk = AttackRoll(skill_bonus=atk_bonus)
        dmg = DamageRoll(
            dice=Dice.from_ndn(self.weapon.attack),
            weapon_bonus=self.weapon.bonus,
            skill_bonus=dmg_bonus,
        )
        return atk, dmg


class UnarmedAttackSource(AttackSource):
    """An attack source for unarmed strikes (fists). Rolls 1d4 bludgeoning."""

    def __init__(self, label: str = "", *, reach: Reach = Reach.MELEE):
        super().__init__(label=label, reach=reach)

    @property
    def damage_type(self) -> Optional[DamageTypes]:
        return DamageTypes.BLUDGEONING

    @property
    def skill(self) -> str:
        return "unarmed"

    def make_attack_rolls(self, attacker: "Creature") -> Tuple[AttackRoll, DamageRoll]:
        atk_bonus, dmg_bonus = _get_skill_bonus(attacker, self.skill)
        atk = AttackRoll(skill_bonus=atk_bonus)
        dmg = DamageRoll(
            dice=Dice.d4(),
            weapon_bonus=0,
            skill_bonus=dmg_bonus,
        )
        return atk, dmg


class NaturalAttackSource(AttackSource):
    """An attack source for natural attacks (claws, teeth, breath, etc.).

    This is the default for monsters that don't wield weapons — the monster's
    hardcoded `atk` dice string drives the damage roll.
    """

    def __init__(
        self,
        atk: str,
        dmg_type: Optional[DamageTypes] = None,
        label: str = "",
        skill: str = "natural",
        *,
        reach: Reach = Reach.MELEE,
        drain_ratio: float = 0.0,
    ):
        super().__init__(label=label, reach=reach)
        self._atk = atk
        self._dmg_type = dmg_type
        self._skill = skill
        self._drain_ratio = drain_ratio

    @property
    def damage_type(self) -> Optional[DamageTypes]:
        return self._dmg_type

    @property
    def skill(self) -> str:
        return self._skill

    @property
    def drain_ratio(self) -> float:
        """Fraction of damage dealt that heals the attacker. ``0.0``
        for ordinary attacks; non-zero for life-drain attacks
        (spirit ethereal touch, future vampire bites, etc.). Read by
        ``Creature._on_attack_resolved`` to apply the heal."""
        return self._drain_ratio

    def make_attack_rolls(self, attacker: "Creature") -> Tuple[AttackRoll, DamageRoll]:
        atk_bonus, dmg_bonus = _get_skill_bonus(attacker, self.skill)
        atk = AttackRoll(skill_bonus=atk_bonus)
        dmg = DamageRoll(
            dice=Dice.from_ndn(self._atk),
            weapon_bonus=0,
            skill_bonus=dmg_bonus,
        )
        return atk, dmg


def _get_skill_bonus(attacker: "Creature", skill: str) -> Tuple[int, int]:
    """Returns (attack_bonus, damage_bonus) for a creature's skill.

    Players have skill-based bonuses; most creatures don't, in which case
    this returns (0, 0).
    """
    getter = getattr(attacker, "get_skill_bonus", None)
    if callable(getter):
        return getter(skill)
    return 0, 0
