import math
import asyncio
from typing import List, Callable, Optional, Dict, Tuple

from discord.ext import tasks

from caldanai.lib.rpg.helpers.enums import TimesOfDay, Seasons
from caldanai.logger import get_logger


_log = get_logger(__name__)


class GameClock:
    """Tracks game time and date, and performs time related tasking.

    Per-channel lookup
    ------------------
    Each ``Game`` owns one ``GameClock``. Downstream subsystems
    (monsters, weather, ambience, dungeon daemons) look up the clock
    for a given Discord channel via :meth:`for_channel` — or,
    preferably, the module-level ``get_time_of_day(channel_id)`` /
    ``schedule_routine(channel_id, …)`` façade functions which expose
    a narrow read/write surface without handing out the full clock
    object.

    There is no separate channel→clock registry: :meth:`for_channel`
    resolves the owning ``Game`` via ``Game.for_channel(channel_id)``
    and returns its ``game_clock``. ``Game._channel_routes`` is the
    single source of truth for channel ownership; clock access is
    derived. Registration / unregistration of the clock happens
    transparently with ``Game.register_channel`` /
    ``Game.unregister_channel``.

    The clock itself has no back-reference to its game, preserving
    one-way ownership: ``Game → GameClock``, not the reverse.
    """

    @classmethod
    def for_channel(cls, channel_id: int) -> "Optional[GameClock]":
        """Returns the ``GameClock`` for the game on ``channel_id``,
        or ``None`` if no game is active on that channel. Callers
        that only need to *read* time state should prefer the module-
        level façade functions (``get_time_of_day`` etc.) — this
        direct accessor is for subsystems that legitimately need to
        schedule routines or hold a reference across ticks.

        Shim over ``Game.for_channel(channel_id).game_clock``. The
        ``Game`` import is deferred to the call body because the
        ``caldanai.lib.rpg`` package imports ``GameClock`` at module
        load, so a top-level import here would cycle."""
        # Deferred to avoid a circular at module load — same pattern
        # the ambience daemons use.
        from caldanai.lib.rpg import Game
        game = Game.for_channel(channel_id)
        return game.game_clock if game is not None else None

    class _Routine:
        """GameClock's internal representation of tasks for use in the tick loop."""

        def __init__(self, time_added: int, function: Callable, seconds: int, only_instance: bool = False):
            """
            Initialize a new GameClock Routine.

            :param time_added: The tick-time at which this routine is created. Tick-time is the seconds since the
                game clock started.
            :param function: The function to execute upon timeout.
            :param seconds: The number of seconds before execution.
            """
            self.function = function
            self.seconds = int(max(0, seconds))
            self.time_added = time_added
            # Use ``__qualname__`` not ``__name__`` so bound methods
            # on different classes/instances with the same method
            # name don't collide in the routine registry. Without
            # this, ``WeatherDaemon.tick`` and
            # ``CelestialDaemon.tick`` both register under
            # ``"tick"``, and ``only_instance=True`` silently evicts
            # one when the other gets added — only the last one
            # wins, and the clock never drives both.
            # Plain functions have ``__qualname__ == __name__`` as
            # their qualname, so non-method callers are unaffected.
            self.name = getattr(function, "__qualname__", function.__name__)
            self.only_instance = only_instance

        def run(self):
            if self.seconds > 1:
                _log.debug(f"Game routine running: {self.name}")
            asyncio.create_task(self.function())

    def __init__(self, game_time: int = 0, channel_id: "Optional[int]" = None):
        # ``channel_id`` identifies the owning ``Game`` for the
        # per-game logging context — stamped on every tick so log
        # lines from routines scheduled on this clock carry the
        # channel id automatically. Defaults to ``None`` for
        # standalone instantiation (tests, utilities) where no
        # channel scope makes sense.
        self._channel_id = channel_id
        self._seconds = game_time
        self._ticks = 0

        # How many game-hours pass per real hour. 1 = real-time, >1 is faster, (0, 1) is slower. 0 = time paused.
        self.time_scale = 4  # 4 means 1 real hour = 4 game-hours.

        self._seconds_per_year = 31104000
        self._seconds_per_season = 7776000
        self._seconds_per_day = 86400
        self._seconds_per_hour = 3600
        self._seconds_per_minute = 60
        self._minutes_per_hour = 60
        self._hours_per_day = 24
        self._days_per_season = 90
        self._days_per_year = 360
        self._seasons_per_year = 4
        self._tick_routines: List[GameClock._Routine] = []
        self._tick_run_once: List[GameClock._Routine] = []
        self._time_map: Dict[str, Tuple[int, int]] = {}

        self.tick_speed = self.time_scale

    def __add__(self, other):
        if isinstance(other, GameClock):
            return GameClock(self._seconds + other._seconds)

        if isinstance(other, (int, float, complex)):
            return GameClock(self._seconds + int(other))

        return None

    def __sub__(self, other):
        if isinstance(other, GameClock):
            return GameClock(self._seconds - other._seconds)

        if isinstance(other, (int, float, complex)):
            return GameClock(self._seconds - int(other))

        return None

    def __eq__(self, other):
        if isinstance(other, GameClock):
            return self._seconds == other._seconds

        if isinstance(other, (int, float, complex)):
            return self._seconds == other

        raise TypeError(f"Unable to compare GameClock instance with {type(other)}.")

    def __ge__(self, other):
        if isinstance(other, GameClock):
            return self._seconds >= other._seconds

        if isinstance(other, (int, float, complex)):
            return self._seconds >= other

    def __gt__(self, other):
        if isinstance(other, GameClock):
            return self._seconds > other._seconds

        if isinstance(other, (int, float, complex)):
            return self._seconds > other

    def __le__(self, other):
        if isinstance(other, GameClock):
            return self._seconds <= other._seconds

        if isinstance(other, (int, float, complex)):
            return self._seconds <= other

    def __lt__(self, other):
        if isinstance(other, GameClock):
            return self._seconds < other._seconds

        if isinstance(other, (int, float, complex)):
            return self._seconds < other

    def add_routine(self, routine: Callable, seconds: int, run_once: bool = False, only_instance: bool = True) -> None:
        """
        Adds a function to the game clock's internal lists.

        With ``only_instance=True`` (the default), this is a
        **skip-if-found** operation: if a routine with the same
        qualname is already registered in the matching list, the
        call is a no-op. The previous implementation used to evict
        the old entry and append a fresh one, which silently reset
        the routine's ``time_added`` phase anchor (and, via the
        daemon ``start()`` paths that drive this, reset
        per-daemon tracking state like ``_last_tick_seconds``).
        Skip-if-found avoids that side-effect — callers who want
        to genuinely restart or change the interval should
        ``remove_routine`` first, then add.

        :param routine: The function to add.
        :param seconds: How often the function should run, in seconds.
        :param run_once: Whether or not the function runs only once.
        :param only_instance: When True (default), skip the add if
            a same-qualname routine is already registered. When
            False, always append (duplicates coexist).
        """

        if seconds <= 0:
            return
        r = GameClock._Routine(self._ticks, routine, seconds, only_instance)
        routines = self._tick_run_once if run_once else self._tick_routines

        if only_instance:
            lst, idx = self.find_routine(r.name)
            if lst is routines:
                _log.debug(
                    f"Routine `{r.name}` already registered (index {idx}, "
                    f"{routines[idx].seconds}s); skipping add"
                )
                return

        routines.append(r)
        _log.debug(
            f"Added {'run_once' if run_once else 'recurring'} game routine "
            f"`{r.name}` with timer of {seconds} seconds"
        )

    def find_routine(self, name: str) -> Tuple[Optional[List["GameClock._Routine"]], Optional[int]]:
        """
        Returns the list and index within which a given routine is found, or None if not found.

        :param name: The name of the function to remove.
        :return: A tuple with the containing List and index, or None and None.
        """

        _log.debug(f"Seeking routine `{name}`")
        for i in range(len(self._tick_routines)):
            if name == self._tick_routines[i].name:
                _log.debug(
                    f"Routine `{name}` found in recurring list at index {i}"
                )
                return self._tick_routines, i

        for i in range(len(self._tick_run_once)):
            if name == self._tick_run_once[i].name:
                _log.debug(
                    f"Routine `{name}` found in run-once list at index {i}"
                )
                return self._tick_run_once, i

        _log.debug(f"Routine `{name}` not found")
        return None, None

    def remove_routine(self, routine: Callable) -> bool:
        """Removes the first instance of a routine from the game clock's internal lists.

        Keyed by ``__qualname__`` so bound methods on different
        classes (``WeatherDaemon.tick`` vs
        ``CelestialDaemon.tick``) target the right entry
        instead of colliding on the bare method name.
        """
        name = getattr(routine, "__qualname__", routine.__name__)
        lst, i = self.find_routine(name)
        if lst and i >= 0:
            lst.pop(i)
            _log.debug(f"{name} removed from game clock")
            return True
        return False

    def get_time_components(self, seconds: int = None) -> Tuple[int, int, int]:
        """
        Gets the hour, minute, and second components of a given time value.

        :param seconds: The total number of game-seconds elapsed since the clock began.
        :return: A tuple containing hour, minute, and second values.
        """
        if seconds is None:
            seconds = self._seconds

        s = seconds % self._seconds_per_minute
        m = int(seconds / self._seconds_per_minute) % self._minutes_per_hour
        h = int(seconds / self._seconds_per_hour) % self._hours_per_day
        return h, m, s

    def get_day(self):
        """Returns the game clock's current day of the year."""
        return int(self._seconds / self._seconds_per_day) % self._days_per_year

    def get_day_of_season(self):
        """Returns the game clock's current day of the season."""
        return self.get_day() % self._days_per_season

    def get_season(self):
        """Returns the game clock's current season as a number."""
        return int(self._seconds / self._seconds_per_season) % self._seasons_per_year

    def get_year(self):
        """Returns the game clock's current year."""
        return 1104 + int(self._seconds / self._seconds_per_year)

    def get_daylight_length(self, day: int = None) -> float:
        """
        Returns the length of daylight for a given day of the current year, or the current day if none is provided.

        :param day: The nth day of the year.
        :return: A whole and fractional value indicating the number of hours of daylight.
        """
        if day is None:
            day = self.get_day()

        return 35 / 3 + 7 / 3 * math.sin(math.pi * (day + 8.213210701) / 180)  # The vernal equinox is now year start

    def get_night_length(self, day: int = None):
        """
        Returns the length of the night for a given day of the year, or the current day is none is provided.

        :param day: The nth day of the year.
        :return: A whole and fractional value indicating the number of hours of night.
        """
        if day is None:
            day = self.get_day()

        return 24 - self.get_daylight_length(day)

    def get_seconds(
        self, year: int = None, day: int = None, hour: int = None, minute: int = None, second: int = None
    ) -> int:
        """
        Returns the internal representation of a given time, or the current time if none is provided.

        :param year: The year component.
        :param day: The day component.
        :param hour: The hour component.
        :param minute: The minute component.
        :param second: The second component.
        :return: An integer value representing the game clock's time.
        """

        if year is not None and day is not None and hour is not None and minute is not None and second is not None:
            s = (
                (year - 1104) * self._seconds_per_year
                + day * self._seconds_per_day
                + hour * self._seconds_per_hour
                + minute * self._seconds_per_minute
                + second
            )
            return s

        return self._seconds

    def set_date_time(self, year: int, day: int, hour: int, minute: int, second: int) -> None:
        """
        Sets the game clock's internal value according to the provided game time information.

        :param year: The year to set.
        :param day: The day of the year to set.
        :param hour: The hour to set.
        :param minute: The minute to set.
        :param second: The second to set.
        """
        self._seconds = self.get_seconds(year, day, hour, minute, second)

    def set_date(self, year: int, day: int) -> None:
        """
        Sets the game clock's internal value to match the provided date.

        :param year: The year to set.
        :param day: The day to set.
        """
        h, m, s = self.get_time_components()
        self.set_date_time(year, day, h, m, s)

    def set_time(self, hour: int, minute: int, second: int) -> None:
        """
        Sets the game clock's internal value to match the provided time.

        :param hour: The hour to set.
        :param minute: The minute to set.
        :param second: The second to set.
        """
        self.set_date_time(self.get_year(), self.get_day(), hour, minute, second)

    def get_sunrise_and_sunset(self) -> Tuple["GameClock", "GameClock"]:
        """Returns a tuple containing the sunrise and sunset game clocks for the game's current day."""
        seconds = self._seconds
        half_daylight = int(self._seconds_per_hour * self.get_daylight_length() / 2)
        dawn = GameClock(game_time=seconds)
        dusk = GameClock(game_time=seconds)
        noon = 12 * self._seconds_per_hour
        h, m, s = self.get_time_components(half_daylight)
        ds = noon - h * self._seconds_per_hour - m * self._seconds_per_minute - s
        dawn.set_time(*self.get_time_components(ds))
        ds = noon + h * self._seconds_per_hour + m * self._seconds_per_minute + s
        dusk.set_time(*self.get_time_components(ds))
        return dawn, dusk

    def get_moon_phase(self) -> str:
        """Returns the moon's current phase as a string."""
        return "Not yet implemented"

    def update_times_of_day(self) -> None:
        """Updates the internal time map dictionary for the current day."""

        sunrise, sunset = self.get_sunrise_and_sunset()
        srh, srm, srs = sunrise.get_time_components()
        ssh, ssm, sss = sunset.get_time_components()

        self._time_map = {
            TimesOfDay.DAWN.name: (srh, srm),
            TimesOfDay.MORNING.name: (srh + 1, srm),
            TimesOfDay.NOON.name: (12, 0),
            TimesOfDay.AFTERNOON.name: (13, 0),
            TimesOfDay.EVENING.name: (ssh - 2, ssm),
            TimesOfDay.DUSK.name: (ssh, ssm),
            TimesOfDay.NIGHT.name: (ssh + 1, ssm),
        }
        return

    def get_time_of_day(self) -> str:
        """Returns the string form of the current time of day, such as 'night', 'noon', etc."""
        if not self._time_map:
            self.update_times_of_day()
        h, m, _ = self.get_time_components()

        times = [(k, v) for k, v in self._time_map.items() if v[0] < h or (v[0] == h and v[1] <= m)]
        if len(times) == 0:
            max_key = TimesOfDay.NIGHT.name
        else:
            max_key = max(times, key=lambda t: t[1])[0]
        return max_key.lower()

    def get_next_time(self) -> Tuple[TimesOfDay, int, int]:
        """Returns a tuple containing the next time of day after the current time, and the hour and the minute."""
        if not self._time_map:
            self.update_times_of_day()
        h, m, _ = self.get_time_components()

        times = [(k, v) for k, v in self._time_map.items() if v[0] > h or (v[0] == h and v[1] > m)]
        if len(times) == 0:
            min_tuple = (TimesOfDay.DAWN.name, *self._time_map[TimesOfDay.DAWN.name])
        else:
            min_key = min(times, key=lambda t: t[1])[0]
            min_tuple = (min_key, *self._time_map[min_key])
        return min_tuple

    def get_season_string(self, season: int = None) -> str:
        """
        Returns the name of the given season, or the current season if none is provided.
        :param season: An integer representing the season to retrieve.

        :return: The name of the season.
        """

        season = season or self.get_season()

        return Seasons(season).name.title()

    def get_tick_time(self) -> int:
        """Returns the number of seconds since the game clock last started."""
        return self._ticks

    def get_time(self) -> str:
        """Returns the game clock's current time in the hh:mm format."""
        h, m, _ = self.get_time_components()
        return f"{h:02d}:{m:02d}"

    def get_date(self) -> str:
        """Returns the game clock's current date in the 'day of season' format."""
        day = f"{self.get_day_of_season() + 1}"
        form = "th"
        if day[-1] == "1" and (len(day) == 1 or (len(day) > 1 and day[0] != "1")):
            form = "st"
        elif day[-1] == "2" and day[0] != "1":
            form = "nd"
        elif day[-1] == "3" and day[0] != "1":
            form = "rd"
        return f"{day}{form} of {self.get_season_string()}"

    def get_full_date(self) -> str:
        """Returns the game clock's current date in full format."""
        return f"It is {self.get_time()} on the {self.get_date()} in the year {self.get_year()}."

    @tasks.loop(seconds=1)
    async def tick(self):
        """Continuously updates the game clock's internal value and
        executes any pending tasks.

        Every tick runs inside a ``channel_log_context`` bound to
        this clock's owning game — routines scheduled on this clock
        (monster actions, weather daemon updates, ambience, combat
        pipeline composer) emit logs stamped with the channel id
        automatically, no call-site changes required."""

        from caldanai.log_context import channel_log_context

        with channel_log_context(self._channel_id):
            self._seconds += self.tick_speed
            self._ticks += 1

            h, m, s = self.get_time_components()
            if not self._time_map or (h == 0 and m == 0 and s < 8):
                self.update_times_of_day()

            for i in range(len(self._tick_routines)):
                routine = self._tick_routines[i]
                if (self._ticks - routine.time_added) % routine.seconds == 0:
                    routine.run()

            for i in range(len(self._tick_run_once) - 1, -1, -1):
                if (self._ticks - self._tick_run_once[i].time_added) % self._tick_run_once[i].seconds == 0:
                    routine = self._tick_run_once.pop(i)
                    routine.run()


# ---------------------------------------------------------------------------
# Module-level façade — narrow read/write surface keyed by channel_id.
#
# These functions are the *preferred* way for subsystems (monsters,
# weather daemons, ambience, dungeon logic) to interact with a game's
# clock. They hand out only the concrete piece of information the
# caller needs, rather than the whole clock object — which means
# downstream code can't accidentally mutate scheduling, tick state,
# or any other internal. Callers that genuinely need to schedule
# routines use the explicit ``schedule_routine`` / ``cancel_routine``
# functions below.
#
# All functions accept a ``channel_id`` (the Game's primary Discord
# channel id) and return ``None`` (for read functions) or quietly
# no-op (for scheduling functions) when no clock is registered for
# that channel — so callers operating in test / pre-spawn contexts
# don't have to defensively guard every access.
# ---------------------------------------------------------------------------


# -- Read surface -----------------------------------------------------------


def get_time_of_day(channel_id: int) -> Optional[str]:
    """Current time-of-day label (``"dawn"``, ``"morning"``, etc.)
    for the game on ``channel_id``, or ``None`` if no game is
    registered for that channel."""
    clock = GameClock.for_channel(channel_id)
    return clock.get_time_of_day() if clock else None


def get_time_components(channel_id: int) -> Optional[Tuple[int, int, int]]:
    """Current ``(hour, minute, second)`` components for the game on
    ``channel_id``, or ``None`` if no game is registered for that
    channel."""
    clock = GameClock.for_channel(channel_id)
    return clock.get_time_components() if clock else None


def get_next_time(channel_id: int) -> Optional[Tuple[str, int, int]]:
    """Next time-of-day boundary as ``(name, hour, minute)`` for the
    game on ``channel_id``, or ``None`` if no game is registered for
    that channel."""
    clock = GameClock.for_channel(channel_id)
    return clock.get_next_time() if clock else None


def get_seconds(channel_id: int) -> Optional[int]:
    """Total game-seconds elapsed for the game on ``channel_id``, or
    ``None`` if no game is registered for that channel."""
    clock = GameClock.for_channel(channel_id)
    return clock.get_seconds() if clock else None


# -- Scheduling surface -----------------------------------------------------


def schedule_routine(
    channel_id: int,
    fn: Callable,
    seconds: int,
    run_once: bool = False,
    only_instance: bool = True,
) -> bool:
    """Register ``fn`` to run every ``seconds`` game-seconds on the
    clock for ``channel_id``. Returns ``True`` on success, ``False``
    if no game is registered for that channel. Thin wrapper over
    ``GameClock.add_routine`` so callers don't need a clock reference."""
    clock = GameClock.for_channel(channel_id)
    if clock is None:
        return False
    clock.add_routine(fn, seconds, run_once=run_once, only_instance=only_instance)
    return True


def cancel_routine(channel_id: int, fn: Callable) -> bool:
    """Remove ``fn`` from the scheduled routines on the clock for
    ``channel_id``. Returns the underlying ``remove_routine`` result
    (``True`` if removed), or ``False`` if no game is registered for
    that channel."""
    clock = GameClock.for_channel(channel_id)
    if clock is None:
        return False
    return clock.remove_routine(fn)
