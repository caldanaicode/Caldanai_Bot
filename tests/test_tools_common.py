"""Tests for ``tools/_common.py`` — the shared helpers backing
the standalone tooling scripts.

Covers:
- Live-DB lazy connection (one MongoClient per process,
  scoped to LIVE_DB_NAME regardless of STAGE).
- ``get_auth`` and ``get_guild_channels`` thin DB wrappers.
- ``resolve_channel_id`` helpful-error contract when a guild's
  channel is unconfigured.
- ``DiscordRestClient`` URL construction, auth header,
  message-post and message-fetch shapes.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import _common


@pytest.fixture(autouse=True)
def _reset_client():
    """``_common._client`` and ``_active_db_name`` are module-
    level singletons — reset between tests so each gets a fresh
    state and a stray ``use_db_env_var`` in one test doesn't
    leak into the next."""
    _common._client = None
    _common._active_db_name = None
    yield
    _common._client = None
    _common._active_db_name = None


class TestLiveDb:
    def test_returns_db_scoped_to_live_db_name(self):
        with patch("tools._common.MongoClient") as MC, \
             patch("tools._common.LIVE_DB_NAME", "live_db_name"):
            mock_client = MagicMock()
            MC.return_value = mock_client

            db = _common.live_db()

            MC.assert_called_once()
            mock_client.__getitem__.assert_called_once_with("live_db_name")
            assert db is mock_client.__getitem__.return_value

    def test_reuses_client_across_calls(self):
        """One MongoClient per process — repeated ``live_db()``
        calls should not open additional connections."""
        with patch("tools._common.MongoClient") as MC:
            MC.return_value = MagicMock()
            _common.live_db()
            _common.live_db()
            _common.live_db()
            assert MC.call_count == 1

    def test_use_db_env_var_resolves_and_targets_named_db(self, monkeypatch):
        """The CLI passes an env var name like ``"TEST_DB_NAME"``;
        ``use_db_env_var`` reads that env var and points
        subsequent ``live_db`` calls at whatever it resolves to."""
        monkeypatch.setenv("MY_DB_VAR", "resolved_db")
        with patch("tools._common.MongoClient") as MC:
            mock_client = MagicMock()
            MC.return_value = mock_client

            _common.use_db_env_var("MY_DB_VAR")
            _common.live_db()

            assert mock_client.__getitem__.call_args.args == ("resolved_db",)

    def test_use_db_env_var_resets_lazy_client(self, monkeypatch):
        """A previously-opened MongoClient may have been pointed
        at a different DB; ``use_db_env_var`` must close it and
        re-open so the next call doesn't serve a stale
        connection."""
        monkeypatch.setenv("MY_DB_VAR", "resolved_db")
        with patch("tools._common.MongoClient") as MC:
            first_client = MagicMock()
            second_client = MagicMock()
            MC.side_effect = [first_client, second_client]

            _common.live_db()  # opens first_client
            _common.use_db_env_var("MY_DB_VAR")
            _common.live_db()  # must open second_client

            first_client.close.assert_called_once()
            assert MC.call_count == 2

    def test_use_db_env_var_unset_exits_with_guidance(self, monkeypatch, capsys):
        """If the named env var isn't set, fail loudly with a
        message naming the missing var. Silent fallback would
        risk posting against the wrong DB."""
        monkeypatch.delenv("UNKNOWN_DB_VAR", raising=False)
        with pytest.raises(SystemExit) as exc:
            _common.use_db_env_var("UNKNOWN_DB_VAR")
        captured = capsys.readouterr()

        assert exc.value.code == 1
        assert "UNKNOWN_DB_VAR" in captured.err

    def test_live_db_falls_back_to_live_db_name_when_no_call_made(self):
        """Direct usage (e.g. an interactive REPL session) without
        a prior ``use_db_env_var`` falls back to ``LIVE_DB_NAME``
        so the helpers Just Work."""
        with patch("tools._common.MongoClient") as MC, \
             patch("tools._common.LIVE_DB_NAME", "live_name_default"):
            mock_client = MagicMock()
            MC.return_value = mock_client

            _common.live_db()

            assert mock_client.__getitem__.call_args.args == ("live_name_default",)


class TestGetAuth:
    def test_returns_auth_doc_when_present(self):
        with patch("tools._common.live_db") as live_db:
            db = MagicMock()
            db.auth.find_one.return_value = {"TOKEN": "abc"}
            live_db.return_value = db

            assert _common.get_auth() == {"TOKEN": "abc"}

    def test_raises_when_no_auth_doc(self):
        """Tools always need the token; missing auth doc fails
        loudly with guidance rather than returning None and
        producing a downstream AttributeError."""
        with patch("tools._common.live_db") as live_db:
            db = MagicMock()
            db.auth.find_one.return_value = None
            live_db.return_value = db

            with pytest.raises(RuntimeError, match="No auth document"):
                _common.get_auth()


class TestGetGuildChannels:
    def test_returns_channels_dict(self):
        with patch("tools._common.live_db") as live_db:
            db = MagicMock()
            db.servers.find_one.return_value = {
                "guild_id": 1,
                "channels": {"updates": 100, "ideas": 200},
            }
            live_db.return_value = db

            assert _common.get_guild_channels(1) == {"updates": 100, "ideas": 200}

    def test_empty_when_no_server_doc(self):
        with patch("tools._common.live_db") as live_db:
            db = MagicMock()
            db.servers.find_one.return_value = None
            live_db.return_value = db

            assert _common.get_guild_channels(1) == {}

    def test_empty_when_no_channels_field(self):
        with patch("tools._common.live_db") as live_db:
            db = MagicMock()
            db.servers.find_one.return_value = {"guild_id": 1, "prefix": "$"}
            live_db.return_value = db

            assert _common.get_guild_channels(1) == {}


class TestResolveChannelId:
    def test_returns_channel_id_when_configured(self):
        with patch("tools._common.get_guild_channels") as gc:
            gc.return_value = {"updates": 555}
            assert _common.resolve_channel_id(1, "updates") == 555

    def test_raises_with_setup_guidance_when_missing(self):
        """Operator-friendly error: name the missing key and the
        $config command that fixes it. Tools should fail fast
        with this message rather than silently no-op."""
        with patch("tools._common.get_guild_channels") as gc:
            gc.return_value = {}
            with pytest.raises(RuntimeError, match="\\$config ideas_channel"):
                _common.resolve_channel_id(1, "ideas")

    def test_returns_int_even_if_db_returned_string(self):
        """Defensive: if a channel id sneaks into the DB as a
        string (e.g. via Compass typing), still return an int so
        downstream f-string interpolation into URLs is consistent."""
        with patch("tools._common.get_guild_channels") as gc:
            gc.return_value = {"ideas": "12345"}
            assert _common.resolve_channel_id(1, "ideas") == 12345


class TestDiscordRestClient:
    """The REST client is a thin async wrapper around aiohttp.
    Tests pin the contract: bot-token auth header on every
    request, correct URL construction, JSON body for posts,
    and ``after`` / ``limit`` query params for fetches."""

    @pytest.mark.asyncio
    async def test_uses_bot_token_in_auth_header(self):
        """Every request goes out with ``Authorization: Bot <token>``.
        Discord rejects with 401 otherwise."""
        with patch("tools._common.aiohttp.ClientSession") as Session:
            session = MagicMock()
            session.close = AsyncMock()
            Session.return_value = session

            async with _common.DiscordRestClient("my-token"):
                pass

            Session.assert_called_once()
            headers = Session.call_args.kwargs["headers"]
            assert headers["Authorization"] == "Bot my-token"

    @pytest.mark.asyncio
    async def test_post_message_calls_correct_url_and_body(self):
        with patch("tools._common.aiohttp.ClientSession") as Session:
            session = MagicMock()
            session.close = AsyncMock()
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json = AsyncMock(return_value={"id": "999"})
            session.post.return_value.__aenter__ = AsyncMock(return_value=response)
            session.post.return_value.__aexit__ = AsyncMock(return_value=None)
            Session.return_value = session

            async with _common.DiscordRestClient("t") as client:
                result = await client.post_message(123, "hello world")

            session.post.assert_called_once()
            url = session.post.call_args.args[0]
            assert url.endswith("/channels/123/messages")
            body = session.post.call_args.kwargs["json"]
            assert body == {"content": "hello world"}
            assert result == {"id": "999"}

    @pytest.mark.asyncio
    async def test_get_messages_passes_limit_and_after_params(self):
        with patch("tools._common.aiohttp.ClientSession") as Session:
            session = MagicMock()
            session.close = AsyncMock()
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            Session.return_value = session

            async with _common.DiscordRestClient("t") as client:
                msgs = await client.get_messages(456, after=789, limit=10)

            session.get.assert_called_once()
            url = session.get.call_args.args[0]
            assert url.endswith("/channels/456/messages")
            params = session.get.call_args.kwargs["params"]
            assert params["after"] == "789"
            assert params["limit"] == 10
            assert msgs == [{"id": "1"}, {"id": "2"}]

    @pytest.mark.asyncio
    async def test_edit_message_calls_patch_with_content(self):
        """Editing PATCHes the per-message URL with a JSON body
        carrying the new content. Bots can only edit their own
        messages — Discord rejects others with 403, but the tool
        layer just propagates that as a regular ``raise_for_status``."""
        with patch("tools._common.aiohttp.ClientSession") as Session:
            session = MagicMock()
            session.close = AsyncMock()
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json = AsyncMock(return_value={"id": "999", "content": "new"})
            session.patch.return_value.__aenter__ = AsyncMock(return_value=response)
            session.patch.return_value.__aexit__ = AsyncMock(return_value=None)
            Session.return_value = session

            async with _common.DiscordRestClient("t") as client:
                result = await client.edit_message(123, 999, "new content")

            session.patch.assert_called_once()
            url = session.patch.call_args.args[0]
            assert url.endswith("/channels/123/messages/999")
            body = session.patch.call_args.kwargs["json"]
            assert body == {"content": "new content"}
            assert result["content"] == "new"

    @pytest.mark.asyncio
    async def test_get_message_returns_single_message_object(self):
        """Used by the edit tool's dry-run to show the operator
        what content will be replaced."""
        with patch("tools._common.aiohttp.ClientSession") as Session:
            session = MagicMock()
            session.close = AsyncMock()
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json = AsyncMock(return_value={"id": "999", "content": "old"})
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            Session.return_value = session

            async with _common.DiscordRestClient("t") as client:
                result = await client.get_message(123, 999)

            url = session.get.call_args.args[0]
            assert url.endswith("/channels/123/messages/999")
            assert result["content"] == "old"

    @pytest.mark.asyncio
    async def test_get_messages_clamps_limit_to_discord_bounds(self):
        """Discord rejects ``limit`` outside 1–100. The wrapper
        clamps so callers can pass any int without worrying about
        the API contract."""
        with patch("tools._common.aiohttp.ClientSession") as Session:
            session = MagicMock()
            session.close = AsyncMock()
            response = MagicMock()
            response.raise_for_status = MagicMock()
            response.json = AsyncMock(return_value=[])
            session.get.return_value.__aenter__ = AsyncMock(return_value=response)
            session.get.return_value.__aexit__ = AsyncMock(return_value=None)
            Session.return_value = session

            async with _common.DiscordRestClient("t") as client:
                await client.get_messages(1, limit=500)
                await client.get_messages(1, limit=0)

            limits = [c.kwargs["params"]["limit"] for c in session.get.call_args_list]
            assert limits == [100, 1]
