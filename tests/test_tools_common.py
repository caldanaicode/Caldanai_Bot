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


class TestSplitForDiscord:
    """Shared splitter that backs both ``post_patch_notes`` (with
    ``reserve_header=True``) and ``journal post`` (default,
    body-only). Patch-notes-specific header behavior is covered in
    ``test_tools_post_patch_notes.py``; these cover the journal-
    flavored body-only path and parameter contract."""

    def test_single_chunk_when_under_limit(self):
        content = "Short journal entry, well under the cap."
        chunks = _common.split_for_discord(content)
        assert chunks == [content]

    def test_no_header_by_default(self):
        """Default ``reserve_header=False`` treats the whole input
        as body — a leading paragraph with a trailing blank line
        is NOT auto-detected as a header to reserve for chunk 1."""
        opener = "Caels came back tonight."
        bullets = [f"Line {i}: " + ("y" * 80) for i in range(40)]
        content = opener + "\n\n" + "\n".join(bullets)
        assert len(content) > 2000

        chunks = _common.split_for_discord(content)
        assert len(chunks) >= 2
        # The opener appears once in chunk 1; chunk 2+ have neither
        # the opener nor any artificial header.
        assert chunks[0].startswith(opener)
        for chunk in chunks[1:]:
            assert opener not in chunk

    def test_reserve_header_true_keeps_header_on_chunk_one(self):
        """When opt-in via ``reserve_header=True``, the lines up to
        and including the first blank line land only in chunk 1."""
        header = "**Header — 2026-05-01**\n"
        bullets = [f"- Bullet {i}: " + ("z" * 100) for i in range(25)]
        content = header + "\n" + "\n".join(bullets)

        chunks = _common.split_for_discord(content, reserve_header=True)
        assert len(chunks) >= 2
        assert chunks[0].startswith("**Header")
        for chunk in chunks[1:]:
            assert not chunk.startswith("**Header")

    def test_lines_preserved_intact(self):
        """Splitting at line boundaries means no line is broken
        mid-text; every line in every chunk is whole."""
        lines = [f"L{i}: " + ("a" * 70) for i in range(40)]
        content = "\n".join(lines)
        chunks = _common.split_for_discord(content)
        # Concatenating all chunk lines should produce the original
        # set of lines (with rstrip on the last line of each chunk).
        rejoined = "\n".join(c.rstrip() for c in chunks)
        # All original lines are present in order.
        for line in lines:
            assert line in rejoined

    def test_chunks_under_max_chars(self):
        lines = [f"L{i}: " + ("b" * 100) for i in range(40)]
        content = "\n".join(lines)
        chunks = _common.split_for_discord(content)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_oversize_single_line_raises(self):
        """A single line longer than the limit can't be split at
        line boundaries; SystemExit so the operator can shorten
        rather than silently truncate."""
        huge = "x" * 2500
        with pytest.raises(SystemExit, match="(?i)tighten that line"):
            _common.split_for_discord(huge)

    def test_default_max_uses_module_constant(self):
        """No explicit ``max_chars`` => fall back to
        ``DISCORD_MESSAGE_LIMIT``. Pin the constant so a future
        Discord limit change is a single-point edit."""
        assert _common.DISCORD_MESSAGE_LIMIT == 2000
        content = "x" * 1999  # one under
        assert _common.split_for_discord(content) == [content]
