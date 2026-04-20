"""Tests for ``tools.repeat`` — command-repetition runner.

Subprocess execution is mocked; these tests cover the argument
parsing, iteration counting, {i}-substitution, stop-on-failure,
and summary accounting.
"""

from unittest.mock import MagicMock, patch

import pytest

import sys

from tools.repeat import _apply_iter, _resolve_python, main


class TestResolvePython:
    def test_swaps_python_for_sys_executable(self):
        out = _resolve_python(["python", "-m", "pytest"])
        assert out == [sys.executable, "-m", "pytest"]

    def test_swaps_python3_for_sys_executable(self):
        out = _resolve_python(["python3", "script.py"])
        assert out == [sys.executable, "script.py"]

    def test_leaves_non_python_alone(self):
        out = _resolve_python(["bash", "-c", "echo hi"])
        assert out == ["bash", "-c", "echo hi"]

    def test_handles_empty_cmd(self):
        out = _resolve_python([])
        assert out == []


class TestApplyIter:
    def test_replaces_literal_placeholder(self):
        out = _apply_iter(["--seed", "{i}"], 3)
        assert out == ["--seed", "3"]

    def test_replaces_multiple_occurrences(self):
        out = _apply_iter(["{i}", "{i}-label"], 7)
        assert out == ["7", "7-label"]

    def test_leaves_unrelated_args_alone(self):
        out = _apply_iter(["python", "-m", "mod"], 1)
        assert out == ["python", "-m", "mod"]


class TestMain:
    def test_zero_count_errors(self):
        with patch("tools.repeat.subprocess.run") as run:
            # count=0 means zero iterations; passed/total = 0/0. Exit 0.
            run.return_value = MagicMock(returncode=0)
            rc = main(["-n", "0", "--", "python", "-m", "dummy"])
        assert rc == 0
        run.assert_not_called()

    def test_success_runs_command_n_times(self, capsys):
        with patch("tools.repeat.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            rc = main(["-n", "3", "--", "python", "-m", "x"])

        assert rc == 0
        assert run.call_count == 3
        captured = capsys.readouterr()
        assert "3/3 succeeded" in captured.out

    def test_substitutes_iteration_number(self):
        calls = []
        def _capture(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)
        with patch("tools.repeat.subprocess.run", side_effect=_capture):
            main(["-n", "3", "--", "cmd", "--seed", "{i}"])

        assert calls == [
            ["cmd", "--seed", "1"],
            ["cmd", "--seed", "2"],
            ["cmd", "--seed", "3"],
        ]

    def test_nonzero_exit_tracked_in_summary(self, capsys):
        returncodes = iter([0, 1, 0])
        with patch(
            "tools.repeat.subprocess.run",
            side_effect=lambda *a, **kw: MagicMock(returncode=next(returncodes)),
        ):
            rc = main(["-n", "3", "--", "cmd"])

        assert rc == 1
        captured = capsys.readouterr()
        assert "2/3 succeeded" in captured.out
        assert "failing iterations: 2" in captured.err

    def test_stop_on_failure_halts_early(self):
        runcount = 0
        def _run(*a, **kw):
            nonlocal runcount
            runcount += 1
            return MagicMock(returncode=0 if runcount < 2 else 1)
        with patch("tools.repeat.subprocess.run", side_effect=_run):
            rc = main(["-n", "5", "--stop-on-failure", "--", "cmd"])

        assert rc == 1
        assert runcount == 2  # ran until the failure, then stopped

    def test_missing_command_errors(self):
        with pytest.raises(SystemExit):
            main(["-n", "3"])

    def test_quiet_suppresses_headers(self, capsys):
        with patch("tools.repeat.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            main(["-n", "2", "--quiet", "--", "cmd"])
        captured = capsys.readouterr()
        assert "iteration" not in captured.out
        # Summary still prints even in quiet mode.
        assert "2/2 succeeded" in captured.out

    def test_accepts_double_dash_separator(self):
        with patch("tools.repeat.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            rc = main(["-n", "1", "--", "cmd", "arg1"])
        assert rc == 0
        assert run.call_args.args[0] == ["cmd", "arg1"]

    def test_command_without_double_dash_still_works(self):
        with patch("tools.repeat.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            rc = main(["-n", "1", "cmd", "arg1"])
        assert rc == 0
        assert run.call_args.args[0] == ["cmd", "arg1"]


class TestEachMode:
    def test_runs_once_per_value(self):
        calls = []
        def _capture(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)
        with patch("tools.repeat.subprocess.run", side_effect=_capture):
            rc = main(["--each", "pixie,goblin,bandit", "--", "cmd", "{v}"])

        assert rc == 0
        assert calls == [
            ["cmd", "pixie"],
            ["cmd", "goblin"],
            ["cmd", "bandit"],
        ]

    def test_trims_whitespace_around_values(self):
        calls = []
        def _capture(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)
        with patch("tools.repeat.subprocess.run", side_effect=_capture):
            main(["--each", " a , b , c ", "--", "cmd", "{v}"])

        assert calls == [["cmd", "a"], ["cmd", "b"], ["cmd", "c"]]

    def test_empty_each_errors(self):
        with pytest.raises(SystemExit):
            main(["--each", ",,", "--", "cmd"])

    def test_each_overrides_count(self):
        """When --each is supplied, iteration count is len(values),
        not --count."""
        calls = []
        def _capture(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)
        with patch("tools.repeat.subprocess.run", side_effect=_capture):
            main(["-n", "10", "--each", "x,y", "--", "cmd", "{v}"])

        assert len(calls) == 2

    def test_both_i_and_v_substitute(self):
        calls = []
        def _capture(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)
        with patch("tools.repeat.subprocess.run", side_effect=_capture):
            main(["--each", "a,b", "--", "cmd", "{i}", "{v}"])

        assert calls == [["cmd", "1", "a"], ["cmd", "2", "b"]]

    def test_count_mode_still_works_without_each(self):
        calls = []
        def _capture(cmd, *a, **kw):
            calls.append(cmd)
            return MagicMock(returncode=0)
        with patch("tools.repeat.subprocess.run", side_effect=_capture):
            main(["-n", "3", "--", "cmd"])

        assert len(calls) == 3
