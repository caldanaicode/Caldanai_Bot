"""Regression tests for ``Bot.on_command_error`` hint behavior.

Before the 2026-04-21 fix, ``BadArgument`` and
``MissingRequiredArgument`` were silently swallowed — user
invocations with typo'd arguments produced no feedback, no log,
no trail. After the fix, the invoker gets a one-liner hint
nudging them at ``$help <command>``, with a per-user-per-error
cooldown so fast typo sessions can't spam the channel.

Tests pin:

- A ``BadArgument`` from a command with no custom ``.error``
  handler triggers a hint.
- A ``MissingRequiredArgument`` does the same.
- Repeat within ``_ERROR_HINT_COOLDOWN_SECONDS`` is suppressed.
- A different exception class from the same user gets its own
  hint (per-class keying).
- ``CommandOnCooldown`` stays silent (would be noisy on
  rapid retries).
- ``CommandNotFound`` stays silent (too broad — any non-command
  message starting with the prefix would echo).
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from discord.ext.commands import (
    BadArgument,
    CommandNotFound,
    CommandOnCooldown,
    MissingRequiredArgument,
)


def _make_bot():
    """Instantiate a ``Bot`` without going through the DB-touching
    ``__init__``. We only need the methods under test plus the
    ``_error_hint_cooldowns`` dict and ``_ERROR_HINT_COOLDOWN_SECONDS``
    class attr."""
    from caldanai.lib.bot import Bot
    bot = Bot.__new__(Bot)
    bot._error_hint_cooldowns = {}
    return bot


def _make_ctx(user_id: int = 42, cmd_name: str = "equip", prefix: str = "$"):
    ctx = SimpleNamespace(
        author=SimpleNamespace(id=user_id),
        command=SimpleNamespace(qualified_name=cmd_name),
        prefix=prefix,
    )
    return ctx


class TestHintResponseFires:
    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_bad_argument_sends_hint(self, mock_dispatch):
        bot = _make_bot()
        ctx = _make_ctx(user_id=42, cmd_name="equip")
        exc = BadArgument("Converting to 'int' failed")
        await bot.on_command_error(ctx, exc)
        mock_dispatch.add.assert_called_once()
        _sent_ctx, sent_msg = mock_dispatch.add.call_args.args
        assert "didn't quite catch" in sent_msg.lower()
        assert "$help equip" in sent_msg

    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_missing_required_argument_sends_hint(self, mock_dispatch):
        bot = _make_bot()
        ctx = _make_ctx(user_id=42, cmd_name="unequip")
        exc = MissingRequiredArgument(MagicMock(name="item_or_placement"))
        await bot.on_command_error(ctx, exc)
        mock_dispatch.add.assert_called_once()
        _, sent_msg = mock_dispatch.add.call_args.args
        assert "$help unequip" in sent_msg

    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_hint_mentions_invoker(self, mock_dispatch):
        bot = _make_bot()
        ctx = _make_ctx(user_id=12345)
        await bot.on_command_error(ctx, BadArgument("x"))
        _, sent_msg = mock_dispatch.add.call_args.args
        assert "<@!12345>" in sent_msg


class TestHintCooldown:
    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_repeat_within_cooldown_is_silent(self, mock_dispatch):
        """A user triggering the same error class twice within the
        cooldown window gets one hint, not two."""
        bot = _make_bot()
        ctx = _make_ctx(user_id=42, cmd_name="equip")
        await bot.on_command_error(ctx, BadArgument("x"))
        await bot.on_command_error(ctx, BadArgument("y"))
        assert mock_dispatch.add.call_count == 1

    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_different_exception_class_bypasses_cooldown(self, mock_dispatch):
        """Cooldown key is ``(user_id, exc_class)`` — a different
        error class from the same user should still produce a hint,
        since the user's attempted fix might have introduced a new
        issue we want them to see."""
        bot = _make_bot()
        ctx = _make_ctx(user_id=42)
        await bot.on_command_error(ctx, BadArgument("x"))
        await bot.on_command_error(
            ctx, MissingRequiredArgument(MagicMock(name="p")),
        )
        assert mock_dispatch.add.call_count == 2

    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_different_user_bypasses_cooldown(self, mock_dispatch):
        bot = _make_bot()
        await bot.on_command_error(_make_ctx(user_id=42), BadArgument("x"))
        await bot.on_command_error(_make_ctx(user_id=99), BadArgument("x"))
        assert mock_dispatch.add.call_count == 2

    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_after_cooldown_window_hint_fires_again(self, mock_dispatch):
        """Same user, same error, but past the cooldown window —
        hint fires again so a genuine mistake later in the session
        isn't permanently silent."""
        bot = _make_bot()
        ctx = _make_ctx(user_id=42)
        await bot.on_command_error(ctx, BadArgument("x"))
        # Simulate the cooldown entry aging past the window.
        old_key = (42, "BadArgument")
        bot._error_hint_cooldowns[old_key] = datetime.now() - timedelta(
            seconds=bot._ERROR_HINT_COOLDOWN_SECONDS + 1,
        )
        await bot.on_command_error(ctx, BadArgument("y"))
        assert mock_dispatch.add.call_count == 2


class TestSilentErrorClasses:
    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_cooldown_stays_silent(self, mock_dispatch):
        """Echoing to the channel on every cooldown-blocked attempt
        would be noisier than the silence the user was annoyed by —
        keep ``CommandOnCooldown`` silent."""
        bot = _make_bot()
        ctx = _make_ctx()
        exc = CommandOnCooldown(MagicMock(), retry_after=5, type=MagicMock())
        await bot.on_command_error(ctx, exc)
        mock_dispatch.add.assert_not_called()

    @pytest.mark.asyncio
    @patch("caldanai.lib.bot.Dispatcher")
    async def test_command_not_found_stays_silent(self, mock_dispatch):
        """``CommandNotFound`` fires for any non-command chat that
        starts with the prefix — echoing back would produce noise
        on every stray ``$`` in conversation."""
        bot = _make_bot()
        ctx = _make_ctx()
        await bot.on_command_error(ctx, CommandNotFound("foo"))
        mock_dispatch.add.assert_not_called()
