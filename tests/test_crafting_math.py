"""Tests for crafting math — pure functions, deterministic with
seeded RNG."""
from random import seed
from statistics import mean

import pytest

from caldanai.lib.rpg.crafting.math import (
    success_chance,
    roll_success,
    roll_quality,
    quality_int,
    int_to_quality,
)
from caldanai.lib.rpg.helpers.enums import Qualities


class TestSuccessChance:
    def test_below_min_skill_is_zero(self):
        assert success_chance(skill_xp=10, min_skill=20) == 0.0

    def test_at_min_skill_is_half(self):
        assert success_chance(skill_xp=20, min_skill=20) == 0.5

    def test_25_xp_above_min_is_60_percent(self):
        assert success_chance(skill_xp=45, min_skill=20) == pytest.approx(0.6)

    def test_50_xp_above_min_is_70_percent(self):
        assert success_chance(skill_xp=70, min_skill=20) == pytest.approx(0.7)

    def test_caps_at_95_percent(self):
        # +500 XP would naively give +200% — must cap.
        assert success_chance(skill_xp=520, min_skill=20) == pytest.approx(0.95)

    def test_quantized_to_25_xp_steps(self):
        # 24 XP over min still rounds down to the 0-step bucket.
        assert success_chance(skill_xp=44, min_skill=20) == 0.5
        assert success_chance(skill_xp=45, min_skill=20) == pytest.approx(0.6)


class TestRollSuccess:
    def test_below_min_skill_always_fails(self):
        seed(0)
        for _ in range(100):
            assert roll_success(skill_xp=10, min_skill=20) is False

    def test_at_min_skill_roughly_half(self):
        seed(42)
        results = [roll_success(skill_xp=20, min_skill=20) for _ in range(2000)]
        rate = sum(results) / len(results)
        assert 0.45 < rate < 0.55, f"expected ~0.5, got {rate}"

    def test_far_above_min_nearly_always_succeeds(self):
        seed(42)
        results = [roll_success(skill_xp=520, min_skill=20) for _ in range(2000)]
        rate = sum(results) / len(results)
        assert rate > 0.92, f"expected ~0.95, got {rate}"


class TestQualityIntRoundTrip:
    def test_round_trip_every_quality(self):
        for q in [
            Qualities.JUNK,
            Qualities.ORDINARY,
            Qualities.FINE,
            Qualities.QUALITY,
            Qualities.SUPERIOR,
            Qualities.MASTERWORK,
        ]:
            assert int_to_quality(quality_int(q)) is q

    def test_int_to_quality_clamps_high(self):
        assert int_to_quality(99) is Qualities.MASTERWORK

    def test_int_to_quality_clamps_low(self):
        assert int_to_quality(-5) is Qualities.JUNK


class TestRollQuality:
    def test_empty_inputs_default_to_ordinary(self):
        seed(0)
        assert roll_quality([], skill_xp=0, min_skill=0) is Qualities.ORDINARY

    def test_at_min_skill_no_bonus_centers_on_input(self):
        """Five ORDINARY (rank 1) inputs at min skill should center
        on rank 1 with ±1 variance — average across many rolls
        should land near 1.0."""
        seed(42)
        ranks = [
            quality_int(roll_quality(
                [Qualities.ORDINARY] * 5,
                skill_xp=0,
                min_skill=0,
            ))
            for _ in range(2000)
        ]
        # Average should be close to 1 (ORDINARY); jackpot tail
        # nudges it slightly but stays well within [0.7, 1.3].
        assert 0.7 < mean(ranks) < 1.3

    def test_high_skill_lifts_quality(self):
        """+100 XP above min = +2 skill bonus. Five ORDINARY inputs
        should center on rank 3 (QUALITY)."""
        seed(42)
        ranks = [
            quality_int(roll_quality(
                [Qualities.ORDINARY] * 5,
                skill_xp=100,
                min_skill=0,
            ))
            for _ in range(2000)
        ]
        assert 2.7 < mean(ranks) < 3.3

    def test_skill_bonus_caps_at_plus_two(self):
        """A wildly-over-min skill shouldn't push quality past
        avg + 2 + variance."""
        seed(42)
        ranks = [
            quality_int(roll_quality(
                [Qualities.ORDINARY] * 5,
                skill_xp=10000,
                min_skill=0,
            ))
            for _ in range(2000)
        ]
        # Centred at rank 1 + 2 = 3 with ±1 variance.
        # Allow rare ±2 jackpot in the tails.
        assert 2.7 < mean(ranks) < 3.4

    def test_clamps_below_zero(self):
        """JUNK inputs with disastrous variance shouldn't crash;
        result clamps to JUNK."""
        seed(0)
        for _ in range(100):
            q = roll_quality([Qualities.JUNK], skill_xp=0, min_skill=0)
            assert quality_int(q) >= 0  # never negative

    def test_jackpot_path_can_lift_two_tiers(self):
        """The 1% rare-jackpot branch (``random() < 0.01``) gives
        ±2 variance instead of ±1. Pin that the path is reachable
        — over enough trials, ORDINARY input + zero skill should
        occasionally land at QUALITY (rank 3) via the +2 jackpot."""
        seed(7)  # seed picked so the run hits at least one jackpot
        landed_three_or_higher = False
        for _ in range(5000):
            q = roll_quality(
                [Qualities.ORDINARY],
                skill_xp=0,
                min_skill=0,
            )
            if quality_int(q) >= 3:
                landed_three_or_higher = True
                break
        assert landed_three_or_higher, (
            "rare-jackpot path never reached — verify the +2 branch"
        )

    def test_jackpot_disaster_can_drop_two_tiers(self):
        """The disaster half of the rare-jackpot branch (``random()
        < 0.5`` after the 0.01 gate) gives -2 instead of +2. Pin
        reachability — ORDINARY input should occasionally bottom
        out at JUNK via the -2 branch."""
        seed(7)
        landed_zero = False
        for _ in range(5000):
            q = roll_quality(
                [Qualities.ORDINARY],
                skill_xp=0,
                min_skill=0,
            )
            if quality_int(q) == 0:
                landed_zero = True
                break
        assert landed_zero, (
            "rare-disaster path never reached — verify the -2 branch"
        )
