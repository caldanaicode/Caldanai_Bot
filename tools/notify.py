"""Speak a short notification via Windows PowerShell TTS.

Fires when the agent needs the user's attention and the terminal is
unattended — background agents completing, pre/post-deploy rituals
waiting on approval, etc. An audible cue beats "please glance at
the terminal" when the user is AFK.

Usage::

    python -m tools.notify "Phase 1 review done, waiting on approval"
    python -m tools.notify "Agent complete" --quiet

Message is passed to PowerShell via an environment variable so there
is zero shell-interpolation surface — no quote-escaping concerns
regardless of what the message contains.

Why this exists (not inline ``powershell -c ...``): every inline
PowerShell call re-prompts the permission harness. A dedicated tool
gets approved once and stays reusable.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import Optional, Sequence


_PS_SCRIPT = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$s.Speak($env:NOTIFY_MSG)"
)


def speak(message: str) -> int:
    """Speak ``message`` via Windows PowerShell TTS. Returns the
    PowerShell exit code (0 on success). Empty / whitespace-only
    messages are a no-op returning 0 — nothing to say."""
    if not message.strip():
        return 0
    env = os.environ.copy()
    env["NOTIFY_MSG"] = message
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _PS_SCRIPT],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"notify: PowerShell TTS failed (exit {result.returncode}): "
            f"{result.stderr.strip()}\n"
        )
    return result.returncode


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Speak a short notification via Windows PowerShell TTS."
    )
    parser.add_argument("message", help="Text to speak.")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the confirmation line on success.",
    )
    args = parser.parse_args(argv)
    exit_code = speak(args.message)
    if exit_code == 0 and not args.quiet:
        print(f"spoke: {args.message}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
