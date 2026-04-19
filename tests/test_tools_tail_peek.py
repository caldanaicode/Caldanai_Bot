"""Tests for ``tools/tail_peek.py``.

Formatting + stateless HTTP client. The inspector HTTP endpoint
it talks to is covered in ``test_tools_tail_channel.py``; these
tests pin the peek-side behavior: snapshot rendering shape,
``--tail`` slicing, connection-refused handling, JSON passthrough,
and cursor hint in the header.
"""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from tools import tail_peek


def _msg(msg_id: str, ts: str, author: str, content: str) -> dict:
    return {"id": msg_id, "timestamp": ts, "author": author, "content": content}


# ---------------------------------------------------------------------------
# _fetch — URL construction, error paths
# ---------------------------------------------------------------------------


class TestFetch:
    def test_no_since_omits_query_string(self):
        expected = {"messages": [], "buffer_size": 0, "buffer_max": 10,
                    "dropped_count": 0}

        def fake_urlopen(url, timeout=5):
            assert url == "http://127.0.0.1:8765/tail"
            resp = MagicMock()
            resp.__enter__ = lambda self: BytesIO(json.dumps(expected).encode())
            resp.__exit__ = lambda *_: None
            return resp

        with patch.object(tail_peek.urllib.request, "urlopen", fake_urlopen):
            got = tail_peek._fetch("127.0.0.1", 8765, None)
        assert got == expected

    def test_with_since_appends_query_string(self):
        """``since`` must appear in the URL so the server-side
        filter fires rather than relying on client-side slicing."""
        seen_urls = []
        payload = {"messages": [], "buffer_size": 0, "buffer_max": 10,
                   "dropped_count": 0}

        def fake_urlopen(url, timeout=5):
            seen_urls.append(url)
            resp = MagicMock()
            resp.__enter__ = lambda self: BytesIO(json.dumps(payload).encode())
            resp.__exit__ = lambda *_: None
            return resp

        with patch.object(tail_peek.urllib.request, "urlopen", fake_urlopen):
            tail_peek._fetch("127.0.0.1", 8765, 12345)
        assert seen_urls == ["http://127.0.0.1:8765/tail?since=12345"]

    def test_connection_refused_exits_with_hint(self, capsys):
        """When the --follow inspector isn't running the operator
        should get a one-line actionable hint, not a stack trace."""
        def fake_urlopen(url, timeout=5):
            raise URLError("Connection refused")

        with patch.object(tail_peek.urllib.request, "urlopen", fake_urlopen):
            with pytest.raises(SystemExit) as excinfo:
                tail_peek._fetch("127.0.0.1", 8765, None)

        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "Could not reach" in captured.err
        assert "tools.tail_channel --follow" in captured.err

    def test_http_error_exits_with_status(self, capsys):
        def fake_urlopen(url, timeout=5):
            raise HTTPError(
                url=url, code=500, msg="Server Error",
                hdrs=None, fp=BytesIO(b"boom"),
            )

        with patch.object(tail_peek.urllib.request, "urlopen", fake_urlopen):
            with pytest.raises(SystemExit) as excinfo:
                tail_peek._fetch("127.0.0.1", 8765, None)

        assert excinfo.value.code == 1
        captured = capsys.readouterr()
        assert "HTTP 500" in captured.err


# ---------------------------------------------------------------------------
# _format_snapshot — pastable markdown
# ---------------------------------------------------------------------------


class TestFormatSnapshot:
    def _snapshot(self, messages, dropped=0, buffer_max=500):
        return {
            "messages": messages,
            "buffer_size": len(messages),
            "buffer_max": buffer_max,
            "dropped_count": dropped,
        }

    def test_header_reports_buffer_and_latest_id(self):
        snap = self._snapshot([
            _msg("1", "2026-04-18T20:00Z", "Caels", "hi"),
            _msg("2", "2026-04-18T20:01Z", "Caels", "there"),
        ])
        out = tail_peek._format_snapshot(snap, tail=None)
        assert "buffer 2/500" in out
        assert "dropped=0" in out
        assert "`2`" in out  # latest id in the snapshot

    def test_empty_snapshot_says_so(self):
        snap = self._snapshot([])
        out = tail_peek._format_snapshot(snap, tail=None)
        assert "No messages to display" in out

    def test_tail_slices_to_last_n(self):
        msgs = [_msg(str(i), "ts", "Caels", f"m{i}") for i in range(1, 6)]
        snap = self._snapshot(msgs)
        out = tail_peek._format_snapshot(snap, tail=2)

        assert "m4" in out
        assert "m5" in out
        assert "m1" not in out
        assert "m2" not in out

    def test_tail_header_notes_hidden_messages(self):
        """When --tail hides some, the header should say so (so
        the caller knows messages weren't rolled off the back)."""
        msgs = [_msg(str(i), "ts", "Caels", f"m{i}") for i in range(1, 6)]
        snap = self._snapshot(msgs)
        out = tail_peek._format_snapshot(snap, tail=2)
        assert "showing last 2" in out

    def test_tail_header_silent_when_tail_larger_than_buffer(self):
        """No 'showing last N' if N >= buffer — there's nothing hidden."""
        msgs = [_msg("1", "ts", "Caels", "only")]
        snap = self._snapshot(msgs)
        out = tail_peek._format_snapshot(snap, tail=5)
        assert "showing last" not in out

    def test_dropped_count_shown(self):
        snap = self._snapshot([_msg("1", "ts", "Caels", "hi")], dropped=7)
        out = tail_peek._format_snapshot(snap, tail=None)
        assert "dropped=7" in out

    def test_body_is_quoted_per_line(self):
        snap = self._snapshot([_msg("1", "ts", "Caels", "line1\nline2")])
        out = tail_peek._format_snapshot(snap, tail=None)
        assert "> line1" in out
        assert "> line2" in out

    def test_message_header_includes_id_for_cursor_reuse(self):
        """The id is shown per message so the operator can copy it
        verbatim for the next ``--since`` call."""
        snap = self._snapshot([_msg("1234567890", "ts", "Caels", "hi")])
        out = tail_peek._format_snapshot(snap, tail=None)
        assert "id=1234567890" in out

    def test_empty_content_falls_back_to_placeholder(self):
        snap = self._snapshot([_msg("1", "ts", "Caels", "")])
        out = tail_peek._format_snapshot(snap, tail=None)
        assert "no content" in out
