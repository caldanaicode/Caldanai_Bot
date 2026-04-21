from queue import Queue
from typing import Union, Tuple

from discord import User, Member, TextChannel, Guild, Embed, File, HTTPException
from discord.ext import tasks
from discord.ext.commands import Context

from caldanai.logger import get_logger


_log = get_logger(__name__)


class Dispatcher:
    queue: Queue = Queue(-1)
    flush: bool = False

    class Message:
        """
        Container class for message data.
        """

        def __init__(
            self,
            channel: Union[User, Member, TextChannel, Guild],
            text: Union[str, Tuple[str], None] = None,
            embed: Union[Embed, None] = None,
            file: Union[File, None] = None,
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
        if cls.flush:
            return

        if not cls.queue.empty():
            last_msg: cls.Message = cls.queue.queue[-1]
            if (
                isinstance(last_msg.channel, type(message.channel))
                and last_msg.channel.id == message.channel.id
                and last_msg.file is None
                and last_msg.embed is None
                and message.embed is None
                and message.file is None
                and last_msg.text is not None
                and message.text is not None
                and isinstance(last_msg.text, str)
                and isinstance(message.text, str)
                and len(last_msg.text) + len(message.text) + 1 < 2000
            ):
                last_msg.text += f"\n{message.text}"
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
        file: File = None,
    ):
        """
        Enqueues a message to the dispatcher.

        :param channel: The User, Member, TextChannel, or Guild to which the message will be sent.
        :param text: Optional message to send. Limit of 2000 characters.
        :param embed: Optional Embed to send.
        :param file: Optional File to send.
        """
        if cls.flush:
            return

        ch = (
            channel
            if isinstance(channel, (User, Member, TextChannel, Guild))
            else channel.channel if isinstance(channel, Context) else None
        )

        if ch is None:
            _log.error(f"Dispatcher.add() - Unrecognized channel type: {type(channel)}")
            return

        cls.add_message(cls.Message(ch, text, embed, file))

    @staticmethod
    def _open_fence_lang(text: str) -> Union[str, None]:
        """Return the language of a code fence left open at the end of
        ``text``, or ``None`` if no fence is open.

        Walks line by line. A line whose first non-whitespace token is
        ```` ``` ```` opens a fence (capturing any language suffix like
        ``diff`` / ``ansi``); the next such line closes it. This mirrors
        how Discord / CommonMark interpret code blocks. The language of
        a still-open fence lets us reopen it in the next split chunk.
        """
        open_lang: Union[str, None] = None
        for line in text.split("\n"):
            stripped = line.lstrip()
            if stripped.startswith("```"):
                if open_lang is None:
                    open_lang = stripped[3:].strip()
                else:
                    open_lang = None
        return open_lang

    @staticmethod
    def split_message(message: str, sep: str = "\n", keep_sep: bool = False, limit: int = 1900) -> Tuple[str]:
        """
        Splits a string into a tuple of strings at every separator nearest to a character limit.

        Code-fence-aware: if a split chunk leaves a ```` ``` ```` block
        unclosed, the chunk is capped with a closing ```` ``` ```` and
        the next chunk is prefixed with ```` ```<lang> ```` so Discord
        renders each chunk as a complete code block instead of spilling
        raw text outside the fence on the second half.

        :param message: The string to split.
        :param sep: The separator to split on. Default is a new line character.
        :param keep_sep: Specifies whether to add the separator back into the split string after splitting.
        :param limit: The maximum number of characters to allow per split.
            Fence close/reopen markers (``"\\n```"`` + ``"```<lang>\\n"``,
            up to ~20 chars) are deducted from this so the emitted chunk
            stays under the target, not the raw-split chunk.
        :return: A tuple of strings.
        """

        if message is None or len(message) == 0:
            return ()
        if len(message) <= limit:
            return (message,)

        # Reserve headroom for a potential fence-close / reopen pair
        # ONLY when the input actually contains a code fence. ``` plus
        # up to ~8-char language name plus two newlines fits
        # comfortably inside 20 characters. Skipping the reserve on
        # fence-free input keeps the splitter's behavior identical to
        # pre-fence logic for plain text (important for callers
        # depending on tight-limit splits — small-limit unit tests
        # especially).
        has_fences = "```" in message
        fence_reserve = 20 if has_fences else 0
        effective_limit = max(1, limit - fence_reserve)

        raw_chunks: Tuple[str, ...] = ()
        i = 0
        while i < len(message):
            if len(message) - i < effective_limit:
                raw_chunks += (message[i:],)
                i = len(message)
            else:
                m = message[i : i + effective_limit].rsplit(sep, 1)
                if len(m) == 1:
                    raw_chunks += (m[0],)
                    i += len(m[0])
                else:
                    raw_chunks += (m[0] + sep if keep_sep else m[0],)
                    i += len(m[0]) + len(sep)

        # Post-process: close/reopen any code fences that straddle a
        # chunk boundary so each emitted chunk renders as a complete
        # Discord code block on its own.
        result: Tuple[str, ...] = ()
        pending_prefix = ""
        for raw in raw_chunks:
            chunk = pending_prefix + raw
            pending_prefix = ""
            open_lang = Dispatcher._open_fence_lang(chunk)
            if open_lang is not None:
                # Close the open fence at the end of this chunk and
                # queue the same-language reopener for the next chunk.
                trailing_nl = "" if chunk.endswith("\n") else "\n"
                chunk = f"{chunk}{trailing_nl}```"
                pending_prefix = (
                    f"```{open_lang}\n" if open_lang else "```\n"
                )
            result += (chunk,)
        return result


@tasks.loop(seconds=1)
async def send():
    """
    Sends a batch of messages to discord's API every second.
    """

    count = 0
    while not Dispatcher.queue.empty() and count < 10:
        message: Dispatcher.Message = Dispatcher.queue.get()
        try:
            if isinstance(message.text, Tuple):
                for msg in message.text:
                    await message.channel.send(msg)
                    count += 1
            elif message.text is None or (isinstance(message.text, str) and len(message.text) <= 2000):
                await message.channel.send(message.text, embed=message.embed, file=message.file)
            elif isinstance(message.text, str):
                # Auto-split oversized text so multi-player combat
                # tables (hydra + 4 attackers easily clears 2k chars)
                # don't get silently dropped. The first chunk carries
                # the embed / file; subsequent chunks are text-only.
                _log.debug(
                    f"Splitting oversized message ({len(message.text)} chars) "
                    "into send-safe chunks."
                )
                chunks = Dispatcher.split_message(message.text, keep_sep=True)
                for idx, chunk in enumerate(chunks):
                    if idx == 0:
                        await message.channel.send(
                            chunk, embed=message.embed, file=message.file,
                        )
                    else:
                        await message.channel.send(chunk)
                    count += 1

        except HTTPException as e:
            msg = "HTTP Exception"
            if e.status == 429:
                msg += " -- Message blocked due to rate limiting."
                if "Retry-After" in e.response.headers.keys():
                    msg += f" Retry after {e.response.headers['Retry-After']} seconds."

            elif e.status == 400:
                msg += " -- Message returned a bad format error."
            elif e.status == 524:
                msg += " -- Cloudflare Timeout Error 524."
            else:
                msg += e.text

            _log.error(f"{msg}\n\tError Code: {e.code}\n\tError Status: {e.status}")
        count += 1
