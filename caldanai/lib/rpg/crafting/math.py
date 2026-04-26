"""Pure success / quality math for crafting.

No I/O, no randomness state — every function takes its inputs
and returns a deterministic answer (or a value driven by the
shared :mod:`random` module, which tests seed). Keeps the rules
auditable in one place: the cog and the tests both consume
these.
"""
from random import randint, random
from typing import Iterable, List

from caldanai.lib.rpg.helpers.enums import Qualities


_QUALITY_ORDER: List[Qualities] = [
    Qualities.JUNK,
    Qualities.ORDINARY,
    Qualities.FINE,
    Qualities.QUALITY,
    Qualities.SUPERIOR,
    Qualities.MASTERWORK,
]


def quality_int(q: Qualities) -> int:
    """Map a quality to its rank int (JUNK=0 … MASTERWORK=5)."""
    return _QUALITY_ORDER.index(q)


def int_to_quality(i: int) -> Qualities:
    """Map a rank int back to a quality, clamped to the valid range."""
    clamped = max(0, min(len(_QUALITY_ORDER) - 1, i))
    return _QUALITY_ORDER[clamped]


def success_chance(skill_xp: int, min_skill: int) -> float:
    """Probability the craft succeeds.

    - Below ``min_skill``: 0 (caller refuses outright).
    - At ``min_skill``: 0.5.
    - +0.1 per +25 XP above ``min_skill``, capped at 0.95.
    """
    if skill_xp < min_skill:
        return 0.0
    over = skill_xp - min_skill
    return min(0.95, 0.5 + 0.1 * (over // 25))


def roll_success(skill_xp: int, min_skill: int) -> bool:
    """Did the craft attempt succeed? Pulls one ``random()``."""
    return random() < success_chance(skill_xp, min_skill)


def roll_quality(
    input_qualities: Iterable[Qualities],
    skill_xp: int,
    min_skill: int,
) -> Qualities:
    """Quality of the crafted output (only call after a successful roll).

    Combines:

    - **Average input quality** (rounded to nearest int).
    - **Skill bonus**: +1 per 50 XP above ``min_skill``, soft-capped at +2.
    - **Variance**: usually ``randint(-1, 1)``; 1% rare jackpot for ±2.

    The combined int is clamped to the valid quality range. So
    five ORDINARY (rank 1) inputs + 100 XP over min (skill_bonus
    +2) lands at rank 3 (QUALITY) before variance, with rare
    jackpots reaching SUPERIOR / MASTERWORK.
    """
    qs = list(input_qualities)
    if not qs:
        return Qualities.ORDINARY
    avg = round(sum(quality_int(q) for q in qs) / len(qs))

    over = max(0, skill_xp - min_skill)
    skill_bonus = min(2, over // 50)

    # Most rolls land in ±1; rare jackpot/disaster of ±2.
    if random() < 0.01:
        variance = 2 if random() < 0.5 else -2
    else:
        variance = randint(-1, 1)

    return int_to_quality(avg + skill_bonus + variance)
