import math
import asyncio
from typing import List, Callable, Optional

from discord.ext import tasks

from Caldanai.Logger import stdout


class GameClock:
	"""Tracks game time and date, and performs time related tasking."""

	class _Routine:
		"""GameClock's internal representation of tasks for use in the tick loop."""

		def __init__(self, time_added: int, function: Callable, seconds: int):
			"""
			Initialize a new GameClock Routine.

			:param time_added: The game clock's time at which this routine is created.
			:param function: The function to execute upon timeout.
			:param seconds: The number of seconds before execution.
			"""
			self.function = function
			self.seconds = int(max(0, seconds))
			self.time_added = time_added
			self.name = self.function.__name__

		def run(self):
			asyncio.create_task(self.function())

	def __init__(self, game_time: float = 0):
		self._hours = game_time
		self._ticks = 0

		# How many game-hours pass per real hour. 1 = real-time, >1 is faster, (0, 1) is slower. 0 = time paused.
		self.time_scale = 4  # 4 means 1 real hour = 4 game-hours.

		self._seconds_per_hour = 3600
		self._minutes_per_hour = 60
		self._hours_per_day = 24
		self._days_per_season = 90
		self._seasons_per_year = 4
		self._tick_routines: List[GameClock._Routine] = []
		self._tick_run_once: List[GameClock._Routine] = []

		self.tick_speed = self.time_scale / self._seconds_per_hour

	def add_routine(self, routine: Callable, seconds: int, run_once: bool = False) -> None:
		"""
		Adds a function to the game clock's internal lists.

		:param routine: The function to add.
		:param seconds: How often the function should run, in seconds.
		:param run_once: Whether or not the function runs only once.
		"""
		if seconds > 0:
			r = GameClock._Routine(self._ticks, routine, seconds)
			if run_once:
				self._tick_run_once.append(r)
			else:
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

	def remove_routine(self, routine: Callable):
		"""Removes the first instance of a routine from the game clock's internal lists."""
		lst, i = self.find_routine(routine.__name__)
		if lst and i:
			lst.pop(i)

	def get_time_components(self, hours: float = None) -> (int, int, int):
		"""
		Gets the hour, minute, and second components of a given time value.

		:param hours: The whole and fractional game hours that have elapsed.
		:return: A tuple containing hour, minute, and second values.
		"""
		if hours is None:
			hours = self._hours

		h = math.floor(hours) % 24
		m = (hours - math.floor(hours)) * 60
		s = (m - math.floor(m)) * 60
		return h, math.floor(m) % 60, math.floor(s) % 60

	def get_day(self):
		"""Returns the game clock's current day of the year."""
		return math.floor(self._hours / 24) % 360

	def get_day_of_season(self):
		"""Returns the game clock's current day of the season."""
		return self.get_day() % self._days_per_season

	def get_season(self):
		"""Returns the game clock's current season as a number."""
		return math.floor(self._hours / self._hours_per_day / self._days_per_season) % 4

	def get_year(self):
		"""Returns the game clock's current year."""
		return 1104 + math.floor(self._hours / (self._hours_per_day * self._days_per_season * self._seasons_per_year))

	def get_daylight_length(self, day: int = None) -> float:
		"""
		Returns the length of daylight for a given day of the current year, or the current day if none is provided.

		:param day: The nth day of the year.
		:return: A whole and fractional value indicating the number of hours of daylight.
		"""
		if day is None:
			day = self.get_day()

		# return 35 / 3 + (7 / 3 * math.sin(2 * math.pi * (day - 80) / 360))  # 80 is vernal equinox
		return 35 / 3 + (7 / 3 * math.sin(2 * math.pi * (day + 80) / 360))  # The vernal equinox is now year start

	def get_night_length(self, day: int = None):
		"""
		Returns the length of the night for a given day of the year, or the current day is none is provided.

		:param day: The nth day of the year.
		:return: A whole and fractional value indicating the number of hours of night.
		"""
		if day is None:
			day = self.get_day()

		return 24 - self.get_daylight_length(day)

	def get_hours(self, year: int = None, day: int = None, hour: int = None, minute: int = None, second: int = None) -> float:
		"""
		Returns the internal representation of a given time, or the current time if none is provided.

		:param year: The year component.
		:param day: The day component.
		:param hour: The hour component.
		:param minute: The minute component.
		:param second: The second component.
		:return: A whole and fractional value representing the game clock's time.
		"""

		if year is not None and day is not None and hour is not None and minute is not None and second is not None:
			h = (year - 1104) * self._seasons_per_year * self._days_per_season
			h += day * self._hours_per_day
			h += hour
			h += minute / self._minutes_per_hour
			h += second / self._seconds_per_hour
			return h

		return self._hours

	def set_date_time(self, year: int, day: int, hour: int, minute: int, second: int) -> None:
		"""
		Sets the game clock's internal value according to the provided game time information.

		:param year: The year to set.
		:param day: The day of the year to set.
		:param hour: The hour to set.
		:param minute: The minute to set.
		:param second: The second to set.
		"""
		self._hours = self.get_hours(year, day, hour, minute, second)

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
		hours = self._hours
		half_daylight = self.get_daylight_length() / 2
		dawn = GameClock(game_time=hours)
		dusk = GameClock(game_time=hours)
		h, m, s = self.get_time_components(half_daylight)
		dawn.set_time(12 - h, 60 - m, 60 - s)
		dusk.set_time(12 + h, 0 + m, 0 + s)
		return dawn, dusk

	def get_time_of_day(self) -> str:
		"""Returns the string form of the current time of day, such as 'night', 'noon', etc."""
		sunrise, sunset = self.get_sunrise_and_sunset()
		sr = sunrise.get_time_components()[0]
		ss = sunset.get_time_components()[0]
		hr = self.get_time_components()[0]

		if sr <= hr < sr + 1:
			return "dawn"
		if sr + 1 <= hr < 12:
			return "morning"
		if 12 <= hr < 13:
			return "noon"
		if 13 <= hr < ss - 2:
			return "afternoon"
		if ss - 2 <= hr < ss:
			return "evening"
		if ss <= hr < ss + 1:
			return "dusk"
		return "night"

	def get_season_string(self, season: int = None) -> str:
		"""
		Returns the name of the given season, or the current season if none is provided.
		:param season: An integer representing the season to retrieve.

		:return: The name of the season.
		"""
		seasons = ['Brightbloom', 'Solstime', 'Leafglow', 'Frostfall']

		if season is None:
			season = self.get_season()

		return seasons[season]

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

		self._hours += self.tick_speed
		self._ticks = self._ticks + 1

		for i in range(len(self._tick_routines)):
			routine = self._tick_routines[i]
			if (self._ticks - routine.time_added) % routine.seconds == 0:
				routine.run()

		for i in range(len(self._tick_run_once) - 1, -1, -1):
			if (self._ticks - self._tick_run_once[i].time_added) % self._tick_run_once[i].seconds == 0:
				routine = self._tick_run_once.pop(i)
				routine.run()
