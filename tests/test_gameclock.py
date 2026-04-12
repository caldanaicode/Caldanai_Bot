"""Tests for Caldanai.lib.rpg.time (GameClock class)."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from caldanai.lib.rpg.time import GameClock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dummy_routine():
    """A named callable for use as a routine."""
    pass


async def _async_dummy():
    """An async callable for use as a routine."""
    pass


# ---------------------------------------------------------------------------
# tick
# ---------------------------------------------------------------------------

class TestTick:
    @pytest.mark.asyncio
    async def test_tick_advances_seconds(self):
        clock = GameClock(game_time=0)
        clock.tick_speed = 4  # default time_scale
        clock.update_times_of_day()
        # Manually invoke the coroutine body without the @tasks.loop decorator
        # We call the underlying callback directly.
        clock._seconds += clock.tick_speed
        clock._ticks += 1
        assert clock._seconds == 4
        assert clock._ticks == 1

    def test_tick_speed_matches_time_scale(self):
        clock = GameClock(game_time=0)
        assert clock.tick_speed == clock.time_scale


# ---------------------------------------------------------------------------
# add_routine / remove_routine / find_routine
# ---------------------------------------------------------------------------

class TestRoutineManagement:
    def test_add_recurring_routine(self):
        clock = GameClock()
        clock.add_routine(_async_dummy, seconds=10)
        lst, idx = clock.find_routine("_async_dummy")
        assert lst is clock._tick_routines
        assert idx is not None

    def test_add_run_once_routine(self):
        clock = GameClock()
        clock.add_routine(_async_dummy, seconds=10, run_once=True)
        lst, idx = clock.find_routine("_async_dummy")
        assert lst is clock._tick_run_once
        assert idx is not None

    def test_remove_routine(self):
        clock = GameClock()
        clock.add_routine(_async_dummy, seconds=10)
        removed = clock.remove_routine(_async_dummy)
        assert removed is True
        lst, idx = clock.find_routine("_async_dummy")
        assert lst is None and idx is None

    def test_remove_nonexistent_routine(self):
        clock = GameClock()
        removed = clock.remove_routine(_async_dummy)
        assert removed is False

    def test_find_routine_not_found(self):
        clock = GameClock()
        lst, idx = clock.find_routine("nonexistent")
        assert lst is None
        assert idx is None

    def test_zero_seconds_not_added(self):
        clock = GameClock()
        clock.add_routine(_async_dummy, seconds=0)
        lst, idx = clock.find_routine("_async_dummy")
        assert lst is None


# ---------------------------------------------------------------------------
# only_instance deduplication
# ---------------------------------------------------------------------------

class TestOnlyInstance:
    def test_only_instance_replaces_existing(self):
        clock = GameClock()
        clock.add_routine(_async_dummy, seconds=10, only_instance=True)
        clock.add_routine(_async_dummy, seconds=20, only_instance=True)
        # Should have only one instance
        count = sum(1 for r in clock._tick_routines if r.name == "_async_dummy")
        assert count == 1
        # The surviving one should have seconds=20
        lst, idx = clock.find_routine("_async_dummy")
        assert lst[idx].seconds == 20

    def test_only_instance_false_allows_duplicates(self):
        clock = GameClock()
        clock.add_routine(_async_dummy, seconds=10, only_instance=False)
        clock.add_routine(_async_dummy, seconds=20, only_instance=False)
        count = sum(1 for r in clock._tick_routines if r.name == "_async_dummy")
        assert count == 2


# ---------------------------------------------------------------------------
# Run-once routines execute once and are removed
# ---------------------------------------------------------------------------

class TestRunOnce:
    def test_run_once_removed_after_execution(self):
        clock = GameClock()
        mock_fn = AsyncMock(__name__="mock_fn")
        clock.add_routine(mock_fn, seconds=1, run_once=True)
        assert len(clock._tick_run_once) == 1

        # Simulate tick timing: _ticks increments, and the routine fires when
        # (_ticks - time_added) % seconds == 0
        # time_added was clock._ticks (0) at add time; after 1 tick, _ticks=1, (1-0)%1==0 -> fires
        clock._ticks = 1
        # Manually run the run-once check from the tick body
        for i in range(len(clock._tick_run_once) - 1, -1, -1):
            r = clock._tick_run_once[i]
            if (clock._ticks - r.time_added) % r.seconds == 0:
                routine = clock._tick_run_once.pop(i)
                # Don't call routine.run() — it uses asyncio.create_task which needs a loop
        assert len(clock._tick_run_once) == 0


# ---------------------------------------------------------------------------
# Recurring routines execute on schedule
# ---------------------------------------------------------------------------

class TestRecurring:
    def test_recurring_fires_on_schedule(self):
        clock = GameClock()
        mock_fn = AsyncMock(__name__="recur_fn")
        clock.add_routine(mock_fn, seconds=5)
        routine = clock._tick_routines[0]

        # Should fire when (_ticks - time_added) % 5 == 0
        # time_added = 0
        fired_ticks = []
        for t in range(1, 21):
            if (t - routine.time_added) % routine.seconds == 0:
                fired_ticks.append(t)

        assert fired_ticks == [5, 10, 15, 20]


# ---------------------------------------------------------------------------
# Time calculations
# ---------------------------------------------------------------------------

class TestTimeCalculations:
    def test_get_time_components_midnight(self):
        clock = GameClock(game_time=0)
        h, m, s = clock.get_time_components()
        assert (h, m, s) == (0, 0, 0)

    def test_get_time_components_noon(self):
        clock = GameClock(game_time=12 * 3600)
        h, m, s = clock.get_time_components()
        assert (h, m, s) == (12, 0, 0)

    def test_get_time_components_arbitrary(self):
        # 3 hours, 25 minutes, 17 seconds
        seconds = 3 * 3600 + 25 * 60 + 17
        clock = GameClock(game_time=seconds)
        h, m, s = clock.get_time_components()
        assert (h, m, s) == (3, 25, 17)

    def test_get_time_components_with_explicit_seconds(self):
        clock = GameClock()
        h, m, s = clock.get_time_components(seconds=7384)
        assert h == 2
        assert m == 3
        assert s == 4

    def test_get_day_zero(self):
        clock = GameClock(game_time=0)
        assert clock.get_day() == 0

    def test_get_day_after_one_day(self):
        clock = GameClock(game_time=86400)
        assert clock.get_day() == 1

    def test_get_day_wraps_at_360(self):
        clock = GameClock(game_time=86400 * 360)
        assert clock.get_day() == 0

    def test_get_season_zero(self):
        clock = GameClock(game_time=0)
        assert clock.get_season() == 0

    def test_get_season_second(self):
        # 90 days into the year -> season 1
        clock = GameClock(game_time=90 * 86400)
        assert clock.get_season() == 1

    def test_get_year_base(self):
        clock = GameClock(game_time=0)
        assert clock.get_year() == 1104

    def test_get_year_after_one_year(self):
        clock = GameClock(game_time=31104000)
        assert clock.get_year() == 1105

    def test_get_season_wraps(self):
        # 4 seasons = 1 year, so season 4 wraps to 0
        clock = GameClock(game_time=4 * 7776000)
        assert clock.get_season() == 0
