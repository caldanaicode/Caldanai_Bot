"""Tests for ``tools/post_patch_notes.py``.

The tool is a thin orchestrator over :mod:`tools._common`. Tests
focus on the orchestration contracts that aren't covered in
``test_tools_common.py``: blurb file validation, target discovery
from the servers collection, dry-run vs. post selection, and the
all-guild-by-default vs. ``--guild`` scoping behavior.
"""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import post_patch_notes


@pytest.fixture
def tmp_blurb(tmp_path: Path) -> Path:
    f = tmp_path / "blurb.md"
    f.write_text("- A change.\n", encoding="utf-8")
    return f


_HEADER_RE = re.compile(r"\*\*Patch notes — \d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC\*\*")


class TestReadBlurb:
    def test_reads_strips_and_prepends_header(self, tmp_blurb):
        content = post_patch_notes._read_blurb(tmp_blurb)
        assert _HEADER_RE.match(content), (
            f"expected current-UTC header at start of content; got {content!r}"
        )
        assert "- A change." in content
        assert content == content.strip()

    def test_replaces_legacy_embedded_header(self, tmp_path: Path):
        """A scratch file written before the auto-prepend landed
        carries its own ``**Patch notes — old-date UTC**`` header.
        Re-reading must strip the stale header rather than
        double-stamp the message with two different timestamps."""
        f = tmp_path / "legacy.md"
        f.write_text(
            "**Patch notes — 2026-01-01 00:00 UTC**\n\n- A change.\n",
            encoding="utf-8",
        )
        content = post_patch_notes._read_blurb(f)
        # Exactly one header line, and it's NOT the legacy timestamp.
        assert content.count("**Patch notes — ") == 1
        assert "2026-01-01 00:00 UTC" not in content

    def test_missing_file_raises_with_path(self, tmp_path: Path):
        with pytest.raises(SystemExit, match="not found"):
            post_patch_notes._read_blurb(tmp_path / "nope.md")

    def test_empty_file_raises(self, tmp_path: Path):
        f = tmp_path / "empty.md"
        f.write_text("   \n  \n", encoding="utf-8")
        with pytest.raises(SystemExit, match="empty"):
            post_patch_notes._read_blurb(f)

    def test_oversize_blurb_raises_with_limit_in_message(self, tmp_path: Path):
        """Discord's 2000-char limit; we refuse rather than silently
        truncate or post a 400 from the API. The size check runs
        against the post-prepend content so the limit is honest
        about what'll actually be sent."""
        f = tmp_path / "big.md"
        f.write_text("x" * 2500, encoding="utf-8")
        with pytest.raises(SystemExit, match=r"\d{4} chars"):
            post_patch_notes._read_blurb(f)


class TestFindAnnouncementTargets:
    def test_returns_every_opted_in_guild(self):
        with patch("tools.post_patch_notes.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = [
                {"guild_id": 1, "name": "Alpha", "channels": {"updates": 100}},
                {"guild_id": 2, "name": "Beta", "channels": {"updates": 200}},
            ]
            live_db.return_value = db

            targets = post_patch_notes._find_announcement_targets(None)

            assert len(targets) == 2
            assert targets[0] == {"guild_id": 1, "name": "Alpha", "channel_id": 100}
            assert targets[1] == {"guild_id": 2, "name": "Beta", "channel_id": 200}

    def test_query_filters_to_guilds_with_updates_configured(self):
        """The Mongo query filters server-side to opted-in guilds —
        a guild without ``channels.updates`` (e.g. a guild
        that only set the ideas channel) is correctly excluded."""
        with patch("tools.post_patch_notes.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = []
            live_db.return_value = db

            post_patch_notes._find_announcement_targets(None)

            db.servers.find.assert_called_once()
            query = db.servers.find.call_args.args[0]
            assert query == {"channels.updates": {"$exists": True}}

    def test_guild_filter_narrows_query(self):
        with patch("tools.post_patch_notes.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = []
            live_db.return_value = db

            post_patch_notes._find_announcement_targets(42)

            query = db.servers.find.call_args.args[0]
            assert query["guild_id"] == 42
            assert query["channels.updates"] == {"$exists": True}

    def test_unnamed_guild_falls_back_to_id(self):
        """Server docs predating the prefix command may have no
        ``name`` field; show something useful instead of None."""
        with patch("tools.post_patch_notes.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = [
                {"guild_id": 99, "channels": {"updates": 1}},
            ]
            live_db.return_value = db

            targets = post_patch_notes._find_announcement_targets(None)
            assert "99" in targets[0]["name"]


class TestMainOrchestration:
    def test_no_targets_returns_nonzero_with_setup_hint(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        """If no guild has opted in, the operator should see a
        clear hint pointing at the ``$config`` command. Exit code
        is non-zero so a wrapper script can branch on it."""
        monkeypatch.setattr(
            "sys.argv",
            ["post_patch_notes.py", "--file", str(tmp_blurb)],
        )
        with (
            patch("tools.post_patch_notes.use_db_env_var"),
            patch("tools.post_patch_notes._find_announcement_targets", return_value=[]),
        ):
            rc = post_patch_notes.main()
        captured = capsys.readouterr()

        assert rc == 1
        assert "$config channel updates" in captured.err

    def test_dry_run_prints_targets_and_does_not_post(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["post_patch_notes.py", "--file", str(tmp_blurb)],
        )
        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]
        with (
            patch("tools.post_patch_notes.use_db_env_var"),
            patch("tools.post_patch_notes._find_announcement_targets", return_value=targets),
            patch("tools.post_patch_notes._post_to_targets") as poster,
        ):
            rc = post_patch_notes.main()
        captured = capsys.readouterr()

        assert rc == 0
        assert "DRY RUN" in captured.out
        assert "Alpha" in captured.out
        assert "Patch notes" in captured.out
        poster.assert_not_called()

    def test_post_calls_through_to_rest_loop(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        """``--post`` actually invokes the async REST loop with the
        token from the live auth doc."""
        monkeypatch.setattr(
            "sys.argv",
            ["post_patch_notes.py", "--post", "--file", str(tmp_blurb)],
        )
        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]

        async def fake_post(content, ts, token, db_env_var):
            return len(ts)

        with (
            patch("tools.post_patch_notes.use_db_env_var"),
            patch("tools.post_patch_notes._find_announcement_targets", return_value=targets),
            patch("tools.post_patch_notes.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.post_patch_notes._post_to_targets", side_effect=fake_post) as poster,
        ):
            rc = post_patch_notes.main()
        captured = capsys.readouterr()

        assert rc == 0
        poster.assert_called_once()
        # The token from get_auth() makes it into the post call.
        assert poster.call_args.args[2] == "xyz"
        assert "1/1 successful" in captured.out

    def test_post_without_token_in_auth_doc_errors(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        monkeypatch.setattr(
            "sys.argv",
            ["post_patch_notes.py", "--post", "--file", str(tmp_blurb)],
        )
        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]
        with (
            patch("tools.post_patch_notes.use_db_env_var"),
            patch("tools.post_patch_notes._find_announcement_targets", return_value=targets),
            patch("tools.post_patch_notes.get_auth", return_value={}),
        ):
            rc = post_patch_notes.main()
        captured = capsys.readouterr()

        assert rc == 1
        assert "TOKEN" in captured.err

    def test_partial_post_failure_returns_distinct_exit_code(
        self, tmp_blurb, capsys, monkeypatch,
    ):
        """If some guilds succeed and others fail, exit code 2
        (partial). 0 = full success, 1 = setup error, 2 = some
        guilds didn't get the post — distinct so a wrapper can
        branch."""
        monkeypatch.setattr(
            "sys.argv",
            ["post_patch_notes.py", "--post", "--file", str(tmp_blurb)],
        )
        targets = [
            {"guild_id": 1, "name": "Alpha", "channel_id": 100},
            {"guild_id": 2, "name": "Beta", "channel_id": 200},
        ]

        async def fake_post_one_succeeds(content, ts, token, db_env_var):
            return 1

        with (
            patch("tools.post_patch_notes.use_db_env_var"),
            patch("tools.post_patch_notes._find_announcement_targets", return_value=targets),
            patch("tools.post_patch_notes.get_auth", return_value={"TOKEN": "xyz"}),
            patch("tools.post_patch_notes._post_to_targets", side_effect=fake_post_one_succeeds),
        ):
            rc = post_patch_notes.main()

        assert rc == 2

    def test_db_env_var_arg_drives_use_db_env_var_call(
        self, tmp_blurb, monkeypatch,
    ):
        """The positional arg routes through to ``use_db_env_var``
        so the operator's choice of DB actually takes effect.
        Without this wiring, every invocation would silently
        target whatever LIVE_DB_NAME points at."""
        monkeypatch.setattr(
            "sys.argv",
            ["post_patch_notes.py", "TEST_DB_NAME", "--file", str(tmp_blurb)],
        )
        targets = [{"guild_id": 1, "name": "Alpha", "channel_id": 100}]
        with (
            patch("tools.post_patch_notes.use_db_env_var") as use_db,
            patch("tools.post_patch_notes._find_announcement_targets", return_value=targets),
        ):
            post_patch_notes.main()

        use_db.assert_called_once_with("TEST_DB_NAME")
