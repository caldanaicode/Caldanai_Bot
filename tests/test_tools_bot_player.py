"""Tests for tools/bot_player.py.

Covers the channel-id resolution logic and the env-var token
requirement. The Discord POST path itself is delegated to
:class:`tools._common.DiscordRestClient` — tested elsewhere."""

import os
from unittest.mock import MagicMock, patch

import pytest

from tools.bot_player import (
    _resolve_observations_channel_id,
    _resolve_ooc_channel_id,
    _resolve_test_channel_id,
    _split_thread_file,
    main,
)


class TestResolveTestChannelId:
    @pytest.fixture(autouse=True)
    def _clear_pin_env(self):
        """Ensure BOT_PLAYER_CHANNEL_ID isn't leaked from the runner's
        environment into tests that exercise the DB lookup path —
        the env var would short-circuit the lookup and mask test
        behavior."""
        saved = os.environ.pop("BOT_PLAYER_CHANNEL_ID", None)
        try:
            yield
        finally:
            if saved is not None:
                os.environ["BOT_PLAYER_CHANNEL_ID"] = saved

    def test_single_game_resolves(self):
        fake_game = {"channel_id": 123456789, "guild_id": 111}
        fake_db = MagicMock()
        fake_db.games.find.return_value = [fake_game]

        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
        ):
            assert _resolve_test_channel_id() == 123456789

    def test_no_game_raises(self):
        fake_db = MagicMock()
        fake_db.games.find.return_value = []

        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
        ):
            with pytest.raises(SystemExit, match="No game found"):
                _resolve_test_channel_id()

    def test_multiple_games_without_guild_filter_raises(self):
        fake_db = MagicMock()
        fake_db.games.find.return_value = [
            {"channel_id": 1, "guild_id": 10},
            {"channel_id": 2, "guild_id": 20},
        ]

        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
        ):
            with pytest.raises(SystemExit, match="Multiple games"):
                _resolve_test_channel_id()

    def test_guild_filter_narrows_to_one(self):
        fake_db = MagicMock()
        fake_db.games.find.return_value = [
            {"channel_id": 2, "guild_id": 20},
        ]

        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
        ):
            assert _resolve_test_channel_id(guild_filter=20) == 2
            # And the query included the guild filter.
            args, _ = fake_db.games.find.call_args
            assert args[0].get("guild_id") == 20

    def test_pinned_env_var_short_circuits_db_lookup(self):
        """``BOT_PLAYER_CHANNEL_ID`` env var is the highest-priority
        default channel resolver — when set, the DB lookup is skipped
        entirely. Workspace-pinning mode for bg Vael's launcher."""
        fake_db = MagicMock()
        fake_db.games.find.side_effect = AssertionError(
            "DB lookup should not be called when env var is set"
        )
        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
            patch.dict(
                "os.environ",
                {"BOT_PLAYER_CHANNEL_ID": "111111111111111111"},
            ),
        ):
            assert _resolve_test_channel_id() == 111111111111111111

    def test_pinned_env_var_invalid_raises(self):
        with patch.dict(
            "os.environ", {"BOT_PLAYER_CHANNEL_ID": "not-a-number"}
        ):
            with pytest.raises(SystemExit, match="not a valid integer"):
                _resolve_test_channel_id()

    def test_ooc_channel_excluded_from_default_lookup(self):
        """When OOC_CHANNEL_ID is set, the default DB lookup
        excludes that channel via $ne so existing flows
        (bg Vael's no-flag bot_player send) keep landing on the
        Vael-facing test channel even after a second game is
        registered for the OOC engineering channel."""
        fake_db = MagicMock()
        # Only return the Vael channel; the test asserts the OOC
        # filter went into the query.
        fake_db.games.find.return_value = [
            {"channel_id": 111111111111111111, "guild_id": 10},
        ]

        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
            patch.dict(
                "os.environ",
                {"OOC_CHANNEL_ID": "222222222222222222"},
            ),
        ):
            result = _resolve_test_channel_id()
            assert result == 111111111111111111
            args, _ = fake_db.games.find.call_args
            cid_filter = args[0].get("channel_id")
            assert isinstance(cid_filter, dict)
            assert cid_filter.get("$ne") == 222222222222222222


class TestResolveOocChannelId:
    def test_ooc_resolves_from_env(self):
        with patch.dict(
            "os.environ", {"OOC_CHANNEL_ID": "222222222222222222"}
        ):
            assert _resolve_ooc_channel_id() == 222222222222222222

    def test_ooc_missing_env_raises(self):
        saved = os.environ.pop("OOC_CHANNEL_ID", None)
        try:
            with pytest.raises(SystemExit, match="OOC_CHANNEL_ID"):
                _resolve_ooc_channel_id()
        finally:
            if saved is not None:
                os.environ["OOC_CHANNEL_ID"] = saved

    def test_ooc_invalid_env_raises(self):
        with patch.dict("os.environ", {"OOC_CHANNEL_ID": "not-a-number"}):
            with pytest.raises(SystemExit, match="not a valid integer"):
                _resolve_ooc_channel_id()


class TestResolveObservationsChannelId:
    def test_obs_resolves_from_env(self):
        with patch.dict(
            "os.environ", {"OBSERVATIONS_CHANNEL_ID": "333333333333333333"}
        ):
            assert _resolve_observations_channel_id() == 333333333333333333

    def test_obs_missing_env_raises(self):
        saved = os.environ.pop("OBSERVATIONS_CHANNEL_ID", None)
        try:
            with pytest.raises(SystemExit, match="OBSERVATIONS_CHANNEL_ID"):
                _resolve_observations_channel_id()
        finally:
            if saved is not None:
                os.environ["OBSERVATIONS_CHANNEL_ID"] = saved

    def test_obs_invalid_env_raises(self):
        with patch.dict(
            "os.environ", {"OBSERVATIONS_CHANNEL_ID": "not-a-number"}
        ):
            with pytest.raises(SystemExit, match="not a valid integer"):
                _resolve_observations_channel_id()


class TestWorkspaceMinimalMode:
    """When BOT_PLAYER_CHANNEL_ID is set (workspace mode), the
    engineering-side surface is hidden from argparse — the
    --ooc / --obs flags and the thread subcommand simply don't
    exist. Verifies the conditional surface holds."""

    def test_thread_subcommand_missing_in_minimal_mode(self, capsys):
        with patch.dict(
            "os.environ", {"BOT_PLAYER_CHANNEL_ID": "111111111111111111"}
        ):
            with pytest.raises(SystemExit):
                main(["thread", "ignored.md"])
        err = capsys.readouterr().err
        assert "invalid choice: 'thread'" in err

    def test_ooc_flag_missing_in_minimal_mode(self, capsys):
        with patch.dict(
            "os.environ", {"BOT_PLAYER_CHANNEL_ID": "111111111111111111"}
        ):
            with pytest.raises(SystemExit):
                main(["send", "$health", "--ooc"])
        err = capsys.readouterr().err
        assert "unrecognized arguments: --ooc" in err

    def test_obs_flag_missing_in_minimal_mode(self, capsys):
        with patch.dict(
            "os.environ", {"BOT_PLAYER_CHANNEL_ID": "111111111111111111"}
        ):
            with pytest.raises(SystemExit):
                main(["send", "$health", "--obs"])
        err = capsys.readouterr().err
        assert "unrecognized arguments: --obs" in err

    def test_send_still_works_in_minimal_mode(self, capsys):
        """The minimal subset (send/react/edit + --channel-id /
        --guild) stays functional. Verified at the parser level
        — actual send is mocked elsewhere."""
        # Use an invalid token to bail early but verify argparse
        # accepts the args.
        saved = os.environ.pop("CLAUDE_TESTER_TOKEN", None)
        try:
            with patch.dict(
                "os.environ",
                {"BOT_PLAYER_CHANNEL_ID": "111111111111111111"},
            ):
                with pytest.raises(SystemExit, match="CLAUDE_TESTER_TOKEN"):
                    main(["send", "$health"])
        finally:
            if saved is not None:
                os.environ["CLAUDE_TESTER_TOKEN"] = saved


class TestSplitThreadFile:
    def test_basic_split(self):
        text = "first message\n\n---\n\nsecond message\n"
        chunks = _split_thread_file(text)
        assert chunks == ["first message", "second message"]

    def test_strips_leading_and_trailing_separators(self):
        text = "---\nfirst\n---\nsecond\n---\n"
        chunks = _split_thread_file(text)
        assert chunks == ["first", "second"]

    def test_drops_empty_chunks(self):
        text = "alpha\n---\n\n   \n---\nbeta\n"
        chunks = _split_thread_file(text)
        assert chunks == ["alpha", "beta"]

    def test_inline_dashes_preserved(self):
        """Only LINE-anchored ``---`` (a line containing only dashes,
        possibly with trailing whitespace) is a separator. Inline
        em-dashes or mid-line ``---`` stay in the content."""
        text = (
            "first message — has em-dash\n"
            "---\n"
            "second message has --- inline but the line has more\n"
        )
        chunks = _split_thread_file(text)
        assert len(chunks) == 2
        assert "em-dash" in chunks[0]
        assert "--- inline" in chunks[1]

    def test_separator_with_trailing_whitespace(self):
        text = "alpha\n---   \nbeta\n"
        chunks = _split_thread_file(text)
        assert chunks == ["alpha", "beta"]

    def test_no_separator_returns_single_chunk(self):
        text = "just one message with no separators here\n"
        chunks = _split_thread_file(text)
        assert chunks == ["just one message with no separators here"]

    def test_empty_input(self):
        assert _split_thread_file("") == []
        assert _split_thread_file("   \n\n  \n") == []


class TestThreadCliDryRun:
    def test_thread_dry_run_prints_chunks(self, tmp_path, capsys):
        f = tmp_path / "thread.md"
        f.write_text("alpha\n---\nbeta\n", encoding="utf-8")
        rc = main(["thread", str(f), "--channel-id", "999", "--dry-run"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "chunk 1/2" in out
        assert "chunk 2/2" in out
        assert "alpha" in out
        assert "beta" in out

    def test_thread_cleanup_flag_deletes_file_on_success(
        self, tmp_path, monkeypatch
    ):
        """``--cleanup`` should unlink the source file after a
        successful post. Mocks out the actual Discord call so this
        runs offline."""
        import asyncio
        f = tmp_path / "thread.md"
        f.write_text("alpha\n---\nbeta\n", encoding="utf-8")

        # Stub _post_thread to return fake post results without
        # hitting Discord.
        async def fake_post_thread(*_args, **_kw):
            return [
                {"id": "1", "channel_id": "999"},
                {"id": "2", "channel_id": "999"},
            ]

        monkeypatch.setattr(
            "tools.bot_player._post_thread", fake_post_thread
        )

        rc = main([
            "thread", str(f),
            "--channel-id", "999",
            "--cleanup",
        ])
        assert rc == 0
        assert not f.exists(), "cleanup should have deleted the file"

    def test_thread_cleanup_failure_logs_warning(
        self, tmp_path, monkeypatch, capsys
    ):
        """If the unlink fails (e.g. file already gone, permission
        error), the tool should log a warning but not error out —
        the post already succeeded."""
        import asyncio
        f = tmp_path / "thread.md"
        f.write_text("alpha\n", encoding="utf-8")

        async def fake_post_thread(*_args, **_kw):
            return [{"id": "1", "channel_id": "999"}]

        monkeypatch.setattr(
            "tools.bot_player._post_thread", fake_post_thread
        )

        # Force unlink to fail by deleting the file before main runs
        # cleanup, then invoking with --cleanup. main reads the file
        # for chunks first (so we need it to exist for that step),
        # so this is a slightly different setup: monkeypatch
        # Path.unlink to raise.
        from pathlib import Path as _RealPath
        original_unlink = _RealPath.unlink

        def failing_unlink(self, *a, **kw):
            raise OSError("permission denied")

        monkeypatch.setattr(_RealPath, "unlink", failing_unlink)

        rc = main([
            "thread", str(f),
            "--channel-id", "999",
            "--cleanup",
        ])
        assert rc == 0  # post succeeded, cleanup failure is non-fatal
        err = capsys.readouterr().err
        assert "warning" in err.lower()

    def test_thread_empty_file_errors(self, tmp_path, capsys):
        f = tmp_path / "empty.md"
        f.write_text("\n   \n", encoding="utf-8")
        rc = main(["thread", str(f), "--channel-id", "999", "--dry-run"])
        assert rc == 1
        err = capsys.readouterr().err
        assert "No messages parsed" in err


class TestMainCliGuards:
    def test_missing_token_exits(self):
        # Save + strip token so the tool sees it missing.
        saved = os.environ.pop("CLAUDE_TESTER_TOKEN", None)
        try:
            with pytest.raises(SystemExit, match="CLAUDE_TESTER_TOKEN"):
                main(["send", "$hello"])
        finally:
            if saved is not None:
                os.environ["CLAUDE_TESTER_TOKEN"] = saved

    def test_send_requires_content(self):
        # argparse exits with code 2 on missing required positional.
        with pytest.raises(SystemExit):
            main(["send"])
