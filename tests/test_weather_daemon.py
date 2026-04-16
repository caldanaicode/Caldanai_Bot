"""Tests for ``WeatherDaemon``.

Covers:
- Initial state (clear skies, empty severities dict).
- ``describe()`` output across states (clear, single-component,
  multi-component, with/without wind interaction on precip).
- Per-component severity independence.
- Persistence round-trip.
- Tick decrement + transition trigger.
- Transition invariants (heavy wind disperses fog; precipitation
  absorbs standalone cloud).
"""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.ambience.weather import WeatherDaemon
from caldanai.lib.rpg.helpers.enums import (
    Seasons, WeatherPatterns, WeatherSeverities,
)


FAKE_CHANNEL_ID = 777123


class TestInitialState:
    def test_starts_clear(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        assert d.is_clear()
        assert d.severities == {}
        assert d.active_patterns == WeatherPatterns.CLEAR
        assert d.severity_of(WeatherPatterns.PRECIPITATION) is None


class TestDescribe:
    def test_clear_description(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        assert d.describe() == "The sky is clear."

    def test_light_rain_no_wind(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {WeatherPatterns.PRECIPITATION: WeatherSeverities.LIGHT}
        text = d.describe()
        assert "light rain" in text.lower() or "drifts down" in text.lower()

    def test_heavy_rain_with_heavy_wind_flavors_differently(self):
        """Wind interaction with precipitation produces distinct text
        vs. still-air heavy rain (the whole point of per-component
        severity)."""
        still = WeatherDaemon(FAKE_CHANNEL_ID)
        still.severities = {WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY}

        driven = WeatherDaemon(FAKE_CHANNEL_ID)
        driven.severities = {
            WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY,
            WeatherPatterns.WIND: WeatherSeverities.HEAVY,
        }
        assert still.describe() != driven.describe()

    def test_fog_alone(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {WeatherPatterns.FOG: WeatherSeverities.MODERATE}
        assert "fog" in d.describe().lower() or "mist" in d.describe().lower()

    def test_wind_only_without_precipitation(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {WeatherPatterns.WIND: WeatherSeverities.MODERATE}
        # Wind stands on its own when precip isn't active.
        text = d.describe().lower()
        assert "wind" in text or "breeze" in text or "gale" in text

    def test_wind_with_precipitation_does_not_double_report(self):
        """When precipitation is active, wind is folded into the
        precipitation description. Shouldn't appear as a separate
        sentence (reads oddly: 'rain lashes... a strong wind blows')."""
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {
            WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY,
            WeatherPatterns.WIND: WeatherSeverities.HEAVY,
        }
        text = d.describe()
        # One sentence, not two. (Heuristic: no period mid-string.)
        stripped = text.rstrip(".")
        assert "." not in stripped


class TestPerComponentSeverity:
    def test_severity_of_returns_per_component(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {
            WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY,
            WeatherPatterns.WIND: WeatherSeverities.LIGHT,
        }
        assert d.severity_of(WeatherPatterns.PRECIPITATION) == WeatherSeverities.HEAVY
        assert d.severity_of(WeatherPatterns.WIND) == WeatherSeverities.LIGHT
        assert d.severity_of(WeatherPatterns.FOG) is None

    def test_active_patterns_is_union(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {
            WeatherPatterns.PRECIPITATION: WeatherSeverities.MODERATE,
            WeatherPatterns.WIND: WeatherSeverities.LIGHT,
        }
        expected = WeatherPatterns.PRECIPITATION | WeatherPatterns.WIND
        assert d.active_patterns == expected


class TestPersistence:
    def test_round_trip(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {
            WeatherPatterns.PRECIPITATION: WeatherSeverities.HEAVY,
            WeatherPatterns.WIND: WeatherSeverities.MODERATE,
        }
        d._duration_remaining = 123

        payload = d.to_dict()
        restored = WeatherDaemon(FAKE_CHANNEL_ID)
        restored.load_dict(payload)

        assert restored.severities == d.severities
        assert restored._duration_remaining == 123

    def test_round_trip_clear_state(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d._duration_remaining = 50
        payload = d.to_dict()
        restored = WeatherDaemon(FAKE_CHANNEL_ID)
        restored.load_dict(payload)
        assert restored.is_clear()
        assert restored._duration_remaining == 50

    def test_load_dict_handles_missing_severities(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.load_dict({"duration_remaining": 10})
        assert d.is_clear()
        assert d._duration_remaining == 10

    def test_load_dict_ignores_unknown_enum_values(self):
        """A doc with stale enum names (after a rename) loads cleanly
        — unknown entries are dropped, not raised."""
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.load_dict({
            "severities": {"WAT_TORNADO": "APOCALYPTIC"},
            "duration_remaining": 5,
        })
        assert d.is_clear()
        assert d._duration_remaining == 5


class TestTickAndTransition:
    @pytest.mark.asyncio
    async def test_tick_decrements_duration(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d._duration_remaining = 5
        await d.tick()
        assert d._duration_remaining == 4

    @pytest.mark.asyncio
    async def test_tick_does_not_transition_before_expiry(self):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.severities = {WeatherPatterns.FOG: WeatherSeverities.LIGHT}
        d._duration_remaining = 5
        await d.tick()
        assert d.severities == {WeatherPatterns.FOG: WeatherSeverities.LIGHT}


class TestTransitionInvariants:
    """``_roll_new_state`` enforces physical invariants: heavy wind
    disperses fog, precipitation absorbs standalone cloud."""

    def test_precipitation_removes_standalone_cloud(self):
        """Trigger rolls with monkeypatched random until we hit
        precipitation — then verify no stand-alone CLOUDY entry
        appears in the result (rain comes with cloud cover but the
        component is implicit, not double-reported)."""
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        # Force everything to roll by making random() return 0.0
        # (always under the chance threshold). Also need severities
        # to roll deterministically — just run it; the invariant
        # applies regardless of severity values.
        with patch("caldanai.lib.rpg.ambience.weather.random", return_value=0.0):
            d._roll_new_state(Seasons.LEAFGLOW)
        # After the invariant: if PRECIPITATION is active, CLOUDY
        # should not be a separate entry.
        if WeatherPatterns.PRECIPITATION in d.severities:
            assert WeatherPatterns.CLOUDY not in d.severities

    def test_heavy_wind_disperses_fog(self):
        """Force a roll where wind would be HEAVY or SEVERE; fog
        must not coexist."""
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        # Patch random to trigger both fog and wind, and shift
        # severities high for wind.
        with patch("caldanai.lib.rpg.ambience.weather.random", return_value=0.0):
            # Monkeypatch the severity roll to always return HEAVY.
            with patch(
                "caldanai.lib.rpg.ambience.weather._roll_severity",
                return_value=WeatherSeverities.HEAVY,
            ):
                d._roll_new_state(Seasons.FROSTFALL)
        # If wind was included and is HEAVY+, fog must be gone.
        if d.severities.get(WeatherPatterns.WIND) in (
            WeatherSeverities.HEAVY, WeatherSeverities.SEVERE
        ):
            assert WeatherPatterns.FOG not in d.severities


class TestLifecycle:
    @patch("caldanai.lib.rpg.ambience.weather.schedule_routine")
    def test_start_schedules_routine(self, mock_schedule):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.start(Seasons.BRIGHTBLOOM)
        mock_schedule.assert_called_once()
        # First positional arg is the channel_id.
        args = mock_schedule.call_args[0]
        assert args[0] == FAKE_CHANNEL_ID

    @patch("caldanai.lib.rpg.ambience.weather.cancel_routine")
    def test_stop_cancels_routine(self, mock_cancel):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.stop()
        mock_cancel.assert_called_once()
        args = mock_cancel.call_args[0]
        assert args[0] == FAKE_CHANNEL_ID

    @patch("caldanai.lib.rpg.ambience.weather.schedule_routine")
    def test_start_rolls_initial_state_when_empty(self, _):
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        # Empty + duration 0 = fresh daemon.
        assert d.is_clear()
        assert d._duration_remaining == 0
        d.start(Seasons.LEAFGLOW)
        # Duration should now be set (initial roll fired).
        assert d._duration_remaining > 0

    @patch("caldanai.lib.rpg.ambience.weather.schedule_routine")
    def test_start_preserves_loaded_state(self, _):
        """Loading from DB → calling start should NOT reroll, the
        state is already current."""
        d = WeatherDaemon(FAKE_CHANNEL_ID)
        d.load_dict({
            "severities": {"FOG": "LIGHT"},
            "duration_remaining": 45,
        })
        d.start(Seasons.FROSTFALL)
        # Loaded fog state preserved; duration preserved.
        assert d.severities == {WeatherPatterns.FOG: WeatherSeverities.LIGHT}
        assert d._duration_remaining == 45
