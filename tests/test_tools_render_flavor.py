"""Tests for ``tools/render_flavor.py``.

The tool's real output is sampled text rendered through ``parse()``
— exercising the full monster plugin stack and the parser. These
tests verify the CLI plumbing, the dedup behavior in
``_sample_branches``, and that a known monster (bandit) renders
without exceptions and produces the expected shape.
"""

import io
import json
from contextlib import redirect_stdout

import pytest

from tools import render_flavor


# ``random`` state leakage is handled repo-wide by the autouse
# ``_isolate_random_state`` fixture in ``tests/conftest.py`` — no
# per-file save/restore needed. The tool's ``--seed`` flag still
# scopes cleanly within a test because conftest snapshots before
# and restores after each invocation.


class TestSampleBranches:
    def test_dedups_repeated_outputs(self):
        """Branches producing the same rendered string across
        multiple samples should collapse to a single entry."""
        calls = iter(["alpha", "alpha", "beta", "alpha", "beta"])
        out = render_flavor._sample_branches(
            fn=lambda: next(calls),
            count=5,
            post_parse=False,
            monster=None,
            actor=None,
        )
        assert out == ["alpha", "beta"]

    def test_skips_empty_outputs(self):
        """Empty strings and None are filtered out — monsters that
        don't override a hook return empty, and we don't want that
        in the dumped pool."""
        calls = iter(["", None, "real", ""])
        out = render_flavor._sample_branches(
            fn=lambda: next(calls),
            count=4,
            post_parse=False,
            monster=None,
            actor=None,
        )
        assert out == ["real"]


class TestCLI:
    def test_bandit_end_to_end_renders_without_error(self):
        """Running the CLI against the bandit plugin exercises the
        monster loader, the parse pipeline, and the output path.
        Smoke test — we only assert the render succeeded and produced
        some recognizable output, not exact wording (that's owned by
        the bandit file, which drifts as flavor evolves)."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = render_flavor.main([
                "bandit", "--count", "10", "--seed", "0",
            ])
        assert exit_code == 0
        text = buf.getvalue()
        assert "Bandit" in text
        assert "on_hugged" in text
        assert "on_social" in text
        # The bandit's high_five override is one of the two things
        # this tool was built to render-proof — make sure the section
        # actually landed in the output.
        assert "'high_five'" in text

    def test_json_mode_emits_parseable_json(self):
        """``--json`` produces machine-readable output that other
        tooling can consume."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = render_flavor.main([
                "bandit", "--count", "5", "--seed", "0", "--json",
            ])
        assert exit_code == 0
        payload = json.loads(buf.getvalue())
        assert "static" in payload
        assert "on_hugged" in payload
        assert "on_social" in payload
        assert "high_five" in payload["on_social"]

    def test_cmd_flag_limits_social_output(self):
        """``--cmd high_five`` scopes the social dump to a single
        command instead of iterating every warmth-aware verb."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = render_flavor.main([
                "bandit", "--count", "5", "--cmd", "high_five",
                "--seed", "0", "--json",
            ])
        assert exit_code == 0
        payload = json.loads(buf.getvalue())
        assert set(payload["on_social"].keys()) == {"high_five"}

    def test_unknown_monster_exits_cleanly(self):
        """Unknown plugin stems should produce a helpful error
        instead of a stack trace."""
        with pytest.raises(SystemExit) as exc:
            render_flavor.main(["not_a_real_monster"])
        # The error message goes through SystemExit; verify it
        # mentions what was wrong.
        assert "not_a_real_monster" in str(exc.value) or exc.value.code != 0
