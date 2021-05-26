from datetime import datetime
from queue import Queue
from typing import Union, Tuple

from discord import User, Member, TextChannel, Guild, Embed, File, HTTPException
from discord.ext import tasks

from Caldanai.Logger import stdout


class Dispatcher:
	queue: Queue = Queue(-1)

	@classmethod
	def add(
			cls,
			context: Union[User, Member, TextChannel, Guild],
			message: Union[str, Tuple[str], None] = None,
			embed: Embed = None,
			file: File = None
	):
		"""
		Enqueues a message to the dispatcher.

		:param context: The User, Member, TextChannel, or Guild to which the message will be sent.
		:param message: Optional message to send. Limit of 2000 characters.
		:param embed: Optional Embed to send.
		:param file: Optional File to send.
		"""
		cls.queue.put((context, message, embed, file))

	@staticmethod
	def split_message(message: str, sep: str = '\n', keep_sep: bool = False) -> Tuple[str]:
		"""
		Splits a string into a tuple of strings at every separator nearest to a 2000 character limit.

		:param message: The string to split.
		:param sep: The separator to split on. Default is a new line character.
		:param keep_sep: Specifies whether or not to add the separator back into the split string after splitting.
		:return: A tuple of strings.
		"""
		limit = 2000
		result: Tuple[str] = ()
		if message is None or len(message) == 0:
			return result
		elif len(message) <= 2000:
			result = (message,)
		else:
			i = 0
			while i < len(message):
				m = message[i: i + limit].rsplit(sep, 1)
				result += (m[0] + sep if keep_sep else '',)
				i += len(m[0]) + len(sep)
		return result


@tasks.loop(seconds=1)
async def send():
	"""
	Sends a batch of messages to discord's API every second.
	"""

	count = 0
	while not Dispatcher.queue.empty() and count < 10:
		context, message, embed, file = Dispatcher.queue.get()
		try:
			if isinstance(message, str) or message is None:
				if message is None or len(message) <= 2000:
					await context.send(message, embed=embed, file=file)
				elif isinstance(message, Tuple):
					for msg in message:
						await context.send(msg)
						count += 1

		except HTTPException as e:
			msg = f'{datetime.now().strftime("%m-%d-%Y %H:%M:%S")}: HTTP Exception'
			if e.code == 429:
				msg += f' -- Message blocked due to rate limiting.'
				if 'Retry-After' in e.response.headers.keys():
					msg += f" Retry After {e.response.headers['Retry-After']} seconds."

			elif e.code == 400:
				msg += f' -- Message returned a bad format error.'
			else:
				msg += e.text

			stdout(msg)
		count += 1


send.start()
