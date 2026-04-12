from discord import Member
from caldanai import Event
from caldanai.logger import get_logger


_log = get_logger(__name__)


class DiscordConnectedEvent(Event):
    def __init__(self) -> None:
        super().__init__(__class__.__name__)


class DiscordDisconnectedEvent(Event):
    def __init__(self) -> None:
        super().__init__(__class__.__name__)


class BotReadyEvent(Event):
    def __init__(self) -> None:
        super().__init__(__class__.__name__)


class MemberUpdatedEvent(Event):
    def __init__(self, before: Member, after: Member) -> None:
        super().__init__(__class__.__name__, {"before": before, "after": after})
