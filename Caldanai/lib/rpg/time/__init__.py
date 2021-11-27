import math
import asyncio
from typing import List, Callable, Optional, Dict, Tuple

from discord.ext import tasks

from Caldanai.lib.rpg.helpers.enums import TimesOfDay, Seasons


class GameClock:
	"""Tracks game time and date, and performs time related tasking."""

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
			self.name = self.function.__name__
			self.only_instance = only_instance

		def run(self):
			asyncio.create_task(self.function())

	def __init__(self, game_time: int = 0):
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

		:param routine: The function to add.
		:param seconds: How often the function should run, in seconds.
		:param run_once: Whether or not the function runs only once.
		:param only_instance: Whether or not to allow more than one of this routine to coexist. If True, then the new
			routine will attempt to replace the old routine.
		"""
		if seconds > 0:
			r = GameClock._Routine(self._ticks, routine, seconds, only_instance)
			if run_once:
				while only_instance and (match := self.find_routine(r.name)) and match[0] == self._tick_run_once:
					self._tick_run_once.pop(match[1])
				self._tick_run_once.append(r)
			else:
				while only_instance and (match := self.find_routine(r.name)) and match[0] == self._tick_routines:
					self._tick_routines.pop(match[1])
				self._tick_routines.append(r)

	def find_routine(self, name: str) -> (Optional[List['GameClock._Routine']], Optional[int]):
		"""
		Returns the list and index within which a given routine is found, or None if not found.

		:param name: The name of the function to remove.
		:return: A tuple with the containing List and index, or None and None.
		"""

		for i in range(len(self._tick_routines)):
			if name == self._tick_routines[i].name:
				return self._tick_routines, i

		for i in range(len(self._tick_run_once)):
			if name == self._tick_run_once[i].name:
				return self._tick_run_once, i

		return None, None

	def remove_routine(self, routine: Callable) -> bool:
		"""Removes the first instance of a routine from the game clock's internal lists."""
		lst, i = self.find_routine(routine.__name__)
		if lst and i >= 0:
			lst.pop(i)
			return True
		return False

	def get_time_components(self, seconds: int = None) -> (int, int, int):
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
			self,
			year: int = None,
			day: int = None,
			hour: int = None,
			minute: int = None,
			second: int = None
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
			s = (year - 1104) * self._seconds_per_year \
				+ day * self._seconds_per_day \
				+ hour * self._seconds_per_hour \
				+ minute * self._seconds_per_minute \
				+ second
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

	def get_sunrise_and_sunset(self) -> ('GameClock', 'GameClock'):
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
			TimesOfDay.NIGHT.name: (ssh + 1, ssm)
		}
		return

	def get_time_of_day(self) -> str:
		"""Returns the string form of the current time of day, such as 'night', 'noon', etc."""
		h, m, _ = self.get_time_components()

		times = [(k, v) for k, v in self._time_map.items() if v[0] < h or (v[0] == h and v[1] <= m)]
		if len(times) == 0:
			max_key = TimesOfDay.NIGHT.name
		else:
			max_key = max(times, key=lambda t: t[1])[0]
		return max_key.lower()

	def get_next_time(self) -> (TimesOfDay, int, int):
		"""Returns a tuple containing the next time of day after the current time, and the hour and the minute."""
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
		form = 'th'
		if day[-1] == '1' and (len(day) == 1 or (len(day) > 1 and day[0] != '1')):
			form = 'st'
		elif day[-1] == '2' and day[0] != '1':
			form = 'nd'
		elif day[-1] == '3' and day[0] != '1':
			form = 'rd'
		return f"{day}{form} of {self.get_season_string()}"

	def get_full_date(self) -> str:
		"""Returns the game clock's current date in full format."""
		return f"It is {self.get_time()} on the {self.get_date()} in the year {self.get_year()}."

	@tasks.loop(seconds=1)
	async def tick(self):
		"""Continuously updates the game clock's internal value and executes any pending tasks."""

		self._seconds += self.tick_speed
		self._ticks += 1

		h, m, s = self.get_time_components()
		if self.update_times_of_day() == {} or (h == 0 and m == 0 and s < 8):
			self.update_times_of_day()

		for i in range(len(self._tick_routines)):
			routine = self._tick_routines[i]
			if (self._ticks - routine.time_added) % routine.seconds == 0:
				routine.run()

		for i in range(len(self._tick_run_once) - 1, -1, -1):
			if (self._ticks - self._tick_run_once[i].time_added) % self._tick_run_once[i].seconds == 0:
				routine = self._tick_run_once.pop(i)
				routine.run()
