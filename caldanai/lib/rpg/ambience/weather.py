"""Weather daemon — per-game weather state machine.

Owned by ``Game`` and scheduled on the game's clock via the module-
level façade in ``caldanai.lib.rpg.time``. The daemon holds a
``channel_id`` handle (not a Game reference) so it can live alongside
other future subsystems (weather combat modifiers, body temperature,
weather-filtered ambience) without widening anyone's surface area.

Weather state
-------------
Weather is a ``Dict[WeatherPatterns, WeatherSeverities]`` — each
active component (PRECIPITATION, WIND, FOG, CLOUDY) carries its
own severity. An empty dict is the "clear skies" state. This shape
lets us express heavy rain in light wind distinctly from heavy
wind driving a drizzle — both for narration and for per-component
combat modifiers in later work.

Transitions
-----------
When the remaining duration ticks to zero, the daemon rolls a new
state. Transition probabilities are weighted by:

- **Season** — FROSTFALL skews toward PRECIPITATION + WIND,
  BRIGHTBLOOM toward CLEAR, etc.
- **Current state** — gradual drift (CLEAR → CLOUDY → LIGHT rain)
  is more likely than a sudden jump (CLEAR → SEVERE storm).

Changes are announced to the game channel as narrative text, not
as raw state ("Dark clouds roll in from the west…" rather than
"weather = PRECIPITATION|CLOUDY MODERATE").

Persistence
-----------
``to_dict`` / ``from_dict`` round-trip the state so weather
survives bot restarts. Duration counts down in game-minutes so the
storm you started watching at bedtime is still going in the
morning (or petering out) depending on how long it was supposed
to last.
"""

from random import choice, randint, random
from typing import Dict, List, Optional, Tuple

from caldanai.dispatcher import Dispatcher
from caldanai.lib.rpg.helpers.enums import (
    Seasons,
    WeatherPatterns,
    WeatherSeverities,
)
from caldanai.lib.rpg.time import (
    schedule_routine,
    cancel_routine,
    get_seconds,
)
from caldanai.logger import get_logger


_log = get_logger(__name__)


# Seconds between weather daemon ticks. The daemon tracks remaining
# duration in game-minutes; a 60-second tick = one game-minute per
# tick at ``time_scale == 1`` (slower game clocks tick game-minutes
# less frequently, which is fine — the daemon decrements by one
# each fire regardless of scale).
_TICK_INTERVAL_SECONDS = 60

# Fallback duration window (in game-minutes) when rolling a new
# weather state. ~1 game-hour to ~8 game-hours. Individual roll
# logic can override by returning a specific duration from
# ``_roll_new_state``.
_DEFAULT_DURATION_MIN = 60
_DEFAULT_DURATION_MAX = 480


class WeatherDaemon:
    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        # Active components keyed by pattern. Empty dict = clear skies.
        self.severities: Dict[WeatherPatterns, WeatherSeverities] = {}
        # Remaining game-minutes until the next transition roll.
        self._duration_remaining: int = 0
        # Guard so we don't announce the initial state as a "change".
        self._announced_initial: bool = False
        # Listeners notified when weather transitions to a new state.
        # Each callback receives (old_patterns, new_patterns,
        # old_severities, new_severities). Used by Game to fan out
        # to room.static_objects' on_weather_change hooks. Direct
        # listener-list (rather than EventEmitter) keeps coupling
        # minimal — daemon doesn't import Game.
        self.transition_listeners: list = []

    # -- Public API -----------------------------------------------------

    @property
    def active_patterns(self) -> WeatherPatterns:
        """Union of all active pattern flags, or ``CLEAR`` if none
        are active. ``CLEAR`` is NOT OR'd onto a weather with active
        components — it's the explicit "no weather" state, useful for
        monster spawn filters to opt-in to clear-weather spawning."""
        if not self.severities:
            return WeatherPatterns.CLEAR
        # Start from a bare flag and OR active components only.
        result = WeatherPatterns(0)
        for p in self.severities:
            result |= p
        return result

    def is_clear(self) -> bool:
        return not self.severities

    def severity_of(self, pattern: WeatherPatterns) -> Optional[WeatherSeverities]:
        """Severity of a specific component, or ``None`` if the
        component isn't active. Combat hooks pull the wind severity
        independently from the precipitation severity this way."""
        return self.severities.get(pattern)

    def forecast(self, season: Seasons) -> str:
        """Best-effort weather forecast for the given season.
        Reads the seasonal weights and narrates the dominant likely
        components in almanac-style prose. Adds a small amount of
        inaccuracy (~20%) so the forecast occasionally lies — which
        is both realistic for an in-world almanac and saves players
        from treating it as an oracle.
        """
        weights = _seasonal_weights(season)
        lines: List[str] = []

        # Order: precipitation has more narrative weight than
        # background cloud cover, and wind is usually reported
        # alongside it. Fog is its own note.
        if weights["precipitation_chance"] >= 0.4:
            bias = weights["precipitation_severity_bias"]
            if bias >= 1:
                lines.append("Heavy rain seems likely.")
            else:
                lines.append("Rain is likely throughout the day.")
        elif weights["precipitation_chance"] >= 0.25:
            lines.append("Scattered showers are possible.")

        if weights["wind_chance"] >= 0.45:
            bias = weights["wind_severity_bias"]
            if bias >= 1:
                lines.append("Strong winds are expected.")
            else:
                lines.append("Winds will pick up.")

        if weights["fog_chance"] >= 0.2:
            lines.append("Fog may settle in the lower ground.")

        if weights["cloudy_chance"] >= 0.5 and not lines:
            lines.append("Cloudy skies are expected.")

        if not lines:
            lines.append("The skies should remain clear.")

        # ~20% chance of a small inaccuracy — swap one line with a
        # mildly-wrong sibling so a forecast isn't gospel. The old
        # books are only so reliable.
        if random() < 0.20 and lines:
            _scramble_forecast_line(lines)

        return " ".join(lines)

    def describe(self) -> str:
        """Player-facing description of the current weather. Used by
        ``$weather`` and by change announcements."""
        if self.is_clear():
            return "The sky is clear."

        parts: List[str] = []
        precip_sev = self.severities.get(WeatherPatterns.PRECIPITATION)
        wind_sev = self.severities.get(WeatherPatterns.WIND)
        fog_sev = self.severities.get(WeatherPatterns.FOG)
        cloud_sev = self.severities.get(WeatherPatterns.CLOUDY)

        if precip_sev:
            parts.append(_describe_precipitation(precip_sev, wind_sev))
        elif cloud_sev:
            parts.append(_describe_cloudy(cloud_sev))

        if fog_sev:
            parts.append(_describe_fog(fog_sev))

        if wind_sev and not precip_sev:
            # Wind-only descriptions read oddly when tacked onto rain
            # (already covered by the combined precip description).
            parts.append(_describe_wind(wind_sev))

        return " ".join(parts) if parts else "The sky is clear."

    # -- Lifecycle ------------------------------------------------------

    def start(self, season: Seasons) -> None:
        """Roll an initial state and schedule the tick loop. Called
        by ``Game`` after construction or restore."""
        if self._duration_remaining <= 0 and not self.severities:
            # Fresh daemon — roll an initial state without announcing
            # it (the game's "just started" context speaks for itself).
            self._roll_new_state(season)
            self._announced_initial = True
        schedule_routine(self.channel_id, self.tick, _TICK_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Remove the tick routine from the clock. Called by
        ``remove_game`` so the daemon stops firing against a defunct
        channel."""
        cancel_routine(self.channel_id, self.tick)

    async def tick(self):
        """One tick of the weather state machine. Called every
        minute of game-time (one minute per fire at time_scale=1)."""
        self._duration_remaining -= 1
        if self._duration_remaining > 0:
            return

        season = self._current_season()
        old_description = self.describe()
        old_patterns = self.active_patterns
        old_severities = dict(self.severities)
        self._roll_new_state(season)
        new_description = self.describe()
        new_patterns = self.active_patterns
        new_severities = dict(self.severities)

        if new_description != old_description:
            # Narrative announcement, not raw state. The describe()
            # output reads as prose, so we can ship it directly.
            Dispatcher.add(self._channel(), new_description)

        # Fan out to transition listeners regardless of description
        # change — listeners may care about severity-only changes
        # (e.g. light → moderate rain) even when the prose form
        # rounds to the same description.
        if (
            old_patterns != new_patterns
            or old_severities != new_severities
        ):
            for listener in list(self.transition_listeners):
                try:
                    listener(
                        old_patterns, new_patterns,
                        old_severities, new_severities,
                    )
                except Exception:
                    _log.exception(
                        "WeatherDaemon transition listener raised; "
                        "continuing with remaining listeners",
                    )

    # -- State rolls ----------------------------------------------------

    def _roll_new_state(self, season: Seasons) -> None:
        """Pick the next weather state. Weighted by season; gradual
        drift is more likely than big jumps. Sets ``self.severities``
        and ``self._duration_remaining`` in place."""
        # Start each roll from nothing; additively set components.
        # Transitions that hold "mostly clear" land here as empty.
        new_severities: Dict[WeatherPatterns, WeatherSeverities] = {}

        weights = _seasonal_weights(season)

        # Each component rolls independently — composable weather.
        # Order doesn't matter for the result.
        if random() < weights["cloudy_chance"]:
            new_severities[WeatherPatterns.CLOUDY] = _roll_severity(
                weights["cloudy_severity_bias"]
            )
        if random() < weights["precipitation_chance"]:
            new_severities[WeatherPatterns.PRECIPITATION] = _roll_severity(
                weights["precipitation_severity_bias"]
            )
            # Precipitation implies cloud cover — drop any stand-alone
            # cloud that would read weirdly next to rain.
            new_severities.pop(WeatherPatterns.CLOUDY, None)
        if random() < weights["wind_chance"]:
            new_severities[WeatherPatterns.WIND] = _roll_severity(
                weights["wind_severity_bias"]
            )
        if random() < weights["fog_chance"]:
            new_severities[WeatherPatterns.FOG] = _roll_severity(
                weights["fog_severity_bias"]
            )
            # Fog and strong wind don't coexist (wind disperses fog).
            if new_severities.get(WeatherPatterns.WIND) in (
                WeatherSeverities.HEAVY, WeatherSeverities.SEVERE,
            ):
                new_severities.pop(WeatherPatterns.FOG, None)

        self.severities = new_severities
        self._duration_remaining = randint(
            _DEFAULT_DURATION_MIN, _DEFAULT_DURATION_MAX
        )

    # -- Persistence ----------------------------------------------------

    def to_dict(self) -> dict:
        """Serialize for DB round-trip. Enum keys/values become their
        names so Mongo stores human-readable state."""
        return {
            "severities": {
                p.name: s.name for p, s in self.severities.items()
            },
            "duration_remaining": self._duration_remaining,
        }

    def load_dict(self, d: dict) -> None:
        """Restore state from a ``to_dict`` payload. Silently no-ops
        on missing / malformed entries so a schema addition doesn't
        brick old saves."""
        if not d:
            return
        try:
            sev = d.get("severities") or {}
            self.severities = {
                WeatherPatterns[p]: WeatherSeverities[s]
                for p, s in sev.items()
                if p in WeatherPatterns.__members__
                and s in WeatherSeverities.__members__
            }
            self._duration_remaining = int(d.get("duration_remaining", 0))
            # Loaded state is already the "current" state for the
            # game — don't announce it as a change when the first
            # tick fires.
            self._announced_initial = True
        except Exception as e:
            _log.error(f"Failed to load weather state: {e}")
            self.severities = {}
            self._duration_remaining = 0

    # -- Internals ------------------------------------------------------

    def _current_season(self) -> Seasons:
        """Reads the current season off the clock. Defaults to
        BRIGHTBLOOM if the clock can't be resolved (daemon running
        without a registered clock shouldn't happen, but defensive)."""
        # Local import to avoid a circular at module load.
        from caldanai.lib.rpg.time import GameClock
        clock = GameClock.for_channel(self.channel_id)
        if clock is None:
            return Seasons.BRIGHTBLOOM
        return Seasons(clock.get_season())

    def _channel(self):
        """Resolve the live Discord channel object for Dispatcher
        output. Reaches through the bot's channel-to-game map rather
        than holding a Game reference."""
        # Local import to avoid a circular at module load.
        from caldanai.lib.rpg import Game
        game = Game.for_channel(self.channel_id)
        return game.channel if game else None


# ---------------------------------------------------------------------------
# Seasonal weighting
# ---------------------------------------------------------------------------


def _seasonal_weights(season: Seasons) -> Dict[str, float]:
    """Per-season roll weights. Biases are integer "bumps" applied
    to each component's severity roll; positive bias favors heavier
    weather for that component in that season."""
    # Reasonable defaults; tune after playtest.
    if season == Seasons.BRIGHTBLOOM:  # spring
        return {
            "cloudy_chance": 0.50,
            "cloudy_severity_bias": 0,
            "precipitation_chance": 0.35,
            "precipitation_severity_bias": 0,
            "wind_chance": 0.30,
            "wind_severity_bias": 0,
            "fog_chance": 0.15,
            "fog_severity_bias": 0,
        }
    if season == Seasons.SOLSTIME:  # summer
        return {
            "cloudy_chance": 0.30,
            "cloudy_severity_bias": 0,
            "precipitation_chance": 0.25,
            "precipitation_severity_bias": 1,   # when it rains, it pours
            "wind_chance": 0.25,
            "wind_severity_bias": 0,
            "fog_chance": 0.05,
            "fog_severity_bias": -1,
        }
    if season == Seasons.LEAFGLOW:  # autumn
        return {
            "cloudy_chance": 0.55,
            "cloudy_severity_bias": 0,
            "precipitation_chance": 0.40,
            "precipitation_severity_bias": 0,
            "wind_chance": 0.45,
            "wind_severity_bias": 1,
            "fog_chance": 0.25,
            "fog_severity_bias": 1,
        }
    if season == Seasons.FROSTFALL:  # winter
        return {
            "cloudy_chance": 0.60,
            "cloudy_severity_bias": 0,
            "precipitation_chance": 0.40,
            "precipitation_severity_bias": 1,
            "wind_chance": 0.50,
            "wind_severity_bias": 1,
            "fog_chance": 0.20,
            "fog_severity_bias": 0,
        }
    # Fallback (shouldn't reach here — all four seasons enumerated).
    return {
        "cloudy_chance": 0.4,
        "cloudy_severity_bias": 0,
        "precipitation_chance": 0.3,
        "precipitation_severity_bias": 0,
        "wind_chance": 0.3,
        "wind_severity_bias": 0,
        "fog_chance": 0.1,
        "fog_severity_bias": 0,
    }


_SEVERITY_ROLL_TABLE: Tuple[WeatherSeverities, ...] = (
    WeatherSeverities.LIGHT,
    WeatherSeverities.LIGHT,
    WeatherSeverities.LIGHT,
    WeatherSeverities.MODERATE,
    WeatherSeverities.MODERATE,
    WeatherSeverities.HEAVY,
    WeatherSeverities.SEVERE,
)


def _roll_severity(bias: int) -> WeatherSeverities:
    """Roll a severity level, biased toward heavier outcomes if
    ``bias > 0`` or lighter if ``bias < 0``. Bias shifts the index
    into a weighted lookup table that favors LIGHT > MODERATE >
    HEAVY > SEVERE at baseline."""
    idx = randint(0, len(_SEVERITY_ROLL_TABLE) - 1) + bias
    idx = max(0, min(len(_SEVERITY_ROLL_TABLE) - 1, idx))
    return _SEVERITY_ROLL_TABLE[idx]


# ---------------------------------------------------------------------------
# Descriptors — narrative text for each component severity
# ---------------------------------------------------------------------------


def _describe_precipitation(
    precip: WeatherSeverities, wind: Optional[WeatherSeverities],
) -> str:
    """Precipitation description, flavored by any concurrent wind."""
    wind_heavy = wind in (WeatherSeverities.HEAVY, WeatherSeverities.SEVERE)
    if precip == WeatherSeverities.LIGHT:
        if wind_heavy:
            return "A thin rain is driven sideways on the wind."
        return "A light rain drifts down through the air."
    if precip == WeatherSeverities.MODERATE:
        if wind_heavy:
            return "Wind-driven rain hisses through the area."
        return "A steady rain falls across the area."
    if precip == WeatherSeverities.HEAVY:
        if wind_heavy:
            return "Heavy rain lashes the area in wind-driven sheets."
        return "Heavy rain drums steadily against the ground."
    if precip == WeatherSeverities.SEVERE:
        return "A torrential downpour hammers down with punishing force."
    return ""


def _describe_cloudy(severity: WeatherSeverities) -> str:
    if severity == WeatherSeverities.LIGHT:
        return "Thin clouds drift lazily overhead."
    if severity == WeatherSeverities.MODERATE:
        return "A blanket of cloud covers the sky."
    if severity == WeatherSeverities.HEAVY:
        return "Dark clouds press low against the sky."
    if severity == WeatherSeverities.SEVERE:
        return "An oppressive ceiling of black cloud roils overhead."
    return ""


def _describe_fog(severity: WeatherSeverities) -> str:
    if severity == WeatherSeverities.LIGHT:
        return "A faint mist softens the edges of everything."
    if severity == WeatherSeverities.MODERATE:
        return "Fog gathers, muffling sound and sight alike."
    if severity == WeatherSeverities.HEAVY:
        return "Thick fog smothers the area; nothing beyond arm's reach is clear."
    if severity == WeatherSeverities.SEVERE:
        return "An impossibly dense fog blots out the world."
    return ""


_FORECAST_WRONG_SWAPS = {
    "Heavy rain seems likely.": "Light showers are likely.",
    "Rain is likely throughout the day.": "The skies should remain clear.",
    "Scattered showers are possible.": "The skies should remain clear.",
    "Strong winds are expected.": "Light winds are expected.",
    "Winds will pick up.": "The air will remain still.",
    "Fog may settle in the lower ground.": "Visibility should be good.",
    "Cloudy skies are expected.": "Sunshine throughout the day.",
    "The skies should remain clear.": "Expect some cloud cover.",
}


def _scramble_forecast_line(lines: List[str]) -> None:
    """Replace a random line with its 'mildly wrong' sibling in place.
    Preserves list length and ordering; silently no-ops if no swap is
    defined for the chosen line."""
    idx = randint(0, len(lines) - 1)
    swap = _FORECAST_WRONG_SWAPS.get(lines[idx])
    if swap:
        lines[idx] = swap


def _describe_wind(severity: WeatherSeverities) -> str:
    if severity == WeatherSeverities.LIGHT:
        return "A gentle breeze stirs the air."
    if severity == WeatherSeverities.MODERATE:
        return "A steady wind moves across the landscape."
    if severity == WeatherSeverities.HEAVY:
        return "Strong gusts whip through the area."
    if severity == WeatherSeverities.SEVERE:
        return "A roaring gale tears across the land."
    return ""
