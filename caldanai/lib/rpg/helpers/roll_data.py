from typing import Tuple

from caldanai.lib.rpg.helpers.dice import Dice


class RollData:
    """
    Simple structure for packaging a die roll with skill bonus. NOT INTENDED FOR DIRECT USE!

    Please use AttackRoll or DamageRoll which inherit from this class.

    Attributes
    ----------
    rolls : Tuple
        The natural rolls with no bonuses applied.
    skillBonus : int
        The bonus applied due to skill level.
    result : int
        The result of the roll + bonus.
    """

    def __init__(self, dice: Dice, skill_bonus: int):
        self.rolls: Tuple[int] = dice.rolls
        self.sides = dice.sides
        # Q.6.3-followup: dice specs can carry a static constant
        # modifier (``"2d6+2"``). ``dice.value`` already sums rolls +
        # modifier, so ``result`` below is correct — the modifier is
        # surfaced separately so the renderer can show ``(r1 + r2) +
        # C`` rather than a pre-merged single number.
        self.diceModifier: int = getattr(dice, "modifier", 0)
        self.skillBonus: int = skill_bonus
        self.result = dice.value + skill_bonus


class AttackRoll(RollData):
    """
    Simple structure for packaging a d20 roll with a skill bonus.

    Attributes
    ----------
    isCritical : bool
        Whether or not the roll is a critical hit (natural 20).
    isFumble : bool
        Whether or not the roll is a fumble (natural 1).
    """

    def __init__(self, skill_bonus: int):
        super().__init__(Dice(1, 20), skill_bonus)
        self.isCritical = self.rolls[0] == 20
        self.isFumble = self.rolls[0] == 1

    def __str__(self):
        return (
            f"{' + '.join(str(r) for r in self.rolls)}"
            f"{' + ' + str(self.skillBonus) if self.skillBonus > 0 and not self.isFumble else ''}"
        )


class DamageRoll(RollData):
    """
    Simple structure for packaging an NdN roll with a skill bonus and a weapon bonus.
    """

    def __init__(self, dice: Dice, skill_bonus: int, weapon_bonus: int):
        super().__init__(dice, skill_bonus)
        self.weaponBonus = weapon_bonus
        self.result += weapon_bonus

    def __str__(self):
        # Render order: ``(r1 + r2 + ... + rN)`` then each non-zero
        # term appended — dice-spec modifier first (it was baked into
        # the spec string and conceptually belongs with the dice),
        # then skill bonus, then weapon bonus. Parens open whenever
        # there's more than one die OR any bonus term (a bare single-
        # die roll stays unwrapped — ``5`` not ``(5)``).
        needs_parens = (
            len(self.rolls) > 1
            or self.diceModifier
            or self.skillBonus
            or self.weaponBonus
        )
        msg = (
            f"{'(' if needs_parens else ''}"
            f"{' + '.join(str(r) for r in self.rolls)}"
            f"{')' if needs_parens else ''}"
        )
        show_result = False

        def _signed(value: int) -> str:
            return (
                f" {'+' if value > 0 else '-'} {abs(value)}"
            )

        if self.diceModifier != 0:
            msg += _signed(self.diceModifier)
            show_result = True
        if self.skillBonus != 0:
            msg += _signed(self.skillBonus)
            show_result = True
        if self.weaponBonus != 0:
            msg += _signed(self.weaponBonus)
            show_result = True
        if show_result:
            msg += f" = {self.result}"

        return msg


class CombinedRoll:
    """
    A structure that packages together an AttackRoll and DamageRoll against monster data, providing easy access to
    interdependent data such as critical damage, fumbled damage.

    Attributes
    ----------
    attack : AttackRoll
        Attack roll data
    damage : DamageRoll
        Damage roll data
    isMiss : bool
        True if the attack fumbles or misses.
    isCritical : bool
        True if the attack roll is a natural 20.
    isFumble : bool
        True if the attack roll is a natural 1.
    result : int
        The total of the damage accounting for miss/fumble, or critical hit multipliers.
    """

    def __init__(self, attack: AttackRoll, damage: DamageRoll, dodge: int = 0, is_miss: bool = False):
        self.attack = attack
        self.damage = damage
        self.isMiss = not attack.isCritical and (is_miss or attack.isFumble or attack.result < dodge)
        self.isCritical = attack.isCritical
        self.isFumble = attack.isFumble
        self.result = damage.result * (0 if self.isMiss else 2 if self.attack.isCritical else 1)

    def get_hit_string(self):
        return f"{'FUMBLE' if self.isFumble else 'MISS' if self.isMiss else 'CRIT' if self.isCritical else 'HIT'}"
