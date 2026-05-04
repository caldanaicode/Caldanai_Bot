"""Tests for tools.journal CLI argument resolution.

The actual Discord posting is exercised separately via
``tools._common.split_for_discord`` tests; this file pins the
``--stdin`` / ``--file`` / positional content-resolution contract
that the journal tool added 2026-05-03 to sidestep Windows .bat
multi-line argv truncation.
"""

import io
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tools.journal import _resolve_content


def _ns(**kw):
    """Lightweight argparse-like namespace for _resolve_content tests."""
    return SimpleNamespace(
        content=kw.get("content"),
        stdin=kw.get("stdin", False),
        file=kw.get("file"),
    )


class TestResolveContent:
    def test_positional_returned_directly(self):
        result = _resolve_content(_ns(content="hello"), kind="entry")
        assert result == "hello"

    def test_stdin_reads_full_content(self):
        text = "Para 1.\n\nPara 2.\n\nPara 3."
        with patch("sys.stdin", io.StringIO(text)):
            result = _resolve_content(_ns(stdin=True), kind="entry")
        assert result == text

    def test_stdin_strips_trailing_newlines(self):
        """Common shell pipes append a trailing newline; the tool
        strips it so the posted message doesn't end with extra
        whitespace."""
        with patch("sys.stdin", io.StringIO("hello\n\n")):
            result = _resolve_content(_ns(stdin=True), kind="entry")
        assert result == "hello"

    def test_stdin_preserves_interior_newlines(self):
        """Multi-paragraph stdin must keep paragraph breaks. This
        is the whole point of the stdin path — argv-via-.bat eats
        these; stdin must not."""
        text = "Para 1.\n\nPara 2.\n\nPara 3."
        with patch("sys.stdin", io.StringIO(text + "\n")):
            result = _resolve_content(_ns(stdin=True), kind="entry")
        # Trailing strip keeps interior \n\n breaks.
        assert result == text
        assert result.count("\n\n") == 2

    def test_file_reads_content(self, tmp_path):
        f = tmp_path / "entry.md"
        f.write_text("From file content.", encoding="utf-8")
        result = _resolve_content(
            _ns(file=str(f)), kind="entry",
        )
        assert result == "From file content."

    def test_file_preserves_interior_newlines(self, tmp_path):
        f = tmp_path / "entry.md"
        text = "Para 1.\n\nPara 2.\n\nPara 3."
        f.write_text(text + "\n", encoding="utf-8")
        result = _resolve_content(_ns(file=str(f)), kind="entry")
        assert result == text

    def test_no_source_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc:
            _resolve_content(_ns(), kind="entry")
        assert "No entry content" in str(exc.value)

    def test_multiple_sources_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc:
            _resolve_content(
                _ns(content="x", stdin=True), kind="entry",
            )
        assert "Multiple content sources" in str(exc.value)

    def test_empty_stdin_raises_systemexit(self):
        """Empty stdin should refuse rather than post a blank
        message — silent failure on a misconfigured pipe is worse
        than a loud refusal."""
        with patch("sys.stdin", io.StringIO("")):
            with pytest.raises(SystemExit) as exc:
                _resolve_content(_ns(stdin=True), kind="entry")
        assert "empty" in str(exc.value).lower()

    def test_kind_appears_in_error_message(self):
        """``kind`` parameter customizes the error so post vs edit
        users see relevant phrasing."""
        with pytest.raises(SystemExit) as exc:
            _resolve_content(_ns(), kind="replacement")
        assert "replacement" in str(exc.value).lower()
