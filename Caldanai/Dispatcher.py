from queue import Queue
from typing import Union

from discord import User, Member, TextChannel, Guild
from discord.ext import tasks


class Dispatcher:
	queue: Queue = Queue(-1)

	@classmethod
	def add(cls, context: Union[User, Member, TextChannel, Guild], message: str):
		cls.queue.put((context, message))

	@classmethod
	@tasks.loop(seconds=1)
	async def send(cls):
		count = 0
		while not cls.queue.empty() and count < 5:
			context, message = cls.queue.get()
			context.send(message)
			count += 1


Dispatcher.send.start()
