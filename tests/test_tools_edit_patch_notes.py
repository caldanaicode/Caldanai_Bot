"""Tests for ``tools/edit_patch_notes.py``.

Mirrors ``test_tools_post_patch_notes.py``'s shape — file
validation, target resolution (default last-posted-log path
plus ``--message-id`` override), dry-run vs. ``--post`` flow,
exit codes.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import edit_patch_notes


@pytest.fixture
def tmp_blurb(tmp_path: Path) -> Path:
    f = tmp_path / "blurb.md"
    f.write_text("**Patch notes — fixed**\n\n- updated line.\n", encoding="utf-8")
    return f


class TestReadBlurb:
    """Same shape as post_patch_notes's read — the helpers are
    intentionally duplicated rather than imported, so duplicate
    the smoke coverage too."""

    def test_reads_and_strips(self, tmp_blurb):
        assert "fixed" in edit_patch_notes._read_blurb(tmp_blurb)

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="not found"):
            edit_patch_notes._read_blurb(tmp_path / "nope.md")

    def test_oversize_raises(self, tmp_path: Path):
        f = tmp_path / "big.md"
        f.write_text("x" * 2500, encoding="utf-8")
        with pytest.raises(SystemExit, match="2500"):
            edit_patch_notes._read_blurb(f)


class TestResolveTargets:
    def test_default_pulls_from_last_posted_log(self):
        """No ``--message-id`` → walk every entry in the last-
        posted log, look up each guild's display name + channel
        from the live config, and bundle them together."""
        with (
            patch("tools.edit_patch_notes._post_log") as plog,
            patch("tools.edit_patch_notes._resolve_guild_meta") as meta,
        ):
            plog.get_all_last_posted.return_value = {
                "1": {"channel_id": 100, "message_id": 999},
                "2": {"channel_id": 200, "message_id": 888},
            }
            meta.side_effect = lambda gid: {
                "guild_id": gid, "name": f"G{gid}", "channel_id": gid * 100,
            }

            targets = edit_patch_notes._resolve_targets(
                db_env_var="LIVE_DB_NAME",
                guild_filter=None, message_id_override=None,
            )

            assert len(targets) == 2
            assert {t["message_id"] for t in targets} == {999, 888}

    def test_guild_filter_narrows_default_path(self):
        with (
            patch("tools.edit_patch_notes._post_log") as plog,
            patch("tools.edit_patch_notes._resolve_guild_meta") as meta,
        ):
            plog.get_all_last_posted.return_value = {
                "1": {"channel_id": 100, "message_id": 999},
                "2": {"channel_id": 200, "message_id": 888},
            }
            meta.side_effect = lambda gid: {
                "guild_id": gid, "name": f"G{gid}", "channel_id": gid * 100,
            }

            targets = edit_patch_notes._resolve_targets(
                db_env_var="LIVE_DB_NAME",
                guild_filter=2, message_id_override=None,
            )

            assert [t["guild_id"] for t in targets] == [2]

    def test_message_id_override_requires_guild(self):
        """--message-id without --guild can't know which channel
        to target. Better to refuse than guess."""
        with pytest.raises(SystemExit, match="--message-id requires --guild"):
            edit_patch_notes._resolve_targets(
                db_env_var="LIVE_DB_NAME",
                guild_filter=None, message_id_override=12345,
            )

    def test_message_id_override_builds_single_target(self):
        with patch("tools.edit_patch_notes._resolve_guild_meta") as meta:
            meta.return_value = {
                "guild_id": 42, "name": "Alpha", "channel_id": 100,
            }
            targets = edit_patch_notes._resolve_targets(
                db_env_var="LIVE_DB_NAME",
                guild_filter=42, message_id_override=12345,
            )
            assert len(targets) == 1
            assert targets[0]["message_id"] == 12345
            assert targets[0]["channel_id"] == 100

    def test_message_id_override_unknown_guild_raises(self):
        with patch("tools.edit_patch_notes._resolve_guild_meta", return_value=None):
            with pytest.raises(SystemExit, match="no updates channel"):
                edit_patch_notes._resolve_targets(
                    db_env_var="LIVE_DB_NAME",
                    guild_filter=42, message_id_override=12345,
                )

    def test_default_path_skips_guilds_without_channel_anymore(self, capsys):
        """A guild had a recorded post but its updates
        channel was unset since. Skip with a warning rather than
        crash — the operator can re-config and retry."""
        with (
            patch("tools.edit_patch_notes._post_log") as plog,
            patch("tools.edit_patch_notes._resolve_guild_meta", return_value=None),
        ):
            plog.get_all_last_posted.return_value = {
                "1": {"channel_id": 100, "message_id": 999},
            }
            targets = edit_patch_notes._resolve_targets(
                db_env_var="LIVE_DB_NAME",
                guild_filter=None, message_id_override=None,
            )
            captured = capsys.readouterr()

            assert targets == []
            assert "Skipping guild 1" in captured.err


class TestMain:
    def test_no_recorded_posts_returns_nonzero_with_hint(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["edit_patch_notes.py", "--file", str(tmp_blurb)],
        )
        with (
            patch("tools.edit_patch_notes.use_db_env_var"),
            patch("tools.edit_patch_notes._resolve_targets", return_value=[]),
        ):
            rc = edit_patch_notes.main()
        captured = capsys.readouterr()

        assert rc == 1
        assert "post_patch_notes" in captured.err

    def test_dry_run_does_not_call_edit(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["edit_patch_notes.py", "--file", str(tmp_blurb)],
        )
        targets = [{
            "guild_id": 1, "name": "Alpha",
            "channel_id": 100, "message_id": 999,
        }]

        async def fake_dry_run(ts, content, token):
            return 0

        with (
            patch("tools.edit_patch_notes.use_db_env_var"),
            patch("tools.edit_patch_notes._resolve_targets", return_value=targets),
            patch("tools.edit_patch_notes.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.edit_patch_notes._show_dry_run", side_effect=fake_dry_run) as dry,
            patch("tools.edit_patch_notes._edit_targets") as editor,
        ):
            rc = edit_patch_notes.main()

        assert rc == 0
        dry.assert_called_once()
        editor.assert_not_called()

    def test_post_calls_through_to_edit_loop(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["edit_patch_notes.py", "--post", "--file", str(tmp_blurb)],
        )
        targets = [{
            "guild_id": 1, "name": "Alpha",
            "channel_id": 100, "message_id": 999,
        }]

        async def fake_edit(ts, content, token):
            return len(ts)

        with (
            patch("tools.edit_patch_notes.use_db_env_var"),
            patch("tools.edit_patch_notes._resolve_targets", return_value=targets),
            patch("tools.edit_patch_notes.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.edit_patch_notes._edit_targets", side_effect=fake_edit) as editor,
        ):
            rc = edit_patch_notes.main()

        assert rc == 0
        editor.assert_called_once()
        # Token threaded through.
        assert editor.call_args.args[2] == "xyz"

    def test_partial_failure_returns_distinct_exit_code(
        self, tmp_blurb, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["edit_patch_notes.py", "--post", "--file", str(tmp_blurb)],
        )
        targets = [
            {"guild_id": 1, "name": "Alpha", "channel_id": 100, "message_id": 999},
            {"guild_id": 2, "name": "Beta", "channel_id": 200, "message_id": 888},
        ]

        async def fake_one_succeeds(ts, content, token):
            return 1

        with (
            patch("tools.edit_patch_notes.use_db_env_var"),
            patch("tools.edit_patch_notes._resolve_targets", return_value=targets),
            patch("tools.edit_patch_notes.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.edit_patch_notes._edit_targets", side_effect=fake_one_succeeds),
        ):
            rc = edit_patch_notes.main()

        assert rc == 2
