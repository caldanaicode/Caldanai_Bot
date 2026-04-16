"""Tests for weather-dependent monster spawning.

Covers:
- ``MonsterPlugin.weather_partition`` defaults to ``ALL`` (spawns
  in any weather).
- ``get_random_monster(clock, weather=...)`` filters candidates by
  weather-partition overlap alongside the existing time filter.
- Weather-partition matching semantics for every pattern + the
  CLEAR sentinel.
- Concrete per-monster partitions (spirit, pixie) declared in
  plugin files remain correct (regression guard if someone edits
  those monsters later).
"""

from unittest.mock import MagicMock, patch

import pytest

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.spirit import Spirit
from caldanai.lib.rpg.creatures.monsters.pixie import Pixie
from caldanai.lib.rpg.creatures.monsters.skeleton import Skeleton
from caldanai.lib.rpg.helpers.enums import (
    TimePartitions, TimesOfDay, WeatherPatterns,
)


def _make_clock(time_of_day: str = "night"):
    clock = MagicMock()
    clock.get_time_of_day.return_value = time_of_day
    return clock


class TestWeatherPartitionDefault:
    def test_fresh_monster_spawns_in_any_weather(self):
        """Default ``weather_partition = ALL`` — a monster with no
        explicit weather tag should match every ``WeatherPatterns``
        value, including CLEAR."""
        m = Skeleton()  # not explicitly tagged for weather
        for pattern in (
            WeatherPatterns.CLEAR,
            WeatherPatterns.CLOUDY,
            WeatherPatterns.FOG,
            WeatherPatterns.PRECIPITATION,
            WeatherPatterns.WIND,
        ):
            assert bool(m.weather_partition & pattern), (
                f"Default-weather monster should match {pattern.name}, "
                f"but {m.weather_partition.name or m.weather_partition!r} "
                f"doesn't overlap."
            )


class TestTaggedMonsters:
    """Plugin-declared weather partitions — regression guards."""

    def test_spirit_matches_calm_weather(self):
        s = Spirit()
        assert bool(s.weather_partition & WeatherPatterns.CLEAR)
        assert bool(s.weather_partition & WeatherPatterns.CLOUDY)
        assert bool(s.weather_partition & WeatherPatterns.FOG)

    def test_spirit_avoids_rain_and_wind(self):
        s = Spirit()
        assert not bool(s.weather_partition & WeatherPatterns.PRECIPITATION)
        assert not bool(s.weather_partition & WeatherPatterns.WIND)

    def test_pixie_same_calm_weather_profile_as_spirit(self):
        """Both clear-weather creatures — rough conditions keep them
        tucked away. Locked in so a future retuning of one doesn't
        silently drift from the other without deliberation."""
        p = Pixie()
        s = Spirit()
        assert p.weather_partition == s.weather_partition


class TestGetRandomMonsterWeatherFilter:
    """``get_random_monster`` filters by the bitwise-AND of the
    weather arg and each candidate's ``weather_partition``."""

    @patch("caldanai.lib.rpg.creatures.monsters.PluginManager")
    def test_weather_arg_narrows_candidates(self, mock_pm):
        """When weather is passed, only monsters whose partition
        overlaps should be selected."""
        # Build three fake plugin classes with distinct partitions.
        class AnyWeather(MonsterPlugin):
            def __init__(self):
                super().__init__("any", "1d4", 1, 1, 10)
                self.time_partition = TimePartitions.CATHEMERAL
                self.weather_partition = WeatherPatterns.ALL

        class ClearOnly(MonsterPlugin):
            def __init__(self):
                super().__init__("clear", "1d4", 1, 1, 10)
                self.time_partition = TimePartitions.CATHEMERAL
                self.weather_partition = WeatherPatterns.CLEAR

        class StormOnly(MonsterPlugin):
            def __init__(self):
                super().__init__("storm", "1d4", 1, 1, 10)
                self.time_partition = TimePartitions.CATHEMERAL
                self.weather_partition = (
                    WeatherPatterns.PRECIPITATION | WeatherPatterns.WIND
                )

        mock_pm.LOADED_PLUGINS = {MonsterPlugin: [AnyWeather, ClearOnly, StormOnly]}

        # Clear weather: AnyWeather + ClearOnly are candidates.
        # StormOnly should NOT be picked.
        clock = _make_clock()
        for _ in range(30):
            result = MonsterPlugin.get_random_monster(
                clock, weather=WeatherPatterns.CLEAR,
            )
            assert result is not None
            assert not isinstance(result, StormOnly), (
                "Storm monster spawned during clear weather."
            )

    @patch("caldanai.lib.rpg.creatures.monsters.PluginManager")
    def test_no_weather_arg_matches_all(self, mock_pm):
        """Backward-compat: callers that don't supply weather
        should see the full candidate pool (weather filter is
        effectively disabled)."""
        class Restricted(MonsterPlugin):
            def __init__(self):
                super().__init__("restricted", "1d4", 1, 1, 10)
                self.time_partition = TimePartitions.CATHEMERAL
                self.weather_partition = WeatherPatterns.FOG

        mock_pm.LOADED_PLUGINS = {MonsterPlugin: [Restricted]}

        clock = _make_clock()
        # Without a weather arg, the restricted monster should still
        # be available — the filter defaults to ALL, which overlaps
        # with every partition.
        result = MonsterPlugin.get_random_monster(clock)
        assert isinstance(result, Restricted)

    @patch("caldanai.lib.rpg.creatures.monsters.PluginManager")
    def test_returns_none_when_no_candidates_match_weather(self, mock_pm):
        class FogOnly(MonsterPlugin):
            def __init__(self):
                super().__init__("fog", "1d4", 1, 1, 10)
                self.time_partition = TimePartitions.CATHEMERAL
                self.weather_partition = WeatherPatterns.FOG

        mock_pm.LOADED_PLUGINS = {MonsterPlugin: [FogOnly]}

        clock = _make_clock()
        result = MonsterPlugin.get_random_monster(
            clock, weather=WeatherPatterns.CLEAR,
        )
        assert result is None

    @patch("caldanai.lib.rpg.creatures.monsters.PluginManager")
    def test_time_filter_composes_with_weather_filter(self, mock_pm):
        """Both filters must pass. A monster that matches weather
        but not time is still excluded."""
        class NightFog(MonsterPlugin):
            def __init__(self):
                super().__init__("nightfog", "1d4", 1, 1, 10)
                self.time_partition = TimePartitions.NOCTURNAL
                self.weather_partition = WeatherPatterns.FOG

        mock_pm.LOADED_PLUGINS = {MonsterPlugin: [NightFog]}

        # Daytime + fog → time filter rejects, despite weather match.
        day_clock = _make_clock(time_of_day="noon")
        result = MonsterPlugin.get_random_monster(
            day_clock, weather=WeatherPatterns.FOG,
        )
        assert result is None

        # Night + fog → both filters pass.
        night_clock = _make_clock(time_of_day="night")
        result = MonsterPlugin.get_random_monster(
            night_clock, weather=WeatherPatterns.FOG,
        )
        assert isinstance(result, NightFog)


class TestWeatherPatternsALL:
    """The new ``ALL`` convenience flag should include every pattern
    so it's a safe default for monsters."""

    def test_all_covers_every_single_bit(self):
        for pattern in (
            WeatherPatterns.CLEAR,
            WeatherPatterns.CLOUDY,
            WeatherPatterns.FOG,
            WeatherPatterns.PRECIPITATION,
            WeatherPatterns.WIND,
        ):
            assert pattern in WeatherPatterns.ALL
            assert bool(WeatherPatterns.ALL & pattern)
