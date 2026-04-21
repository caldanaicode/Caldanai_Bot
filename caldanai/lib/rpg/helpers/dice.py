import re
from random import randint
from typing import Tuple, Optional, Union

from caldanai.logger import get_logger


_log = get_logger(__name__)


# Parses ``NdM`` with an optional signed constant: ``"2d6"``,
# ``"4d4+6"``, ``"3d10 - 2"``. Whitespace around the sign is
# optional. ``N`` (die count) is optional and defaults to 1 so
# ``"d20"`` still works the way the legacy parser treated it.
_NDN_WITH_MOD_RE = re.compile(
    r"""
    ^\s*
    (?P<count>\d*)              # optional die count
    d
    (?P<sides>\d+)              # sides
    \s*
    (?:                         # optional signed constant
        (?P<sign>[+\-])\s*
        (?P<mod>\d+)
    )?
    \s*$
    """,
    re.IGNORECASE | re.VERBOSE,
)


class Dice:
    def __init__(self, count: int, sides: int, modifier: int = 0):
        """
        Create a new instance of a Dice object, and initializes the rolls and value as if the dice were rolled.

        :param count: The number of dice to use.
        :param sides: The number of sides for each die.
        :param modifier: Optional signed constant added to (or subtracted
            from) the sum of the die rolls — the ``+6`` in ``"4d4+6"``.
            Baked into :attr:`value` so downstream consumers don't need
            to track the constant separately; rendered as a distinct
            term in :meth:`__str__` so the breakdown still reads as
            ``(r1 + r2) + C`` rather than a pre-summed total.
        """
        self.count = count
        self.sides = sides
        self.modifier = modifier
        self.value: int = 0
        self.rolls: Tuple[int] = self.roll()

    def __str__(self) -> str:
        base = self.get_ndn()
        if not self.rolls:
            return base
        roll_part = ", ".join(str(d) for d in self.rolls)
        breakdown = f"({roll_part})"
        if self.modifier > 0:
            breakdown += f" + {self.modifier}"
        elif self.modifier < 0:
            breakdown += f" - {abs(self.modifier)}"
        s = f"{base} {breakdown}"
        if self.value:
            s += f" = {self.value}"
        return s

    def __repr__(self):
        mod = ""
        if self.modifier:
            mod = f", modifier={self.modifier:+d}"
        return (
            f"Dice <count={self.count}, sides={self.sides}{mod}, "
            f"value={self.value}, rolls=[ {', '.join(map(str, self.rolls))} ]>"
        )

    def roll(self) -> Tuple[int]:
        """
        Rolls the dice in this instance and sets the value as the sum
        of the rolls plus :attr:`modifier`. Individual rolls are
        stored unchanged in :attr:`rolls` so a renderer can still
        show ``(r1 + r2) + C``.

        :return: A tuple containing the individual rolls (pre-modifier).
        """
        result: Tuple[int] = tuple(randint(1, self.sides) for _ in range(self.count))
        self.rolls = result
        self.value = sum(result) + self.modifier
        return result

    @staticmethod
    def quick_roll(ndn: str, keep: Optional[int] = None) -> int:
        """
        Generates a random number between the number of dice, and the number of dice times the number of sides.
        Ignores intermediate rolls and returns only the result.

        :param ndn: The number of dice and the sides per dice, such as "1d6" or "2d10"
        :param keep: [Optional] The number of dice to keep. For instance, if ndn is "4d6" and keep is 3, then the 3
        highest rolls are kept.
        :return: The integer sum of the generated numbers.
        """
        dice: Dice = Dice.from_ndn(ndn)
        if keep is not None and dice is not None and keep < dice.count:
            rolls = list(dice.rolls)
            rolls.sort()
            return sum(rolls[-keep:])
        return dice.value if dice else None

    def get_ndn(self):
        """Canonical string form: ``"NdM"`` or ``"NdM+C"`` / ``"NdM-C"``
        when the modifier is non-zero. Round-trippable through
        :meth:`from_ndn`."""
        s = f"{self.count}d{self.sides}"
        if self.modifier > 0:
            s += f"+{self.modifier}"
        elif self.modifier < 0:
            s += f"{self.modifier}"  # negative sign is already in the int
        return s

    @staticmethod
    def __int__(s: str):
        try:
            return 1 if s == "" else int(s)
        except Exception as e:
            _log.error(e)
            return 0

    @classmethod
    def from_ndn(cls, ndn: str) -> Union["Dice", None]:
        """
        Creates a new instance of dice from a string spec.

        Accepts:

        - ``"2d6"`` — two six-sided dice, modifier 0
        - ``"4d4+6"`` — four d4 with a flat +6 constant bonus
        - ``"3d10-2"`` — three d10 with a flat -2 constant penalty
        - ``"d20"`` — single d20 (die count defaults to 1)
        - whitespace around the sign is tolerated

        :param ndn: The dice spec, as documented above.
        :return: The :class:`Dice` instance, or ``None`` on invalid input.
        """
        if not ndn:
            return None
        match = _NDN_WITH_MOD_RE.match(ndn)
        if not match:
            return None

        count = int(match.group("count")) if match.group("count") else 1
        sides = int(match.group("sides"))
        modifier = 0
        if match.group("mod"):
            magnitude = int(match.group("mod"))
            modifier = magnitude if match.group("sign") == "+" else -magnitude

        if count < 1 or sides < 2:
            return None

        return cls(count, sides, modifier)

    @classmethod
    def d4(cls, count: int = 1) -> "Dice":
        """
        Creates a new nd4 instance of Dice.

        :param count: An optional number of d4 to simulate. Defaults to 1.
        :return: The Dice instance created.
        """
        return cls(1 if count is None or count < 0 else count, 4)

    @classmethod
    def d6(cls, count: Optional[int] = None) -> "Dice":
        """
        Creates a new nd6 instance of Dice.

        :param count: An optional number of d6 to simulate. Defaults to 1.
        :return: The Dice instance created.
        """
        return cls(1 if count is None or count < 0 else count, 6)

    @classmethod
    def d8(cls, count: Optional[int] = None) -> "Dice":
        """
        Creates a new nd8 instance of Dice.

        :param count: An optional number of d8 to simulate. Defaults to 1.
        :return: The Dice instance created.
        """
        return cls(1 if count is None or count < 0 else count, 8)

    @classmethod
    def d10(cls, count: Optional[int] = None) -> "Dice":
        """
        Creates a new nd10 instance of Dice.

        :param count: An optional number of d10 to simulate. Defaults to 1.
        :return: The Dice instance created.
        """
        return cls(1 if count is None or count < 0 else count, 10)

    @classmethod
    def d12(cls, count: Optional[int]) -> "Dice":
        """
        Creates a new nd12 instance of Dice.

        :param count: An optional number of d12 to simulate. Defaults to 1.
        :return: The Dice instance created.
        """
        return Dice(1 if count is None or count < 0 else count, 12)

    @classmethod
    def d20(cls, count: Optional[int] = None) -> "Dice":
        """
        Creates a new nd20 instance of Dice.

        :param count: An optional number of d20 to simulate. Defaults to 1.
        :return: The Dice instance created.
        """
        return cls(1 if count is None or count < 0 else count, 20)
