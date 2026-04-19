"""Tests for ``tools/tail_channel.py``.

Game discovery + picker + formatting. The Discord REST client
itself is covered in ``test_tools_common.py``; these tests pin
the tool-specific behavior: games-collection query shape,
guild-name fallback, channel hydration (including thread parent
resolution), picker branching, and message-rendering for
paste-back.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from tools import tail_channel


def _msg(message_id: str, ts: str, author: str, content: str) -> dict:
    return {
        "id": message_id,
        "timestamp": ts,
        "author": {"global_name": author, "username": author},
        "content": content,
    }


# ---------------------------------------------------------------------------
# _find_games — Mongo query shape + guild filter
# ---------------------------------------------------------------------------


class TestFindGames:
    def test_returns_all_games_when_no_filter(self):
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.games.find.return_value = [
                {"guild_id": 1, "channel_id": 100},
                {"guild_id": 2, "channel_id": 200},
            ]
            live_db.return_value = db

            games = tail_channel._find_games(None)

        assert games == [
            {"guild_id": 1, "channel_id": 100},
            {"guild_id": 2, "channel_id": 200},
        ]
        db.games.find.assert_called_once()
        query = db.games.find.call_args.args[0]
        assert "guild_id" not in query or isinstance(query["guild_id"], dict)

    def test_narrows_to_guild_when_filter_provided(self):
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.games.find.return_value = [{"guild_id": 42, "channel_id": 999}]
            live_db.return_value = db

            games = tail_channel._find_games(42)

        assert games == [{"guild_id": 42, "channel_id": 999}]
        query = db.games.find.call_args.args[0]
        assert query["guild_id"] == 42

    def test_coerces_ids_to_ints(self):
        """Mongo might store these as strings or Long64 depending
        on the write path; the tool canonicalizes to plain int."""
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.games.find.return_value = [{"guild_id": "7", "channel_id": "77"}]
            live_db.return_value = db

            games = tail_channel._find_games(None)

        assert games == [{"guild_id": 7, "channel_id": 77}]


# ---------------------------------------------------------------------------
# _guild_name_lookup
# ---------------------------------------------------------------------------


class TestGuildNameLookup:
    def test_empty_set_returns_empty_map(self):
        assert tail_channel._guild_name_lookup(set()) == {}

    def test_maps_ids_to_names_from_servers_collection(self):
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = [
                {"guild_id": 1, "name": "Alpha"},
                {"guild_id": 2, "name": "Beta"},
            ]
            live_db.return_value = db

            names = tail_channel._guild_name_lookup({1, 2})

        assert names == {1: "Alpha", 2: "Beta"}

    def test_falls_back_to_placeholder_when_server_doc_missing(self):
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = []  # nothing registered
            live_db.return_value = db

            names = tail_channel._guild_name_lookup({99})

        assert 99 in names
        assert "99" in names[99]  # includes id in the fallback label

    def test_missing_name_field_also_falls_back(self):
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.servers.find.return_value = [{"guild_id": 5}]  # no 'name'
            live_db.return_value = db

            names = tail_channel._guild_name_lookup({5})

        assert "5" in names[5]


# ---------------------------------------------------------------------------
# _resolve_channel — delegates to client.get_channel, graceful on errors
# ---------------------------------------------------------------------------


class TestResolveChannel:
    @pytest.mark.asyncio
    async def test_returns_compact_dict_on_success(self):
        client = MagicMock()
        client.get_channel = AsyncMock(return_value={
            "name": "arena", "type": 0, "parent_id": None,
        })

        info = await tail_channel._resolve_channel(client, 1234)

        assert info == {"name": "arena", "type": 0, "parent_id": None}
        client.get_channel.assert_awaited_once_with(1234)

    @pytest.mark.asyncio
    async def test_unnamed_channel_gets_placeholder(self):
        client = MagicMock()
        client.get_channel = AsyncMock(return_value={
            "name": None, "type": 0, "parent_id": None,
        })

        info = await tail_channel._resolve_channel(client, 1)

        assert info["name"] == "<no-name>"

    @pytest.mark.asyncio
    async def test_client_error_returns_unavailable_placeholder(self):
        """A deleted / forbidden / network-error channel should not
        abort the whole tool — it should render a line the operator
        can still reason about."""
        client = MagicMock()
        client.get_channel = AsyncMock(
            side_effect=aiohttp.ClientError("404")
        )

        info = await tail_channel._resolve_channel(client, 7)

        assert info["type"] is None
        assert "unavailable" in info["name"]


# ---------------------------------------------------------------------------
# _hydrate_games — threads resolve parent names, non-threads don't
# ---------------------------------------------------------------------------


class TestHydrateGames:
    @pytest.mark.asyncio
    async def test_non_thread_channels_leave_parent_name_none(self):
        client = MagicMock()
        client.get_channel = AsyncMock(return_value={
            "name": "arena", "type": 0, "parent_id": None,
        })

        hydrated = await tail_channel._hydrate_games(
            client, [{"guild_id": 1, "channel_id": 100}],
        )

        assert hydrated[0]["channel_name"] == "arena"
        assert hydrated[0]["channel_type"] == 0
        assert hydrated[0]["parent_name"] is None

    @pytest.mark.asyncio
    async def test_thread_channel_resolves_parent_name(self):
        """A thread (type 11) with a parent_id should get the
        parent channel's name attached for picker clarity."""
        async def fake_get_channel(channel_id):
            if channel_id == 100:  # the thread
                return {"name": "dungeon-caves", "type": 11, "parent_id": "50"}
            if channel_id == 50:   # its parent
                return {"name": "main-hall", "type": 0, "parent_id": None}
            raise AssertionError(f"Unexpected channel_id {channel_id}")

        client = MagicMock()
        client.get_channel = AsyncMock(side_effect=fake_get_channel)

        hydrated = await tail_channel._hydrate_games(
            client, [{"guild_id": 1, "channel_id": 100}],
        )

        assert hydrated[0]["channel_name"] == "dungeon-caves"
        assert hydrated[0]["parent_name"] == "main-hall"


# ---------------------------------------------------------------------------
# _format_game_choice — picker line formatting
# ---------------------------------------------------------------------------


class TestFormatGameChoice:
    def test_non_thread_shows_channel_name_only(self):
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "arena",
            "channel_type": 0,
            "parent_name": None,
        }
        line = tail_channel._format_game_choice(game, {1: "Alpha"})

        assert "Alpha" in line
        assert "#arena" in line
        assert "100" in line
        assert "thread" not in line.lower()

    def test_thread_labels_parent(self):
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "dungeon-caves",
            "channel_type": 11,
            "parent_name": "main-hall",
        }
        line = tail_channel._format_game_choice(game, {1: "Alpha"})

        assert "#dungeon-caves" in line
        assert "thread of #main-hall" in line


# ---------------------------------------------------------------------------
# _pick_game — auto-pick single, interactive otherwise
# ---------------------------------------------------------------------------


class TestPickGame:
    def test_single_game_auto_returns_without_prompt(self):
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "arena",
            "channel_type": 0,
            "parent_name": None,
        }
        # No input() patch — test fails loudly if auto-pick doesn't fire.
        with patch("builtins.input", side_effect=AssertionError(
            "auto-pick should not prompt on a single candidate"
        )):
            picked = tail_channel._pick_game([game], {1: "Alpha"})
        assert picked is game

    def test_multiple_games_prompts_and_accepts_valid_index(self):
        games = [
            {"guild_id": 1, "channel_id": 100, "channel_name": "a",
             "channel_type": 0, "parent_name": None},
            {"guild_id": 1, "channel_id": 200, "channel_name": "b",
             "channel_type": 0, "parent_name": None},
        ]
        with patch("builtins.input", return_value="2"):
            picked = tail_channel._pick_game(games, {1: "Alpha"})
        assert picked is games[1]

    def test_quit_returns_none(self):
        games = [
            {"guild_id": 1, "channel_id": 100, "channel_name": "a",
             "channel_type": 0, "parent_name": None},
            {"guild_id": 1, "channel_id": 200, "channel_name": "b",
             "channel_type": 0, "parent_name": None},
        ]
        with patch("builtins.input", return_value="q"):
            assert tail_channel._pick_game(games, {1: "Alpha"}) is None

    def test_invalid_then_valid_input(self):
        games = [
            {"guild_id": 1, "channel_id": 100, "channel_name": "a",
             "channel_type": 0, "parent_name": None},
            {"guild_id": 1, "channel_id": 200, "channel_name": "b",
             "channel_type": 0, "parent_name": None},
        ]
        with patch("builtins.input", side_effect=["banana", "5", "1"]):
            picked = tail_channel._pick_game(games, {1: "Alpha"})
        assert picked is games[0]

    def test_eof_returns_none(self):
        games = [
            {"guild_id": 1, "channel_id": 100, "channel_name": "a",
             "channel_type": 0, "parent_name": None},
            {"guild_id": 1, "channel_id": 200, "channel_name": "b",
             "channel_type": 0, "parent_name": None},
        ]
        with patch("builtins.input", side_effect=EOFError):
            assert tail_channel._pick_game(games, {1: "Alpha"}) is None


# ---------------------------------------------------------------------------
# _format_message / _format_header / _format_initial
# ---------------------------------------------------------------------------


class TestFormatMessage:
    def test_renders_author_timestamp_and_quoted_body(self):
        msg = _msg("1", "2026-04-18T20:00:00Z", "Caels", "hello\nworld")
        lines = tail_channel._format_message(msg)

        assert any("2026-04-18T20:00:00Z" in l for l in lines)
        assert any("@Caels" in l for l in lines)
        assert any(l.strip() == "> hello" for l in lines)
        assert any(l.strip() == "> world" for l in lines)

    def test_empty_content_and_no_embeds_gets_placeholder(self):
        msg = _msg("1", "ts", "Caels", "")
        lines = tail_channel._format_message(msg)

        assert any("no text or embed content" in l for l in lines)

    def test_embed_only_message_renders_embed_content(self):
        """Spawn cards / $stats / $inventory are embed-only — the
        renderer now surfaces embed title/fields instead of the
        'no content' placeholder."""
        msg = {
            "id": "1",
            "timestamp": "ts",
            "author": {"global_name": "Caldanai Test"},
            "content": "",
            "embeds": [{
                "title": "Dragon",
                "description": "A huge red dragon.",
                "fields": [
                    {"name": "Size", "value": "Huge"},
                    {"name": "Health", "value": "158 / 158"},
                ],
            }],
        }
        lines = tail_channel._format_message(msg)
        joined = "\n".join(lines)

        assert "Dragon" in joined
        assert "A huge red dragon." in joined
        assert "Size: Huge" in joined
        assert "Health: 158 / 158" in joined
        assert "no text or embed content" not in joined

    def test_missing_author_falls_back_to_unknown(self):
        msg = {"id": "1", "timestamp": "ts", "content": "hi"}
        lines = tail_channel._format_message(msg)

        assert any("@<unknown>" in l for l in lines)


# ---------------------------------------------------------------------------
# _render_embeds — flatten Discord embed objects to plain text
# ---------------------------------------------------------------------------


class TestRenderEmbeds:
    def test_empty_list_returns_empty_string(self):
        assert tail_channel._render_embeds([]) == ""
        assert tail_channel._render_embeds(None or []) == ""

    def test_title_description_and_fields_in_order(self):
        embeds = [{
            "title": "Dragon",
            "description": "Fearsome.",
            "fields": [
                {"name": "Size", "value": "Huge"},
                {"name": "Attack", "value": "3d10"},
            ],
        }]
        out = tail_channel._render_embeds(embeds)

        title_idx = out.index("Dragon")
        desc_idx = out.index("Fearsome.")
        size_idx = out.index("Size: Huge")
        atk_idx = out.index("Attack: 3d10")
        assert title_idx < desc_idx < size_idx < atk_idx

    def test_title_only_embed(self):
        out = tail_channel._render_embeds([{"title": "Notice"}])
        assert "Notice" in out

    def test_description_only_embed(self):
        out = tail_channel._render_embeds([{"description": "hello"}])
        assert out.strip() == "hello"

    def test_fields_only_embed(self):
        embeds = [{"fields": [{"name": "HP", "value": "20"}]}]
        assert tail_channel._render_embeds(embeds) == "HP: 20"

    def test_fields_with_missing_name_or_value(self):
        embeds = [{"fields": [
            {"name": "", "value": "orphan-value"},
            {"name": "orphan-name", "value": ""},
            {"name": "paired", "value": "ok"},
        ]}]
        out = tail_channel._render_embeds(embeds)
        assert "orphan-value" in out
        assert "orphan-name" in out
        assert "paired: ok" in out

    def test_author_and_footer_included(self):
        embeds = [{
            "author": {"name": "Caldanai"},
            "title": "Loot",
            "footer": {"text": "Roll to claim"},
        }]
        out = tail_channel._render_embeds(embeds)
        assert "Caldanai" in out
        assert "Loot" in out
        assert "Roll to claim" in out

    def test_multiple_embeds_separated_by_blank_line(self):
        embeds = [
            {"title": "First"},
            {"title": "Second"},
        ]
        out = tail_channel._render_embeds(embeds)
        assert "**First**\n\n**Second**" in out

    def test_empty_embed_skipped(self):
        embeds = [
            {"title": "kept"},
            {},  # all fields missing
        ]
        assert tail_channel._render_embeds(embeds) == "**kept**"


# ---------------------------------------------------------------------------
# _message_content — text + embed folding
# ---------------------------------------------------------------------------


class TestMessageContent:
    def test_text_only(self):
        msg = _msg("1", "ts", "Caels", "hello")
        assert tail_channel._message_content(msg) == "hello"

    def test_embed_only(self):
        msg = {"content": "", "embeds": [{"title": "Dragon"}]}
        assert tail_channel._message_content(msg) == "**Dragon**"

    def test_text_plus_embed_concatenated_with_blank_line(self):
        """Rare but possible — preserve both so the reader can tell
        the two sources apart."""
        msg = {
            "content": "front-matter",
            "embeds": [{"title": "Dragon"}],
        }
        out = tail_channel._message_content(msg)
        assert "front-matter" in out
        assert "**Dragon**" in out
        assert "front-matter\n\n**Dragon**" == out

    def test_no_content_no_embeds_returns_empty(self):
        msg = {"content": "", "embeds": []}
        assert tail_channel._message_content(msg) == ""


class TestFormatHeader:
    def test_with_guild_context(self):
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "arena",
            "channel_type": 0,
            "parent_name": None,
        }
        header = tail_channel._format_header(game, {1: "Alpha"})

        assert "#arena" in header
        assert "Alpha" in header
        assert "channel_id 100" in header

    def test_without_guild_context_omits_guild_segment(self):
        """When ``--channel-id`` is used without ``--guild``, the
        header should skip the guild segment rather than rendering
        ``guild '0' (0)``."""
        game = {
            "guild_id": 0,
            "channel_id": 100,
            "channel_name": "arena",
            "channel_type": 0,
            "parent_name": None,
        }
        header = tail_channel._format_header(game, {})

        assert "guild" not in header.lower()
        assert "#arena" in header

    def test_thread_header_labels_parent(self):
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "dungeon-caves",
            "channel_type": 11,
            "parent_name": "main-hall",
        }
        header = tail_channel._format_header(game, {1: "Alpha"})

        assert "thread of #main-hall" in header


class TestFormatInitial:
    def test_empty_channel_renders_explicit_note(self):
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "arena",
            "channel_type": 0,
            "parent_name": None,
        }
        out = tail_channel._format_initial(game, {1: "Alpha"}, [])
        assert "no messages" in out.lower()

    def test_messages_render_chronologically(self):
        """Discord returns newest-first; the initial block must
        reverse to chronological so a reader follows the
        conversation top-down."""
        game = {
            "guild_id": 1,
            "channel_id": 100,
            "channel_name": "arena",
            "channel_type": 0,
            "parent_name": None,
        }
        messages = [
            _msg("3", "2026-04-18T20:02:00Z", "Caels", "third"),
            _msg("2", "2026-04-18T20:01:00Z", "Caels", "second"),
            _msg("1", "2026-04-18T20:00:00Z", "Caels", "first"),
        ]
        out = tail_channel._format_initial(game, {1: "Alpha"}, messages)

        first_idx = out.index("first")
        second_idx = out.index("second")
        third_idx = out.index("third")
        assert first_idx < second_idx < third_idx


# ---------------------------------------------------------------------------
# TailBuffer — ring buffer + dropped_count
# ---------------------------------------------------------------------------


class TestTailBuffer:
    def test_append_adds_entries(self):
        buf = tail_channel.TailBuffer(maxsize=10)
        buf.append({"id": "1", "content": "first"})
        buf.append({"id": "2", "content": "second"})
        snap = buf.snapshot()
        assert len(snap["messages"]) == 2
        assert snap["messages"][0]["id"] == "1"
        assert snap["messages"][1]["id"] == "2"
        assert snap["dropped_count"] == 0

    def test_rolls_oldest_when_full(self):
        buf = tail_channel.TailBuffer(maxsize=3)
        for i in range(5):
            buf.append({"id": str(i), "content": f"m{i}"})
        snap = buf.snapshot()
        ids = [m["id"] for m in snap["messages"]]
        assert ids == ["2", "3", "4"]

    def test_dropped_count_matches_overflow(self):
        buf = tail_channel.TailBuffer(maxsize=3)
        for i in range(7):
            buf.append({"id": str(i)})
        assert buf.snapshot()["dropped_count"] == 4

    def test_snapshot_exposes_size_and_max(self):
        buf = tail_channel.TailBuffer(maxsize=500)
        buf.append({"id": "1"})
        buf.append({"id": "2"})
        snap = buf.snapshot()
        assert snap["buffer_size"] == 2
        assert snap["buffer_max"] == 500

    def test_snapshot_since_filters_to_newer_ids(self):
        buf = tail_channel.TailBuffer(maxsize=10)
        for i in range(1, 6):
            buf.append({"id": str(i)})
        snap = buf.snapshot(since_id=3)
        ids = [m["id"] for m in snap["messages"]]
        assert ids == ["4", "5"]

    def test_snapshot_since_none_returns_everything(self):
        buf = tail_channel.TailBuffer(maxsize=10)
        buf.append({"id": "1"})
        buf.append({"id": "2"})
        assert len(buf.snapshot(since_id=None)["messages"]) == 2

    def test_snapshot_keeps_entries_without_numeric_id(self):
        """Degraded entries (missing or non-integer id) shouldn't
        disappear when the caller filters by ``since`` — dropping them
        silently would hide events."""
        buf = tail_channel.TailBuffer(maxsize=10)
        buf.append({"id": None, "content": "mystery"})
        buf.append({"id": "100", "content": "with_id"})
        snap = buf.snapshot(since_id=50)
        contents = [m["content"] for m in snap["messages"]]
        assert "mystery" in contents
        assert "with_id" in contents


# ---------------------------------------------------------------------------
# _make_buffer_entry — compact shape for the ring buffer
# ---------------------------------------------------------------------------


class TestMakeBufferEntry:
    def test_extracts_four_canonical_fields(self):
        msg = _msg("1", "ts", "Caels", "hello")
        entry = tail_channel._make_buffer_entry(msg)
        assert set(entry.keys()) == {"id", "timestamp", "author", "content"}
        assert entry["id"] == "1"
        assert entry["timestamp"] == "ts"
        assert entry["author"] == "Caels"
        assert entry["content"] == "hello"

    def test_prefers_global_name_then_username(self):
        msg = {
            "id": "1", "timestamp": "ts",
            "author": {"username": "username_only"},
            "content": "hi",
        }
        assert tail_channel._make_buffer_entry(msg)["author"] == "username_only"

    def test_missing_author_falls_back(self):
        msg = {"id": "1", "timestamp": "ts", "content": "hi"}
        assert tail_channel._make_buffer_entry(msg)["author"] == "<unknown>"

    def test_strips_whitespace_from_content(self):
        msg = _msg("1", "ts", "Caels", "  padded  \n")
        assert tail_channel._make_buffer_entry(msg)["content"] == "padded"


# ---------------------------------------------------------------------------
# HTTP handler — JSON shape + since= validation
# ---------------------------------------------------------------------------


class TestTailHandler:
    @pytest.mark.asyncio
    async def test_returns_snapshot_json(self):
        from aiohttp.test_utils import make_mocked_request

        buf = tail_channel.TailBuffer(maxsize=10)
        buf.append({"id": "1", "content": "first"})
        buf.append({"id": "2", "content": "second"})
        handler = tail_channel._make_tail_handler(buf)

        request = make_mocked_request("GET", "/tail")
        response = await handler(request)

        assert response.status == 200
        import json
        payload = json.loads(response.body)
        assert payload["buffer_size"] == 2
        assert payload["buffer_max"] == 10
        assert payload["dropped_count"] == 0
        assert len(payload["messages"]) == 2

    @pytest.mark.asyncio
    async def test_since_param_filters(self):
        from aiohttp.test_utils import make_mocked_request

        buf = tail_channel.TailBuffer(maxsize=10)
        for i in range(1, 6):
            buf.append({"id": str(i)})
        handler = tail_channel._make_tail_handler(buf)

        request = make_mocked_request("GET", "/tail?since=3")
        response = await handler(request)

        import json
        payload = json.loads(response.body)
        ids = [m["id"] for m in payload["messages"]]
        assert ids == ["4", "5"]

    @pytest.mark.asyncio
    async def test_invalid_since_returns_400(self):
        from aiohttp.test_utils import make_mocked_request

        buf = tail_channel.TailBuffer(maxsize=10)
        handler = tail_channel._make_tail_handler(buf)

        request = make_mocked_request("GET", "/tail?since=not-a-number")
        response = await handler(request)

        assert response.status == 400
        import json
        payload = json.loads(response.body)
        assert "error" in payload
