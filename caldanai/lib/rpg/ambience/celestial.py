"""Celestial daemon — per-game celestial-transition narration.

Today: emits sunrise / sunset narration at the two daily boundary
crossings. Named ``CelestialDaemon`` rather than ``SunriseSunset``
so the class stays the right home for planned expansion — sun
climbing toward zenith, moon rising / setting, "fully dark now"
kinds of lines — without needing another rename later. See
``project_ambience_kill_switches.md`` for the broader expansion
thread.

Owned by ``Game`` and scheduled on the game's clock via the module-
level façade in ``caldanai.lib.rpg.time``. Sibling to
``WeatherDaemon``: both are ambience subsystems that subscribe to
the clock and emit narrative text when a threshold is crossed.

Previously this logic lived inline in ``Game.do_ambience`` —
mixed with the random flavor-choice ambience roll and the
``enable_ambience`` kill-switch. That mixing made ``do_ambience``
three concerns in one method and bolted a ``_last_ambience_tick``
field onto ``Game`` that nothing else read. Moving it here:

- keeps ``Game.do_ambience`` focused on its remaining concern
  (the random flavor roll + kill-switch),
- gives a future weather-ambience plugin a clean seam to subscribe
  to the clock without tangling with sunrise narration,
- restores one-way ownership: the clock emits time-of-day
  transitions; ``Game`` holds the enable flag only.

Kill-switch
-----------
The daemon reads the effective celestial state each tick via
``Game.ambience_enabled("celestial")`` — i.e. the master
``enable_ambience`` ANDed with the per-subsystem
``enable_ambience_celestial`` flag. Either being ``False``
suppresses emission for this tick; the tracking window still
advances so re-enabling later in the day doesn't replay a
buffered crossing.

Once-per-crossing semantics
---------------------------
The daemon tracks ``_last_tick_seconds`` and fires sunrise
narration exactly when the tick's game-time first crosses the
day's sunrise boundary (``_last_tick_seconds < sunrise <=
game_time``) — same as the original inline check. Same for sunset.
"""

from typing import Optional

from caldanai.dispatcher import Dispatcher
from caldanai.lib.rpg.time import (
    schedule_routine,
    cancel_routine,
    GameClock,
)
from caldanai.logger import get_logger


_log = get_logger(__name__)


# Narration constants — extracted verbatim from the pre-refactor
# ``Game.do_ambience`` so output is byte-identical.
SUNRISE_NARRATION = (
    "The sky glows softly to the east as night gives way to day."
)
SUNSET_NARRATION = (
    "The crimson disc sinks slowly beyond the horizon, and darkness "
    "creeps across the land."
)


# Tick cadence — matches the original per-second ambience cadence so
# we don't miss the second a crossing occurs at time_scale > 1.
_TICK_INTERVAL_SECONDS = 1


class CelestialDaemon:
    """Emits sunrise and sunset narration once per day-boundary
    crossing, gated by the owning Game's ``enable_ambience`` flag."""

    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        # Set on :meth:`start` so we don't narrate a crossing that
        # happened before the daemon was listening.
        self._last_tick_seconds: Optional[int] = None

    # -- Lifecycle ------------------------------------------------------

    def start(self) -> None:
        """Snapshot the current clock time and schedule the per-tick
        emitter.

        Idempotent in two senses:

        - Scheduling is skip-if-found (``GameClock.add_routine``
          no-ops when the routine is already registered under the
          same qualname).
        - The tracking window (``_last_tick_seconds``) is only
          snapshotted on a fresh start — a no-op ``start()`` call
          from ``sync_ambience_daemons`` for an already-running
          daemon preserves progress toward the next boundary
          crossing, so a sibling-subsystem toggle can't silently
          erase a pending sunrise/sunset cue.
        """
        clock = GameClock.for_channel(self.channel_id)
        if clock is None:
            # No clock registered — nothing to tick against. Caller
            # is mis-sequencing (clock must register before start);
            # log and no-op rather than raise because this runs
            # during Game construction.
            _log.debug(
                "CelestialDaemon.start with no clock registered for "
                f"channel {self.channel_id}; skipping."
            )
            return
        # Already running → leave state alone. Re-snapshotting
        # ``_last_tick_seconds`` would erase the in-flight window
        # for the next boundary crossing.
        if clock.find_routine(self.tick.__qualname__)[0] is not None:
            _log.debug(
                f"CelestialDaemon.start on channel {self.channel_id}: "
                "already scheduled, preserving tracking window"
            )
            return
        self._last_tick_seconds = clock.get_seconds()
        schedule_routine(self.channel_id, self.tick, _TICK_INTERVAL_SECONDS)

    def stop(self) -> None:
        """Remove the tick routine from the clock. Called by
        ``remove_game`` (and by the ambience kill-switch admin
        command) so the daemon stops firing against a defunct or
        silenced channel."""
        cancel_routine(self.channel_id, self.tick)
        self._last_tick_seconds = None

    # -- Tick -----------------------------------------------------------

    async def tick(self) -> None:
        """One cadence tick. Check for a dawn or dusk crossing since
        the last tick and narrate it once, if ambience is enabled on
        the owning Game."""
        clock = GameClock.for_channel(self.channel_id)
        if clock is None:
            # Clock went away mid-flight (shouldn't happen — the
            # routine is removed by ``stop()`` before unregister).
            return

        game_time = clock.get_seconds()
        last = self._last_tick_seconds
        # Always advance the tracking window so a disabled-ambience
        # stretch doesn't buffer up a pent-up crossing to replay
        # when ambience is re-enabled mid-day.
        self._last_tick_seconds = game_time

        if last is None:
            # Defensive — daemon fired before start() seeded the
            # snapshot. Skip this tick; the next one has a window.
            return

        # Respect the same kill-switch that gated the pre-refactor
        # inline check. Option (a) per the refactor decision: disabling
        # ambience suppresses the clock-driven sunrise/sunset too.
        if not self._ambience_enabled():
            return

        sunrise, sunset = clock.get_sunrise_and_sunset()
        sunrise_s = sunrise.get_seconds()
        sunset_s = sunset.get_seconds()

        msg = ""
        if last < sunrise_s <= game_time:
            msg = SUNRISE_NARRATION
        elif last < sunset_s <= game_time:
            msg = SUNSET_NARRATION

        if msg:
            channel = self._channel()
            if channel is not None:
                Dispatcher.add(channel, msg)

    # -- Internals ------------------------------------------------------

    def _ambience_enabled(self) -> bool:
        """True if the owning Game has ambience enabled for the
        celestial subsystem (master AND celestial).  Reaches through
        ``Game.for_channel`` rather than holding a Game reference —
        mirrors ``WeatherDaemon._channel``'s back-reference-free
        pattern."""
        # Local import to avoid a circular at module load.
        from caldanai.lib.rpg import Game
        game = Game.for_channel(self.channel_id)
        # No game registered (teardown race) → treat as disabled.
        return bool(game and game.ambience_enabled("celestial"))

    def _channel(self):
        """Resolve the live Discord channel object for Dispatcher
        output."""
        # Local import to avoid a circular at module load.
        from caldanai.lib.rpg import Game
        game = Game.for_channel(self.channel_id)
        return game.channel if game else None
