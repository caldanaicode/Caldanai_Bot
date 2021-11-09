import math

from discord.ext import tasks


class GameClock:
	def __init__(self, game_time: float = 0):
		self._hours = game_time

		# How many game-hours pass per real hour. 1 = real-time, >1 is faster, (0, 1) is slower. 0 = time paused.
		self._time_scale = 4  # 4 means 1 real hour = 4 game-hours.

		self._seconds_per_hour = 3600
		self._minutes_per_hour = 60
		self._hours_per_day = 24
		self._days_per_season = 90
		self._seasons_per_year = 4
		self.tick_speed = self._time_scale / self._seconds_per_hour

	def get_time_components(self, hours: float = None) -> (int, int, int):
		if hours is None:
			hours = self._hours

		h = math.floor(hours) % 24
		m = (hours - math.floor(hours)) * 60
		s = (m - math.floor(m)) * 60
		return h, math.floor(m) % 60, math.floor(s) % 60

	def get_day(self):
		return math.floor(self._hours / 24) % 360

	def get_day_of_season(self):
		return self.get_day() % self._days_per_season

	def get_season(self):
		return math.floor(self._hours / self._hours_per_day / self._days_per_season) % 4

	def get_year(self):
		return 1104 + math.floor(self._hours / (self._hours_per_day * self._days_per_season * self._seasons_per_year))

	def get_daylight_length(self, day: int = None):
		if day is None:
			day = self.get_day()

		# return 35 / 3 + (7 / 3 * math.sin(2 * math.pi * (day - 80) / 360))  # 80 is vernal equinox
		return 35 / 3 + (7 / 3 * math.sin(2 * math.pi * (day + 80) / 360))    # The vernal equinox is now year start
		# return 3.95 * math.sin(math.pi * day / 180 - 2 * math.pi / 3) + 12.25

	def get_night_length(self, day: int = None):
		if day is None:
			day = self.get_day()

		return 24 - self.get_daylight_length(day)

	def get_hours(self, year: int = None, day: int = None, hour: int = None, minute: int = None, second: int = None):
		if year is not None and day is not None and hour is not None and minute is not None and second is not None:
			h = (year - 1104) * self._seasons_per_year * self._days_per_season
			h += day * self._hours_per_day
			h += hour
			h += minute / self._minutes_per_hour
			h += second / self._seconds_per_hour
			return h

		return self._hours

	def set_date_time(self, year: int, day: int, hour: int, minute: int, second: int):
		self._hours = self.get_hours(year, day, hour, minute, second)

	def set_date(self, year: int, day: int):
		h, m, s = self.get_time_components()
		self.set_date_time(year, day, h, m, s)

	def set_time(self, hour: int, minute: int, second: int):
		self.set_date_time(self.get_year(), self.get_day(), hour, minute, second)

	def get_sunrise_and_sunset(self) -> ('GameClock', 'GameClock'):
		hours = self._hours
		half_daylight = self.get_daylight_length() / 2
		dawn = GameClock(hours)
		dusk = GameClock(hours)
		h, m, s = self.get_time_components(half_daylight)
		dawn.set_time(12 - h, 60 - m, 60 - s)
		dusk.set_time(12 + h, 0 + m, 0 + s)
		return dawn, dusk

	def get_time_of_day(self):
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

	def get_season_string(self, season: int = None):
		seasons = ['Brightbloom', 'Solstime', 'Leafglow', 'Frostfall']

		if season is None:
			season = self.get_season()

		return seasons[season]

	def get_time(self):
		h, m, _ = self.get_time_components()
		return f"{h:02d}:{m:02d}"

	def get_date(self):
		day = f"{self.get_day_of_season() + 1}"
		form = 'th'
		if day[-1] == '1' and (len(day) == 1 or (len(day) > 1 and day[0] != '1')):
			form = 'st'
		elif day[-1] == '2' and day[0] != '1':
			form = 'nd'
		elif day[-1] == '3' and day[0] != '1':
			form = 'rd'
		return f"{day}{form} of {self.get_season_string()}"

	def get_full_date(self):
		return f"It is {self.get_time()} on the {self.get_date()} in the year {self.get_year()}."

	@tasks.loop(seconds=1)
	async def tick(self):
		self._hours += self.tick_speed
