import re
from queue import Queue
from typing import List, Tuple, Union

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
    def _fence_regions(message: str) -> List[Tuple[int, int]]:
        """Return ``[(start, end_exclusive)]`` byte ranges that are
        inside a code fence (between an opening ```````
        line and its matching closer, exclusive on both ends so the
        fence-marker lines themselves are NOT in the region — only the
        content between them).

        Used to flag in-fence ``\\n`` positions as last-resort split
        candidates so the packer prefers between-fence boundaries
        (keeping each fence atomic) and only cuts inside a fence when
        nothing else fits in the window.
        """
        regions: List[Tuple[int, int]] = []
        in_fence = False
        content_start = 0
        pos = 0
        for line in message.split("\n"):
            line_end = pos + len(line)
            if line.lstrip().startswith("```"):
                if not in_fence:
                    in_fence = True
                    # Region starts AFTER this line's trailing \n.
                    content_start = line_end + 1
                else:
                    in_fence = False
                    # Region ends BEFORE this line.
                    if content_start < pos:
                        regions.append((content_start, pos))
            pos = line_end + 1  # account for the \n we split on
        if in_fence:
            # Unclosed fence — region runs to end of message.
            if content_start < len(message):
                regions.append((content_start, len(message)))
        return regions

    @staticmethod
    def _split_candidates(
        message: str, sep: str
    ) -> Tuple[List[int], List[int], List[int]]:
        """Pre-compute three tiers of split candidates for the packer.

        - ``preferred``: positions immediately after a run of two or
          more ``sep`` characters (blank-line boundaries) that fall
          OUTSIDE any fence. The chunk ends at the position; the
          next chunk starts there too — leading whitespace from the
          blank run is absorbed by the strip pass below.
        - ``acceptable``: positions immediately after a single ``sep``
          OUTSIDE any fence. Used when no preferred candidate exists
          in the window.
        - ``last_resort``: positions after a single ``sep`` INSIDE a
          fence. Used only when the other two tiers are empty in the
          window, so each fence stays atomic in the typical case and
          the packer falls back to current line-cut behavior on
          oversize fences (with the fence-balance post-process
          fixing close/reopen).

        Each list is sorted ascending. The packer scans them right-
        to-left to find the rightmost candidate ≤ window_end.
        """
        fence_regions = Dispatcher._fence_regions(message)

        def _in_fence(pos: int) -> bool:
            return any(start <= pos < end for start, end in fence_regions)

        preferred: List[int] = []
        for m in re.finditer(r"\n\n+", message):
            cut = m.end()  # one past the last \n in the run
            if not _in_fence(cut):
                preferred.append(cut)

        acceptable: List[int] = []
        last_resort: List[int] = []
        sep_len = len(sep)
        idx = 0
        while True:
            found = message.find(sep, idx)
            if found < 0:
                break
            cut = found + sep_len
            if _in_fence(cut):
                last_resort.append(cut)
            else:
                acceptable.append(cut)
            idx = cut

        return preferred, acceptable, last_resort

    @staticmethod
    def _pick_split(
        candidates_tiered: Tuple[List[int], List[int], List[int]],
        pos: int,
        window_end: int,
    ) -> int:
        """Return the rightmost split position in ``(pos, window_end]``,
        preferring earlier tiers. Falls back to ``window_end`` (a hard
        cut) when no candidate exists in any tier — preserves the
        original splitter's behavior for separator-free input."""
        for tier in candidates_tiered:
            # Walk right-to-left; first one in window wins.
            for cand in reversed(tier):
                if cand <= pos:
                    break
                if cand <= window_end:
                    return cand
        return window_end

    @staticmethod
    def split_message(message: str, sep: str = "\n", keep_sep: bool = False, limit: int = 1900) -> Tuple[str]:
        """
        Splits a string into a tuple of strings at every separator nearest to a character limit.

        Group-aware splitting (2026-05-02). Three tiers of candidate
        boundaries, preferring earlier tiers within each packing
        window:

        1. **Blank-line boundaries** — ``\\n\\n+`` outside any code
           fence. Treats each blank-line-separated paragraph (a
           combat-output block, a multi-line table, a header + body
           pair) as a unit and breaks between them.
        2. **Single-line boundaries** — ``\\n`` outside any code fence.
           Used when no blank-line boundary exists in the window.
        3. **In-fence single-line boundaries** — ``\\n`` inside a fence.
           Last-resort, used only when the other two tiers have no
           candidate in the window. Keeps fences atomic except when a
           fence alone exceeds the limit.

        Code-fence post-process is unchanged: when a chunk leaves a
        ``````` block unclosed (only possible when a
        fence alone exceeded the limit and was line-split internally
        via tier 3), the chunk is capped with a closing
        ``````` and the next chunk is prefixed with
        `````<lang>`` so Discord renders each chunk as
        a complete code block.

        :param message: The string to split.
        :param sep: The separator to split on. Default is a new line character.
        :param keep_sep: Specifies whether to add the separator back into the split string after splitting.
        :param limit: The maximum number of characters to allow per split.
            Fence close/reopen markers (``"\\n```"`` +
            ``"```<lang>\\n"``, up to ~20 chars) are
            deducted from this so the emitted chunk stays under the
            target, not the raw-split chunk.
        :return: A tuple of strings.
        """

        if message is None or len(message) == 0:
            return ()
        if len(message) <= limit:
            return (message,)

        # Reserve headroom for a potential fence-close / reopen pair
        # ONLY when the input actually contains a code fence.
        has_fences = "```" in message
        fence_reserve = 20 if has_fences else 0
        effective_limit = max(1, limit - fence_reserve)

        candidates_tiered = Dispatcher._split_candidates(message, sep)

        raw_chunks: Tuple[str, ...] = ()
        i = 0
        while i < len(message):
            remaining = len(message) - i
            if remaining < effective_limit:
                raw_chunks += (message[i:],)
                break

            window_end = i + effective_limit
            cut = Dispatcher._pick_split(candidates_tiered, i, window_end)

            chunk = message[i:cut]
            if not keep_sep:
                # Strip trailing separators — for tier-1 (blank-line)
                # cuts this drops the run of \n at the boundary; for
                # tier-2 / tier-3 it drops the single trailing \n.
                chunk = chunk.rstrip(sep)
            raw_chunks += (chunk,)
            i = cut

        # Post-process: close/reopen any code fences that straddle a
        # chunk boundary so each emitted chunk renders as a complete
        # Discord code block on its own. With group-aware splitting
        # this typically only fires when a single fence exceeded the
        # limit and was tier-3 split internally.
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
