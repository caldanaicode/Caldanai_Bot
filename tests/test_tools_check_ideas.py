"""Tests for ``tools/check_ideas.py``.

Cursor + fetch + format orchestration. The Discord REST client
itself is covered in ``test_tools_common.py``; these tests pin
the tool-specific behavior: cursor file shape, first-run vs.
incremental, message rendering for paste-back, and the partial-
failure resilience that lets a single failing guild not abort
the others.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import check_ideas


@pytest.fixture
def cursor_in_tmp(tmp_path: Path, monkeypatch):
    """Redirect the shared state-file directory (now in
    ``tools._common``) into ``tmp_path`` so tests don't touch
    the real ``tools/.ideas_cursor.*.json`` files. Returns the
    per-env file path the tests will use (``LIVE_DB_NAME`` is
    the default test env)."""
    from tools import _common
    monkeypatch.setattr(_common, "_STATE_DIR", tmp_path)
    return tmp_path / ".ideas_cursor.LIVE_DB_NAME.json"


def _msg(message_id: str, ts: str, author: str, content: str) -> dict:
    return {
        "id": message_id,
        "timestamp": ts,
        "author": {"global_name": author, "username": author},
        "content": content,
    }


class TestCursor:
    def test_load_returns_empty_when_missing(self, cursor_in_tmp):
        assert check_ideas._load_cursor("LIVE_DB_NAME") == {}

    def test_round_trip_save_load(self, cursor_in_tmp):
        data = {"42": {"channel_id": 100, "last_message_id": 999}}
        check_ideas._save_cursor("LIVE_DB_NAME", data)
        assert check_ideas._load_cursor("LIVE_DB_NAME") == data

    def test_malformed_cursor_treated_as_empty(self, cursor_in_tmp, capsys):
        cursor_in_tmp.write_text("{not json", encoding="utf-8")
        assert check_ideas._load_cursor("LIVE_DB_NAME") == {}
        captured = capsys.readouterr()
        assert "malformed" in captured.err

    def test_cursors_are_filesystem_isolated_per_env(self, cursor_in_tmp):
        """A LIVE check and a TEST check for the same guild
        write to different files — the whole point of the
        per-env scheme. An incremental TEST check can never see
        the LIVE cursor and vice versa."""
        check_ideas._save_cursor("LIVE_DB_NAME", {"1": {"channel_id": 100, "last_message_id": 111}})
        check_ideas._save_cursor("TEST_DB_NAME", {"1": {"channel_id": 200, "last_message_id": 222}})

        assert check_ideas._load_cursor("LIVE_DB_NAME") == {"1": {"channel_id": 100, "last_message_id": 111}}
        assert check_ideas._load_cursor("TEST_DB_NAME") == {"1": {"channel_id": 200, "last_message_id": 222}}

    def test_cursor_path_uses_env_var_name_in_filename(self, cursor_in_tmp):
        path = check_ideas._cursor_path("MY_VAR")
        assert path.name == ".ideas_cursor.MY_VAR.json"


class TestFindIdeasTargets:
    def test_filters_to_opted_in_guilds(self):
        with patch("tools.check_ideas.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = [
                {"guild_id": 1, "name": "Alpha", "channels": {"ideas": 100}},
            ]
            live_db.return_value = db

            targets = check_ideas._find_ideas_targets(None)

            db.servers.find.assert_called_once_with(
                {"channels.ideas": {"$exists": True}},
            )
            assert targets == [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]


class TestFormatMessages:
    def test_renders_multiple_messages_chronologically(self):
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}
        # Discord returns newest-first; the formatter must reverse.
        messages = [
            _msg("3", "2026-04-18T18:00:00Z", "Charlie", "third"),
            _msg("2", "2026-04-18T17:00:00Z", "Bob", "second"),
            _msg("1", "2026-04-18T16:00:00Z", "Alice", "first"),
        ]
        out = check_ideas._format_messages(target, messages)

        # Header with guild context.
        assert out.startswith("# Ideas channel — Alpha (guild 1)")
        # Chronological order in the output: first → second → third.
        first_idx = out.index("first")
        second_idx = out.index("second")
        third_idx = out.index("third")
        assert first_idx < second_idx < third_idx

    def test_quotes_each_body_line_for_markdown_paste(self):
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}
        messages = [_msg("1", "ts", "Alice", "line one\nline two")]
        out = check_ideas._format_messages(target, messages)

        assert "> line one" in out
        assert "> line two" in out

    def test_empty_content_renders_placeholder(self):
        """Embeds-only or attachments-only messages have empty
        content. Render a placeholder so they aren't silently
        dropped from the operator's view."""
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}
        messages = [_msg("1", "ts", "Alice", "")]
        out = check_ideas._format_messages(target, messages)

        assert "no text content" in out

    def test_no_messages_renders_explicit_no_news_block(self):
        """A guild with no new messages still gets a header so the
        operator sees the channel was checked. Important when
        running across multiple guilds — silence on one looks
        like a bug otherwise."""
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}
        out = check_ideas._format_messages(target, [])
        assert "Alpha" in out
        assert "No new messages" in out

    def test_unknown_author_falls_back_gracefully(self):
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}
        messages = [{
            "id": "1",
            "timestamp": "ts",
            "author": {},
            "content": "anonymous",
        }]
        out = check_ideas._format_messages(target, messages)
        assert "@<unknown>" in out


class TestFetchForTarget:
    @pytest.mark.asyncio
    async def test_no_cursor_uses_first_run_limit(self):
        """First-time fetch (no cursor entry) calls
        ``get_messages`` with the configured first-run limit and
        no ``after`` — Discord then returns the most recent N."""
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[])
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}

        await check_ideas._fetch_for_target(client, target, None, 25)

        client.get_messages.assert_called_once_with(100, after=None, limit=25)

    @pytest.mark.asyncio
    async def test_existing_cursor_passes_after_and_caps_at_100(self):
        """Incremental fetches use ``after=last_id`` and the full
        100-per-page Discord cap (the first-run limit isn't the
        right ceiling for backfill)."""
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[])
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}

        await check_ideas._fetch_for_target(
            client, target, {"last_message_id": 999}, 25,
        )

        client.get_messages.assert_called_once_with(100, after=999, limit=100)

    @pytest.mark.asyncio
    async def test_returns_newest_id_for_cursor_update(self):
        """The new cursor must point at the newest message in
        the batch, not the oldest — otherwise the next run
        re-fetches messages we just saw."""
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[
            _msg("3", "ts", "x", "c"),
            _msg("1", "ts", "x", "a"),
            _msg("2", "ts", "x", "b"),
        ])
        target = {"guild_id": 1, "name": "Alpha", "channel_id": 100}

        _, new_id = await check_ideas._fetch_for_target(client, target, None, 50)

        assert new_id == 3


class TestRun:
    @pytest.mark.asyncio
    async def test_partial_failure_doesnt_abort_remaining_targets(self, capsys):
        """One guild's REST failure must not skip the others.
        Failed guild's cursor stays untouched so the next run
        retries from the same point."""
        targets = [
            {"guild_id": 1, "name": "Alpha", "channel_id": 100},
            {"guild_id": 2, "name": "Beta", "channel_id": 200},
        ]

        async def fake_fetch(client, target, cursor_entry, limit):
            if target["guild_id"] == 1:
                raise RuntimeError("simulated failure")
            return [_msg("5", "ts", "x", "ok")], 5

        with (
            patch("tools.check_ideas.DiscordRestClient") as Client,
            patch("tools.check_ideas._fetch_for_target", side_effect=fake_fetch),
        ):
            instance = AsyncMock()
            Client.return_value.__aenter__.return_value = instance

            blocks, new_cursor = await check_ideas._run(
                targets, cursor={}, first_run_limit=50, token="t",
            )

        # Beta succeeded → its block exists, its cursor is set.
        assert any("Beta" in b for b in blocks)
        assert "2" in new_cursor and new_cursor["2"]["last_message_id"] == 5
        # Alpha failed → no block, no cursor entry.
        assert not any("Alpha" in b for b in blocks)
        assert "1" not in new_cursor


class TestMain:
    def test_no_targets_returns_nonzero_with_setup_hint(self, capsys, monkeypatch):
        monkeypatch.setattr("sys.argv", ["check_ideas.py"])
        with (
            patch("tools.check_ideas.use_db_env_var"),
            patch("tools.check_ideas._find_ideas_targets", return_value=[]),
        ):
            rc = check_ideas.main()
        captured = capsys.readouterr()

        assert rc == 1
        assert "$config ideas_channel" in captured.err

    def test_reset_clears_cursor_then_seeds(self, cursor_in_tmp, monkeypatch, capsys):
        cursor_in_tmp.write_text(
            json.dumps({"1": {"channel_id": 100, "last_message_id": 999}}),
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.argv", ["check_ideas.py", "--reset"])

        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]
        with (
            patch("tools.check_ideas.use_db_env_var"),
            patch("tools.check_ideas._find_ideas_targets", return_value=targets),
            patch("tools.check_ideas.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.check_ideas._run") as run,
        ):
            run.return_value = ([], {"1": {"channel_id": 100, "last_message_id": 5}})
            rc = check_ideas.main()

        assert rc == 0
        # _run must have seen an empty cursor (reset effective).
        assert run.call_args.args[1] == {}

    def test_writes_updated_cursor_after_run(self, cursor_in_tmp, monkeypatch):
        monkeypatch.setattr("sys.argv", ["check_ideas.py"])
        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]
        new_cursor = {"1": {"channel_id": 100, "last_message_id": 42}}
        with (
            patch("tools.check_ideas.use_db_env_var"),
            patch("tools.check_ideas._find_ideas_targets", return_value=targets),
            patch("tools.check_ideas.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.check_ideas._run", return_value=([], new_cursor)),
        ):
            check_ideas.main()

        assert json.loads(cursor_in_tmp.read_text(encoding="utf-8")) == new_cursor

    def test_db_env_var_arg_drives_use_db_env_var_call(self, monkeypatch):
        """The positional arg routes through to ``use_db_env_var``
        so the operator's choice of DB actually takes effect.
        Without this wiring, every invocation would silently
        target whatever LIVE_DB_NAME points at."""
        monkeypatch.setattr(
            "sys.argv",
            ["check_ideas.py", "TEST_DB_NAME"],
        )
        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]
        with (
            patch("tools.check_ideas.use_db_env_var") as use_db,
            patch("tools.check_ideas._find_ideas_targets", return_value=targets),
            patch("tools.check_ideas.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.check_ideas._run", return_value=([], {})),
        ):
            check_ideas.main()

        use_db.assert_called_once_with("TEST_DB_NAME")
