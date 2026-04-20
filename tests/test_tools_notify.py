"""Tests for ``tools.notify`` — subprocess invocation shape only
(real TTS hits the audio stack, so we mock and verify the call)."""

from unittest.mock import MagicMock, patch

import pytest

from tools.notify import main, speak


class TestSpeak:
    def test_invokes_powershell_with_message_in_env(self):
        with patch("tools.notify.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="")
            exit_code = speak("hello world")

        assert exit_code == 0
        assert run.call_count == 1
        call_env = run.call_args.kwargs["env"]
        assert call_env["NOTIFY_MSG"] == "hello world"
        cmd = run.call_args.args[0]
        assert cmd[0] == "powershell"
        assert "-NoProfile" in cmd
        assert "System.Speech" in cmd[-1]

    def test_message_not_interpolated_into_command(self):
        # Defense-in-depth: the message must land in env, never on
        # the command line — guarantees no shell-injection surface.
        with patch("tools.notify.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0, stderr="")
            speak('"; rm -rf /; "')

        cmd = run.call_args.args[0]
        assert all("rm -rf" not in piece for piece in cmd)

    def test_empty_message_short_circuits(self):
        with patch("tools.notify.subprocess.run") as run:
            exit_code = speak("")
        assert exit_code == 0
        run.assert_not_called()

    def test_whitespace_only_message_short_circuits(self):
        with patch("tools.notify.subprocess.run") as run:
            exit_code = speak("   \n\t  ")
        assert exit_code == 0
        run.assert_not_called()

    def test_failure_returns_nonzero_and_writes_stderr(self, capsys):
        with patch("tools.notify.subprocess.run") as run:
            run.return_value = MagicMock(returncode=1, stderr="kaboom")
            exit_code = speak("test")

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "PowerShell TTS failed" in captured.err
        assert "kaboom" in captured.err


class TestMain:
    def test_passes_message_to_speak(self):
        with patch("tools.notify.speak") as sp:
            sp.return_value = 0
            exit_code = main(["hi"])

        assert exit_code == 0
        sp.assert_called_once_with("hi")

    def test_prints_confirmation_on_success(self, capsys):
        with patch("tools.notify.speak") as sp:
            sp.return_value = 0
            main(["hello"])

        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_quiet_suppresses_confirmation(self, capsys):
        with patch("tools.notify.speak") as sp:
            sp.return_value = 0
            main(["hello", "--quiet"])

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_returns_nonzero_on_failure(self):
        with patch("tools.notify.speak") as sp:
            sp.return_value = 1
            exit_code = main(["test"])

        assert exit_code == 1

    def test_no_confirmation_on_failure(self, capsys):
        with patch("tools.notify.speak") as sp:
            sp.return_value = 1
            main(["test"])

        captured = capsys.readouterr()
        assert "spoke:" not in captured.out

    def test_missing_message_argument_errors(self):
        with pytest.raises(SystemExit):
            main([])
