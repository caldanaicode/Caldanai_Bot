"""Per-game logging context — ``ContextVar``-backed so log lines
emitted inside a specific game's scope carry the channel id
automatically, without each call site threading it through.

The design question the memo left open was "how do we avoid
rewriting every ``_log.debug`` call to pass channel_id"; the
answer is: don't. Log records get enriched at emit time by
reading a :class:`contextvars.ContextVar` that was stamped once
at the execution entry point (``GameClock.tick``, a discord.py
command invocation, etc.). Anything emitted outside a
game-scoped context has the var at its default (``None``) and
the handler format falls back to the pre-existing ``[name]``
shape — zero impact on Dispatcher / main / db logs that aren't
owned by one specific game.

Readers:

- :class:`caldanai.logger.MongoHandler` — reads
  :data:`channel_id_var` and appends ``(channel_id)`` to the
  logger-name bracket in stdout output plus a ``channel_id``
  field on the Mongo log document.

Writers:

- :class:`caldanai.lib.rpg.time.GameClock` — wraps each
  per-second ``tick`` body so every routine it runs (monster
  hooks, weather daemon, ambience, etc.) inherits the context.
- :class:`caldanai.lib.bot.Bot.on_command` — stamps the channel
  id when a cog command fires. Discord.py runs each invocation
  in its own task, so task-local ``ContextVar`` storage keeps
  concurrent commands isolated without a manual reset.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Optional


# Sentinel ``None`` means "no game context on the stack" — the
# formatter falls back to the legacy bracket shape in that case.
channel_id_var: ContextVar[Optional[int]] = ContextVar(
    "channel_id", default=None,
)


@contextmanager
def channel_log_context(channel_id: Optional[int]) -> Iterator[None]:
    """Set :data:`channel_id_var` for the duration of the with-block.

    Idempotent nesting: re-entering with the same (or a different)
    channel id is fine — the token-based reset restores the
    previous value on exit, so a nested game-scoped block inside
    another doesn't corrupt the outer context.

    Passing ``None`` explicitly scopes OUT of a game context for
    the block, which is occasionally useful inside a Game-scoped
    coroutine that calls into a cross-game helper whose logs
    shouldn't be misattributed.
    """
    token = channel_id_var.set(channel_id)
    try:
        yield
    finally:
        channel_id_var.reset(token)
