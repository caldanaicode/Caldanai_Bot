"""Tests for the signal-handler installation in ``main.py``.

The installation itself is imperative plumbing (calls
``signal.signal`` for SIGINT/SIGTERM/SIGBREAK and captures the
event loop + state references in a closure), so tests focus on:

1. The installer tolerates the Windows vs Unix signal-set
   differences without raising — SIGTERM and SIGBREAK don't both
   exist on every platform, and ``signal.signal`` can fail for
   signals that aren't settable in a given runtime.
2. The registered handler routes to ``state._command_queue`` via
   ``loop.call_soon_threadsafe`` so the shutdown request lands on
   the queue ``cmd_loop`` is awaiting, and the same code path the
   console ``shutdown`` command uses fires identically.
"""

import signal as signal_mod
from unittest.mock import MagicMock, patch

import pytest

import main as main_mod


class TestInstallShutdownSignals:
    def test_registers_all_available_signals(self):
        """Every signal that exists on this platform should get a
        handler registered. Missing signals (e.g. SIGBREAK on
        Unix, SIGTERM in some Windows contexts) are silently
        skipped, not re-raised."""
        registered = {}

        def fake_signal(sig, handler):
            registered[sig] = handler

        loop = MagicMock()
        state = MagicMock()

        with patch("main.signal.signal", side_effect=fake_signal):
            main_mod._install_shutdown_signals(state, loop)

        # At minimum, SIGINT must be settable — it's the Ctrl+C
        # path and available on every supported platform.
        assert signal_mod.SIGINT in registered

    def test_oserror_on_one_signal_does_not_abort_others(self):
        """``signal.signal(SIGTERM, ...)`` can raise ``OSError`` on
        some Windows configurations. That failure must not prevent
        SIGINT / SIGBREAK from registering."""
        registered = {}

        def flaky_signal(sig, handler):
            if sig == signal_mod.SIGINT:
                raise OSError("simulated refusal")
            registered[sig] = handler

        loop = MagicMock()
        state = MagicMock()

        with patch("main.signal.signal", side_effect=flaky_signal):
            main_mod._install_shutdown_signals(state, loop)

        # SIGINT failed but any other defined signal on this
        # platform still got its handler.
        other_sigs = [
            getattr(signal_mod, n, None) for n in ("SIGTERM", "SIGBREAK")
        ]
        assert any(s in registered for s in other_sigs if s is not None)

    def test_handler_enqueues_shutdown_via_call_soon_threadsafe(self):
        """When the handler fires, it must schedule a ``"shutdown"``
        enqueue on the captured event loop via
        ``call_soon_threadsafe`` — NOT put directly onto the queue
        (asyncio queues aren't thread/signal-safe) and NOT via
        ``call_soon`` (the signal handler runs in a signal context,
        not on the event loop's thread, even on Windows where those
        happen to coincide)."""
        registered = {}

        def fake_signal(sig, handler):
            registered[sig] = handler

        loop = MagicMock()
        state = MagicMock()
        state._command_queue = MagicMock()

        with patch("main.signal.signal", side_effect=fake_signal):
            main_mod._install_shutdown_signals(state, loop)

        handler = registered[signal_mod.SIGINT]
        handler(signal_mod.SIGINT.value, None)

        loop.call_soon_threadsafe.assert_called_once()
        call_args = loop.call_soon_threadsafe.call_args.args
        # First arg is the callable to invoke on the loop.
        assert call_args[0] == state._command_queue.put_nowait
        # Remaining args are what's passed through to it.
        assert call_args[1] == "shutdown"

    def test_handler_tolerates_closed_event_loop(self):
        """If the signal fires after the event loop has closed
        (late echo during shutdown), ``call_soon_threadsafe``
        raises ``RuntimeError``. The handler must swallow it —
        the shutdown is already underway and nothing more to do."""
        registered = {}

        def fake_signal(sig, handler):
            registered[sig] = handler

        loop = MagicMock()
        loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")
        state = MagicMock()

        with patch("main.signal.signal", side_effect=fake_signal):
            main_mod._install_shutdown_signals(state, loop)

        handler = registered[signal_mod.SIGINT]
        # Must not raise.
        handler(signal_mod.SIGINT.value, None)
