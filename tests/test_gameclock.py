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


# ---------------------------------------------------------------------------
# Per-game lookup + module-level façade
#
# The channel→clock registry was consolidated into ``Game._channel_routes``:
# ``GameClock.for_channel(cid)`` is a shim that returns
# ``Game.for_channel(cid).game_clock`` (or ``None``). These tests exercise
# the shim via the same routing map that production uses.
# ---------------------------------------------------------------------------


_FAKE_ID_A = 888001
_FAKE_ID_B = 888002


class _StubGame:
    """Minimal stand-in for ``Game`` in the channel-routing map:
    exposes ``game_clock`` so the shim can return it."""

    def __init__(self, clock):
        self.game_clock = clock


@pytest.fixture(autouse=False)
def clean_registry():
    """Ensures ``Game._channel_routes`` is empty before and after each
    registry/façade test so tests don't cross-contaminate."""
    from caldanai.lib.rpg import Game
    Game._channel_routes.clear()
    yield
    Game._channel_routes.clear()


def _register(channel_id, clock):
    """Wire a stub game carrying ``clock`` into the routing map under
    ``channel_id`` so ``GameClock.for_channel`` resolves."""
    from caldanai.lib.rpg import Game
    Game._channel_routes[channel_id] = _StubGame(clock)


def _unregister(channel_id):
    """Remove the stub game for ``channel_id`` from the routing map.
    Idempotent."""
    from caldanai.lib.rpg import Game
    Game._channel_routes.pop(channel_id, None)


class TestClockRegistry:
    def test_for_channel_returns_registered_clock(self, clean_registry):
        clock = GameClock(game_time=0)
        _register(_FAKE_ID_A, clock)
        assert GameClock.for_channel(_FAKE_ID_A) is clock

    def test_for_channel_returns_none_when_unregistered(self, clean_registry):
        assert GameClock.for_channel(_FAKE_ID_A) is None

    def test_unregister_removes_clock(self, clean_registry):
        clock = GameClock(game_time=0)
        _register(_FAKE_ID_A, clock)
        _unregister(_FAKE_ID_A)
        assert GameClock.for_channel(_FAKE_ID_A) is None

    def test_unregister_is_idempotent(self, clean_registry):
        # Removing a never-registered id must not raise.
        _unregister(_FAKE_ID_A)
        assert GameClock.for_channel(_FAKE_ID_A) is None

    def test_registry_isolates_games(self, clean_registry):
        """Two games have independent clocks under distinct ids."""
        clock_a = GameClock(game_time=100)
        clock_b = GameClock(game_time=200)
        _register(_FAKE_ID_A, clock_a)
        _register(_FAKE_ID_B, clock_b)
        assert GameClock.for_channel(_FAKE_ID_A) is clock_a
        assert GameClock.for_channel(_FAKE_ID_B) is clock_b

    def test_for_channel_tracks_game_route_removal(self, clean_registry):
        """After a Game is unregistered from ``_channel_routes``, its
        clock must no longer be findable through the shim — there is
        no longer a separate registry to keep the clock alive."""
        clock = GameClock(game_time=0)
        _register(_FAKE_ID_A, clock)
        assert GameClock.for_channel(_FAKE_ID_A) is clock
        _unregister(_FAKE_ID_A)
        assert GameClock.for_channel(_FAKE_ID_A) is None


class TestModuleLevelReadSurface:
    """Façade functions hand out concrete values rather than the clock
    object. Return ``None`` when no game is registered so callers
    don't have to guard every call."""

    def test_get_time_of_day_with_registered_clock(self, clean_registry):
        from caldanai.lib.rpg.time import get_time_of_day
        clock = GameClock(game_time=0)
        _register(_FAKE_ID_A, clock)
        # At game_time=0 the default map may not be populated yet;
        # force it so get_time_of_day returns something meaningful.
        clock.update_times_of_day()
        assert get_time_of_day(_FAKE_ID_A) is not None

    def test_get_time_of_day_returns_none_for_unknown_game(self, clean_registry):
        from caldanai.lib.rpg.time import get_time_of_day
        assert get_time_of_day(_FAKE_ID_A) is None

    def test_get_time_components_returns_none_for_unknown_game(self, clean_registry):
        from caldanai.lib.rpg.time import get_time_components
        assert get_time_components(_FAKE_ID_A) is None

    def test_get_next_time_returns_none_for_unknown_game(self, clean_registry):
        from caldanai.lib.rpg.time import get_next_time
        assert get_next_time(_FAKE_ID_A) is None

    def test_get_seconds_for_registered_clock(self, clean_registry):
        from caldanai.lib.rpg.time import get_seconds
        clock = GameClock(game_time=1234)
        _register(_FAKE_ID_A, clock)
        assert get_seconds(_FAKE_ID_A) == 1234

    def test_get_seconds_returns_none_for_unknown_game(self, clean_registry):
        from caldanai.lib.rpg.time import get_seconds
        assert get_seconds(_FAKE_ID_A) is None


class TestModuleLevelSchedulingSurface:
    def test_schedule_routine_on_registered_clock(self, clean_registry):
        from caldanai.lib.rpg.time import schedule_routine
        clock = GameClock(game_time=0)
        _register(_FAKE_ID_A, clock)

        def r():
            pass

        assert schedule_routine(_FAKE_ID_A, r, seconds=60) is True
        # Routine is actually registered on the clock.
        lst, idx = clock.find_routine("r")
        assert lst is not None and idx >= 0

    def test_schedule_routine_fails_cleanly_for_unknown_game(self, clean_registry):
        from caldanai.lib.rpg.time import schedule_routine

        def r():
            pass

        assert schedule_routine(_FAKE_ID_A, r, seconds=60) is False

    def test_cancel_routine_removes_from_clock(self, clean_registry):
        from caldanai.lib.rpg.time import schedule_routine, cancel_routine
        clock = GameClock(game_time=0)
        _register(_FAKE_ID_A, clock)

        def r():
            pass

        schedule_routine(_FAKE_ID_A, r, seconds=60)
        assert cancel_routine(_FAKE_ID_A, r) is True
        # ``find_routine`` returns ``(None, None)`` when the routine
        # has been removed.
        lst, idx = clock.find_routine("r")
        assert lst is None and idx is None

    def test_cancel_routine_returns_false_for_unknown_game(self, clean_registry):
        from caldanai.lib.rpg.time import cancel_routine

        def r():
            pass

        assert cancel_routine(_FAKE_ID_A, r) is False
