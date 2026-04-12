from asyncio import Event, Queue

from caldanai.lib.bot import Bot


class BotState:
    def __init__(self):
        self._shutdown_event = Event()
        self._command_queue = Queue()
        self._bot_queue = Queue()
        self._bot: Bot = None

    def set_shutdown(self):
        self._shutdown_event.set()

    def should_restart(self):
        return not self._shutdown_event.is_set()

    async def put_command(self, cmd: str):
        await self._command_queue.put(cmd)

    async def get_command(self):
        return await self._command_queue.get()

    async def put_bot(self, bot: Bot):
        await self._bot_queue.put(bot)

    async def get_bot(self):
        bot = self._bot
        if (not bot or (bot and bot.is_closed())) and self.should_restart():
            bot = await self._bot_queue.get()
            self._bot = bot
        return bot
