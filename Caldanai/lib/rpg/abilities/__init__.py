from abc import ABC
from typing import Union, Tuple

from Caldanai.lib.rpg.helpers.dice import Dice


class Ability(ABC):
    def __init__(
        self,
        default,
    ):
        self.__default = default
        self.__value = None


class IntAbility(Ability):
    """
    Defines an ability designed to hold an integer value.
    """

    def __init__(self, default: int, value: int = 0, minimum: Union[str, int] = None, maximum: Union[str, int] = None):
        super().__init__(default)
        self.__value = value
        self.__minimum = minimum
        self.__maximum = maximum

    def __str__(self):
        return str(self.__value)

    def __repr__(self):
        return (
            f"IntAbility <value={self.__value}, min={self.__minimum}, max={self.__maximum}, default="
            f"{self.__default}>"
        )


class DiceAbility(Ability):
    """
    Defines an ability designed to hold an a dice value that can be re-rolled on demand.
    """

    def __init__(self, default: int, ndn: str, bonus: int = 0):
        super().__init__(default)
        self.__dice = Dice.from_ndn(ndn)
        self.__bonus = int(bonus)

    def roll(self) -> int:
        self.__dice.roll()
        return self.__dice.value + self.__bonus

    def get_rolls(self) -> Tuple[int]:
        return self.__dice.rolls

    def __str__(self):
        return (
            f"{self.__dice.get_ndn()}"
            f"{' +' if self.__bonus > 0 else ' -' if self.__bonus < 0 else ''}"
            f"{self.__bonus if self.__bonus != 0 else ''}"
        )

    def __repr__(self):
        return f"DiceAbility <bonus={self.__bonus}, dice={repr(self.__dice)}>"
