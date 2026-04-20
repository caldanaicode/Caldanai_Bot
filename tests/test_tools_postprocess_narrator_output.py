"""Tests for ``tools/postprocess_narrator_output.py`` — the CLI
wrapper around the parser's lint functions.

The lint logic itself lives in
``caldanai.lib.rpg.helpers.parser`` and has its own test suite
(``tests/test_parser_lint.py``). This file only covers the CLI
plumbing: argparse flags, stdin / stdout / file I/O, warning
formatting.
"""

import io
import json
from contextlib import redirect_stdout, redirect_stderr

from tools import postprocess_narrator_output as pp


class TestCLI:
    def test_stdin_stdout_roundtrip(self, monkeypatch):
        payload = {
            "narrate_attempt": "@1m surges, @1a shortsword bites @2np torso.",
            "narrate_results": "@2no stumbles back.",
            "narrate_target_death": None,
            "narrate_attacker_death": None,
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            exit_code = pp.main([])
        assert exit_code == 0
        parsed = json.loads(buf.getvalue())
        # @1m at sentence start gets upper-cased to @1M (no-op for
        # player mention render, "Bandit" vs "bandit" for monster
        # fallback). Mid-sentence @1a and @2np stay lowercase.
        assert parsed["narrate_attempt"] == "@1M surges, @1a shortsword bites @2np torso."
        # @2no → @2o (strip invalid noun-mode) → @2O (sentence-start cap)
        assert parsed["narrate_results"] == "@2O stumbles back."
        assert "WARN:" in err.getvalue()

    def test_file_input_output(self, tmp_path):
        payload = {
            "narrate_attempt": "@2a skull offers no resistance.",
            "narrate_results": None,
            "narrate_target_death": None,
            "narrate_attacker_death": None,
        }
        in_path = tmp_path / "in.json"
        out_path = tmp_path / "out.json"
        in_path.write_text(json.dumps(payload), encoding="utf-8")
        exit_code = pp.main([
            "--input", str(in_path),
            "--output", str(out_path),
            "--quiet",
        ])
        assert exit_code == 0
        out = json.loads(out_path.read_text(encoding="utf-8"))
        assert out["narrate_attempt"] == "@2A skull offers no resistance."

    def test_quiet_suppresses_warnings(self, monkeypatch):
        payload = {
            "narrate_attempt": "her eyes flare",   # literal pronoun — should warn
            "narrate_results": None,
            "narrate_target_death": None,
            "narrate_attacker_death": None,
        }
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
        buf = io.StringIO()
        err = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(err):
            pp.main(["--quiet"])
        assert "WARN:" not in err.getvalue()
