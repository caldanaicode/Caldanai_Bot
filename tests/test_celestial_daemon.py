"""Tests for ``CelestialDaemon``.

Covers:
- Sunrise fires exactly once when crossing the dawn boundary.
- Sunset fires exactly once when crossing the dusk boundary.
- Subsequent ticks past a crossing do NOT re-emit.
- The kill switch (``Game.enable_ambience=False``) suppresses
  sunrise/sunset emission.
- Regression guard: ``Game.do_ambience`` does NOT emit sunrise/sunset
  lines (the daemon owns them now).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.rpg.ambience.celestial import (
    CelestialDaemon,
    SUNRISE_NARRATION,
    SUNSET_NARRATION,
)
from caldanai.lib.rpg.time import GameClock


FAKE_CHANNEL_ID = 555321


@pytest.fixture(autouse=False)
def clean_registry():
    """Ensures ``Game._channel_routes`` is empty before and after each
    test so tests don't cross-contaminate. ``GameClock.for_channel``
    resolves through this same map, so there is no separate clock
    registry to clear."""
    from caldanai.lib.rpg import Game
    Game._channel_routes.clear()
    yield
    Game._channel_routes.clear()


def _make_ambience_game(
    channel_id: int,
    clock: GameClock,
    enable_ambience: bool = True,
    enable_ambience_celestial: bool = True,
    enable_ambience_local: bool = True,
    enable_ambience_weather: bool = True,
):
    """Return a minimal stand-in for ``Game`` suitable for
    ``Game._channel_routes`` routing: holds the ambience flags, a
    mock ``channel`` whose id matches ``channel_id``, and the clock
    (so ``GameClock.for_channel`` resolves through the shim).

    ``ambience_enabled`` is wired to ANDs the master with the named
    subsystem flag — matches the real ``Game.ambience_enabled``
    contract so the daemons' gate logic resolves correctly against
    this shim."""
    game = MagicMock()
    game.enable_ambience = enable_ambience
    game.enable_ambience_celestial = enable_ambience_celestial
    game.enable_ambience_local = enable_ambience_local
    game.enable_ambience_weather = enable_ambience_weather
    game.channel = MagicMock()
    game.channel.id = channel_id
    game.game_clock = clock

    def _ambience_enabled(subsystem: str) -> bool:
        if not game.enable_ambience:
            return False
        return bool(getattr(game, f"enable_ambience_{subsystem}", True))

    game.ambience_enabled = _ambience_enabled
    return game


def _register_clock_and_game(clock: GameClock, game, channel_id: int):
    """Wire the Game channel-routing map so ``Game.for_channel`` and
    ``GameClock.for_channel`` resolve during daemon tick. The clock is
    already on ``game.game_clock`` — no separate registration step."""
    from caldanai.lib.rpg import Game
    Game._channel_routes[channel_id] = game


# ---------------------------------------------------------------------------
# Sunrise crossing
# ---------------------------------------------------------------------------


class TestSunriseCrossing:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_sunrise_fires_once_on_crossing(
        self, mock_dispatch, clean_registry,
    ):
        """The first tick whose game-time crosses sunrise emits the
        sunrise narration exactly once."""
        # Place the clock one second before sunrise.
        clock = GameClock(game_time=0)
        sunrise, _ = clock.get_sunrise_and_sunset()
        sunrise_s = sunrise.get_seconds()
        # Seed clock to one second before sunrise.
        clock._seconds = sunrise_s - 1

        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=True)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        # Advance the clock past sunrise and tick once.
        clock._seconds = sunrise_s + 1
        await daemon.tick()

        # Exactly one dispatch, and it's the sunrise text.
        mock_dispatch.add.assert_called_once()
        args = mock_dispatch.add.call_args.args
        assert args[0] is game.channel
        assert args[1] == SUNRISE_NARRATION

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_sunrise_does_not_refire_on_same_day(
        self, mock_dispatch, clean_registry,
    ):
        """After the crossing, additional ticks on the same day don't
        re-emit the sunrise narration."""
        clock = GameClock(game_time=0)
        sunrise, _ = clock.get_sunrise_and_sunset()
        sunrise_s = sunrise.get_seconds()
        clock._seconds = sunrise_s - 1

        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=True)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        # First tick — crossing. Expect 1 dispatch.
        clock._seconds = sunrise_s + 1
        await daemon.tick()
        assert mock_dispatch.add.call_count == 1

        # Second tick — a few seconds later, still dawn. Expect no new
        # dispatch (the window has moved past sunrise).
        clock._seconds = sunrise_s + 10
        await daemon.tick()
        assert mock_dispatch.add.call_count == 1

        # Third tick — well into the morning. Still no re-fire.
        clock._seconds = sunrise_s + 3600
        await daemon.tick()
        assert mock_dispatch.add.call_count == 1


# ---------------------------------------------------------------------------
# Sunset crossing
# ---------------------------------------------------------------------------


class TestSunsetCrossing:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_sunset_fires_once_on_crossing(
        self, mock_dispatch, clean_registry,
    ):
        """The first tick whose game-time crosses sunset emits the
        sunset narration exactly once."""
        clock = GameClock(game_time=0)
        _, sunset = clock.get_sunrise_and_sunset()
        sunset_s = sunset.get_seconds()
        clock._seconds = sunset_s - 1

        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=True)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        clock._seconds = sunset_s + 1
        await daemon.tick()

        mock_dispatch.add.assert_called_once()
        args = mock_dispatch.add.call_args.args
        assert args[0] is game.channel
        assert args[1] == SUNSET_NARRATION

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_sunset_does_not_fire_outside_crossing_window(
        self, mock_dispatch, clean_registry,
    ):
        """Ticks that don't straddle the sunset boundary emit
        nothing."""
        clock = GameClock(game_time=0)
        _, sunset = clock.get_sunrise_and_sunset()
        sunset_s = sunset.get_seconds()
        # Seed clock to well after sunset.
        clock._seconds = sunset_s + 600

        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=True)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        # Next tick — another minute later, still past sunset.
        clock._seconds = sunset_s + 660
        await daemon.tick()
        mock_dispatch.add.assert_not_called()


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


class TestAmbienceKillSwitch:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_disabled_ambience_suppresses_sunrise(
        self, mock_dispatch, clean_registry,
    ):
        """Option (a) of the refactor decision: when
        ``Game.enable_ambience=False``, clock-driven sunrise
        narration is suppressed too — same behavior as the
        pre-refactor kill switch."""
        clock = GameClock(game_time=0)
        sunrise, _ = clock.get_sunrise_and_sunset()
        sunrise_s = sunrise.get_seconds()
        clock._seconds = sunrise_s - 1

        # Ambience disabled on the game.
        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=False)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        clock._seconds = sunrise_s + 1
        await daemon.tick()

        mock_dispatch.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_disabled_ambience_suppresses_sunset(
        self, mock_dispatch, clean_registry,
    ):
        clock = GameClock(game_time=0)
        _, sunset = clock.get_sunrise_and_sunset()
        sunset_s = sunset.get_seconds()
        clock._seconds = sunset_s - 1

        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=False)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        clock._seconds = sunset_s + 1
        await daemon.tick()

        mock_dispatch.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_no_buffered_crossing_replay_when_reenabled(
        self, mock_dispatch, clean_registry,
    ):
        """A crossing that happens while ambience is disabled is NOT
        replayed when ambience is turned back on later the same day.
        The tick advances the window regardless of the kill switch."""
        clock = GameClock(game_time=0)
        sunrise, _ = clock.get_sunrise_and_sunset()
        sunrise_s = sunrise.get_seconds()
        clock._seconds = sunrise_s - 1

        # Start disabled.
        game = _make_ambience_game(FAKE_CHANNEL_ID, clock, enable_ambience=False)
        _register_clock_and_game(clock, game, FAKE_CHANNEL_ID)

        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        daemon.start()

        # Cross sunrise while disabled → no emission, but window advances.
        clock._seconds = sunrise_s + 1
        await daemon.tick()
        mock_dispatch.add.assert_not_called()

        # Re-enable ambience and tick again — a few seconds later, past
        # sunrise already. Should NOT retroactively narrate.
        game.enable_ambience = True
        clock._seconds = sunrise_s + 5
        await daemon.tick()
        mock_dispatch.add.assert_not_called()


# ---------------------------------------------------------------------------
# Missing-clock defensiveness
# ---------------------------------------------------------------------------


class TestMissingClock:
    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_start_without_registered_clock_is_noop(
        self, mock_dispatch, clean_registry,
    ):
        """If no clock is registered for the channel, start() quietly
        no-ops instead of raising — this runs during Game construction
        before the clock is registered in some paths."""
        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        # Must not raise.
        daemon.start()
        assert daemon._last_tick_seconds is None

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.ambience.celestial.Dispatcher")
    async def test_tick_without_registered_clock_is_noop(
        self, mock_dispatch, clean_registry,
    ):
        """A tick firing after the clock has been unregistered (race
        with teardown) is a no-op."""
        daemon = CelestialDaemon(FAKE_CHANNEL_ID)
        # No clock registered — tick must not raise.
        await daemon.tick()
        mock_dispatch.add.assert_not_called()


# ---------------------------------------------------------------------------
# Regression: Game.do_ambience no longer emits sunrise/sunset
# ---------------------------------------------------------------------------


class TestDoAmbienceNoLongerEmitsTransitions:
    """After the refactor, ``Game.do_ambience`` is the random
    flavor-choice roll only — it must not emit sunrise or sunset
    narration (the daemon owns that)."""

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_do_ambience_does_not_emit_sunrise_text(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game

        guild = MagicMock(); guild.id = 111; guild.roles = []
        channel = MagicMock(); channel.id = 222
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}

        # Configure clock mock so construction doesn't start ticks.
        # ``get_season`` returns a valid int so the weather daemon's
        # ``Seasons(...)`` conversion at start succeeds.
        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.get_season.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=True,
        )

        # Force the random roll to NOT fire (controls the only
        # remaining source of dispatch in do_ambience), so any
        # sunrise/sunset emission would be a regression.
        with patch("caldanai.lib.rpg.random") as mock_random:
            mock_random.randint.return_value = 1  # never hits 3000
            await game.do_ambience()

        # No Dispatcher call whatsoever from the routine.
        mock_dispatch.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    async def test_do_ambience_kill_switch_still_removes_routine(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        """Existing kill-switch-self-removal behavior must still work:
        when ambience is flipped off and the routine fires once more,
        it removes itself from the clock."""
        from caldanai.lib.rpg import Game

        guild = MagicMock(); guild.id = 111; guild.name = "G"; guild.roles = []
        channel = MagicMock(); channel.id = 222
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.get_season.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=True,
        )
        game.enable_ambience = False

        await game.do_ambience()

        # Self-removal path: the routine asks the clock to drop it.
        game.game_clock.remove_routine.assert_called_with(game.do_ambience)
        mock_dispatch.add.assert_not_called()


# ---------------------------------------------------------------------------
# _last_ambience_tick field removed from Game
# ---------------------------------------------------------------------------


class TestGameFieldRemoved:
    """``_last_ambience_tick`` was only read/written by the old
    sunrise/sunset code in ``do_ambience``. After the refactor it
    should not be present on ``Game`` instances."""

    @patch("caldanai.lib.rpg.Dispatcher")
    @patch("caldanai.lib.rpg.DB")
    @patch("caldanai.lib.rpg.player_manager")
    @patch("caldanai.lib.rpg.GameClock")
    def test_last_ambience_tick_not_on_game(
        self, mock_gc_cls, mock_pm_cls, mock_db, mock_dispatch,
    ):
        from caldanai.lib.rpg import Game

        guild = MagicMock(); guild.id = 111; guild.roles = []
        channel = MagicMock(); channel.id = 222
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}

        mock_gc = MagicMock()
        mock_gc.get_seconds.return_value = 0
        mock_gc.time_scale = 4
        mock_gc_cls.return_value = mock_gc

        game = Game(
            guild=guild, channel=channel,
            use_spawn_timer=False, enable_ambience=False,
        )
        assert not hasattr(game, "_last_ambience_tick")
