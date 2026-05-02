"""Tests for tools/bot_player.py.

Covers the channel-id resolution logic and the env-var token
requirement. The Discord POST path itself is delegated to
:class:`tools._common.DiscordRestClient` — tested elsewhere."""

import os
from unittest.mock import MagicMock, patch

import pytest

from tools.bot_player import (
    _resolve_ooc_channel_id,
    _resolve_test_channel_id,
    main,
)


class TestResolveTestChannelId:
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
            {"channel_id": 1269749688496558161, "guild_id": 10},
        ]

        with (
            patch("tools.bot_player.use_db_env_var"),
            patch("tools.bot_player.live_db", return_value=fake_db),
            patch.dict(
                "os.environ",
                {"OOC_CHANNEL_ID": "1500205779184255146"},
            ),
        ):
            result = _resolve_test_channel_id()
            assert result == 1269749688496558161
            args, _ = fake_db.games.find.call_args
            cid_filter = args[0].get("channel_id")
            assert isinstance(cid_filter, dict)
            assert cid_filter.get("$ne") == 1500205779184255146


class TestResolveOocChannelId:
    def test_ooc_resolves_from_env(self):
        with patch.dict(
            "os.environ", {"OOC_CHANNEL_ID": "1500205779184255146"}
        ):
            assert _resolve_ooc_channel_id() == 1500205779184255146

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
