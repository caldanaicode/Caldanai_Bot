from queue import Queue
from typing import Union, Tuple, Dict

from discord import User, Member, TextChannel, Guild, Embed, File, HTTPException
from discord.ext import tasks
from discord.ext.commands import Context

from Caldanai.Logger import stdout


class Dispatcher:
	queue: Queue = Queue(-1)

	class Message:
		"""
		Container class for message data.
		"""

		def __init__(
				self,
				channel: Union[User, Member, TextChannel, Guild],
				text: Union[str, Tuple[str], None] = None,
				embed: Union[Embed, None] = None,
				file: Union[File, None] = None
		):
			self.channel = channel
			self.text = text
			self.embed = embed
			self.file = file

	@classmethod
	def add_message(cls, message: Message):
		"""
		Enqueues a message to the dispatcher.

		:param message: Message object to send.
		"""
		if not cls.queue.empty():
			last_msg: cls.Message = cls.queue.queue[-1]
			if isinstance(last_msg.channel, type(message.channel)) and last_msg.channel.id == message.channel.id and \
					last_msg.file is None and last_msg.embed is None and message.embed is None and message.file is None \
					and len(last_msg.text) + len(message.text) + 1 < 2000:
				last_msg.text += f"\n{message.text}"
				stdout("Message grouped successfully!")
			else:
				cls.queue.put(message)
		else:
			cls.queue.put(message)

	@classmethod
	def add(
			cls,
			channel: Union[User, Member, TextChannel, Guild],
			text: Union[str, Tuple[str], None] = None,
			embed: Embed = None,
			file: File = None
	):
		"""
		Enqueues a message to the dispatcher.

		:param channel: The User, Member, TextChannel, or Guild to which the message will be sent.
		:param text: Optional message to send. Limit of 2000 characters.
		:param embed: Optional Embed to send.
		:param file: Optional File to send.
		"""
		if isinstance(channel, Context):
			m = cls.Message(channel.channel, text, embed, file)
		elif isinstance(channel, (User, Member, TextChannel, Guild)):
			m = cls.Message(channel, text, embed, file)
		else:
			stdout(f"Unrecognized channel type: {type(channel)}")
			return
		cls.add_message(m)

	@staticmethod
	def split_message(message: str, sep: str = '\n', keep_sep: bool = False, limit: int = 1900) -> Tuple[str]:
		"""
		Splits a string into a tuple of strings at every separator nearest to a character limit.

		:param message: The string to split.
		:param sep: The separator to split on. Default is a new line character.
		:param keep_sep: Specifies whether or not to add the separator back into the split string after splitting.
		:param limit: The maximum number of characters to allow per split.
		:return: A tuple of strings.
		"""

		result: Tuple[str] = ()
		if message is None or len(message) == 0:
			return result
		elif len(message) <= limit:
			result = (message,)
		else:
			i = 0
			while i < len(message):
				if len(message) - i < limit:
					m = message[i:]
					result += (m,)
					i += len(m)
				else:
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
		message: Dispatcher.Message = Dispatcher.queue.get()
		# context, message, embed, file = Dispatcher.queue.get()
		try:
			if isinstance(message.text, (str, Tuple)) or message.text is None:
				if message.text is None or len(message.text) <= 2000:
					await message.channel.send(message.text, embed=message.embed, file=message.file)
				elif isinstance(message.text, Tuple):
					for msg in message.text:
						await message.channel.send(msg)
						count += 1
				else:
					stdout(f'Message length was too long: {len(message.text)} characters.')

		except HTTPException as e:
			msg = f'HTTP Exception'
			if e.code == 429:
				msg += f' -- Message blocked due to rate limiting.'
				if 'Retry-After' in e.response.headers.keys():
					msg += f" Retry after {e.response.headers['Retry-After']} seconds."

			elif e.code == 400:
				msg += f' -- Message returned a bad format error.'
			else:
				msg += e.text

			stdout(msg)
		count += 1


send.start()
