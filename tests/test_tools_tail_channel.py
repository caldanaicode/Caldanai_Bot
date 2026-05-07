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

    def test_ansi_codes_stripped_from_content(self):
        """$health body-parts tables come through with ANSI color
        escapes; they're noise in text views so we strip them."""
        msg = _msg("1", "ts", "Caels", "head \x1b[2;32munharmed\x1b[0m\ntorso \x1b[2;33mwounded\x1b[0m")
        out = tail_channel._message_content(msg)
        assert "\x1b" not in out
        assert "[2;32m" not in out
        assert "unharmed" in out
        assert "wounded" in out

    def test_ansi_codes_stripped_even_without_esc_prefix(self):
        """Some serialization paths drop the ESC but leave the
        bracket sequence as literal text. Handle that form too."""
        msg = _msg("1", "ts", "Caels", "head [2;32munharmed[0m")
        out = tail_channel._message_content(msg)
        assert "[2;32m" not in out
        assert "unharmed" in out

    def test_mention_map_replaces_user_mentions(self):
        msg = _msg("1", "ts", "alice", "<@!111111111111111111> took damage")
        out = tail_channel._message_content(
            msg, mention_map={111111111111111111: "alice"},
        )
        assert "@alice took damage" in out
        assert "<@!111111111111111111>" not in out

    def test_unknown_mention_left_as_raw(self):
        """Non-player mentions (bot roles, future users) stay as
        raw snowflakes so the reader can still investigate."""
        msg = _msg("1", "ts", "Caldanai", "<@999999> joined")
        out = tail_channel._message_content(
            msg, mention_map={111: "Someone"},
        )
        assert "<@999999>" in out


# ---------------------------------------------------------------------------
# _strip_ansi / _is_visually_empty — polish helpers
# ---------------------------------------------------------------------------


class TestStripAnsi:
    def test_strips_full_escape_with_esc(self):
        assert tail_channel._strip_ansi("\x1b[2;32munharmed\x1b[0m") == "unharmed"

    def test_strips_bracket_only_form(self):
        assert tail_channel._strip_ansi("[2;32munharmed[0m") == "unharmed"

    def test_leaves_plain_text_untouched(self):
        assert tail_channel._strip_ansi("just text") == "just text"

    def test_empty_input(self):
        assert tail_channel._strip_ansi("") == ""
        assert tail_channel._strip_ansi(None) is None


class TestIsVisuallyEmpty:
    def test_empty_string(self):
        assert tail_channel._is_visually_empty("") is True

    def test_whitespace(self):
        assert tail_channel._is_visually_empty("   \t\n") is True

    def test_zero_width_space(self):
        assert tail_channel._is_visually_empty("\u200b") is True

    def test_mixed_zero_width_and_whitespace(self):
        assert tail_channel._is_visually_empty("\u200b \u200c") is True

    def test_real_content_not_empty(self):
        assert tail_channel._is_visually_empty("hi") is False

    def test_zero_width_mixed_with_text_not_empty(self):
        assert tail_channel._is_visually_empty("\u200bhi") is False


# ---------------------------------------------------------------------------
# Mention resolution
# ---------------------------------------------------------------------------


class TestBuildMentionMap:
    def test_queries_by_guild_and_channel(self):
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.players.find.return_value = [
                {"user_id": 111, "name": "Alpha"},
                {"user_id": 222, "name": "Beta"},
            ]
            live_db.return_value = db
            m = tail_channel._build_mention_map(1, 100)
        assert m == {111: "Alpha", 222: "Beta"}
        query = db.players.find.call_args.args[0]
        assert query == {"guild_id": 1, "channel_id": 100}

    def test_missing_guild_or_channel_returns_empty(self):
        assert tail_channel._build_mention_map(0, 100) == {}
        assert tail_channel._build_mention_map(1, 0) == {}

    def test_handles_docs_without_name(self):
        """Partial player docs shouldn't crash the map build."""
        with patch("tools.tail_channel.live_db") as live_db:
            db = MagicMock()
            db.players.find.return_value = [
                {"user_id": 111, "name": "Alpha"},
                {"user_id": 222},  # no name
                {"name": "NoId"},  # no user_id
            ]
            live_db.return_value = db
            m = tail_channel._build_mention_map(1, 100)
        assert m == {111: "Alpha"}

    def test_db_error_returns_empty_map(self):
        """A DB exception shouldn't take down the tool — mention
        resolution is best-effort; fall back to raw mentions."""
        with patch("tools.tail_channel.live_db") as live_db:
            live_db.side_effect = Exception("db down")
            assert tail_channel._build_mention_map(1, 100) == {}


class TestResolveMentions:
    def test_modern_mention(self):
        out = tail_channel._resolve_mentions(
            "<@111> did a thing", {111: "Alpha"},
        )
        assert out == "@Alpha did a thing"

    def test_nickname_mention(self):
        out = tail_channel._resolve_mentions(
            "<@!111> did a thing", {111: "Alpha"},
        )
        assert out == "@Alpha did a thing"

    def test_unknown_id_left_raw(self):
        out = tail_channel._resolve_mentions(
            "<@999> surprise", {111: "Alpha"},
        )
        assert "<@999>" in out

    def test_multiple_in_one_message(self):
        out = tail_channel._resolve_mentions(
            "<@111> hits <@!222>", {111: "Alpha", 222: "Beta"},
        )
        assert out == "@Alpha hits @Beta"

    def test_empty_map_leaves_everything_raw(self):
        text = "<@111> hits <@!222>"
        assert tail_channel._resolve_mentions(text, {}) == text

    def test_role_and_channel_mentions_not_touched(self):
        """Role (<@&id>) and channel (<#id>) mentions intentionally
        fall through — we only resolve users today."""
        text = "<@&1234> check <#5678>"
        assert tail_channel._resolve_mentions(text, {111: "Alpha"}) == text


# ---------------------------------------------------------------------------
# Zero-width embed field skip
# ---------------------------------------------------------------------------


class TestRenderEmbedsZeroWidth:
    def test_zero_width_spacer_field_dropped(self):
        """Discord uses a zero-width spacer field for vertical
        spacing between stat groups. Flattening it renders as
        ``​: ​`` which is visual noise — we skip entirely."""
        embeds = [{
            "title": "Monster",
            "fields": [
                {"name": "Size", "value": "Huge"},
                {"name": "\u200b", "value": "\u200b"},
                {"name": "HP", "value": "100"},
            ],
        }]
        out = tail_channel._render_embeds(embeds)
        assert "Size: Huge" in out
        assert "HP: 100" in out
        # Spacer field gone entirely.
        assert "\u200b" not in out
        assert ": " not in out.replace("Size: Huge", "").replace("HP: 100", "").replace(": ", "", 0)

    def test_visually_empty_title_skipped(self):
        embeds = [{"title": "   ", "description": "real content"}]
        out = tail_channel._render_embeds(embeds)
        assert "real content" in out
        assert "****" not in out


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


# ---------------------------------------------------------------------------
# _parse_time_spec — relative + ISO + edge cases
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta, timezone


class TestParseTimeSpec:
    _NOW = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)

    @pytest.mark.parametrize("spec,delta", [
        ("30s", timedelta(seconds=30)),
        ("5m", timedelta(minutes=5)),
        ("9h", timedelta(hours=9)),
        ("2d", timedelta(days=2)),
        ("1w", timedelta(weeks=1)),
        ("9H", timedelta(hours=9)),  # case-insensitive
    ])
    def test_relative_subtracts_from_now(self, spec, delta):
        result = tail_channel._parse_time_spec(spec, now=self._NOW)
        assert result == self._NOW - delta

    def test_iso_with_z_suffix(self):
        result = tail_channel._parse_time_spec("2026-04-25T16:00:00Z")
        assert result == datetime(2026, 4, 25, 16, 0, 0, tzinfo=timezone.utc)

    def test_iso_without_z_assumes_utc(self):
        result = tail_channel._parse_time_spec("2026-04-25T16:00:00")
        assert result == datetime(2026, 4, 25, 16, 0, 0, tzinfo=timezone.utc)

    def test_iso_with_offset(self):
        result = tail_channel._parse_time_spec("2026-04-25T16:00:00+02:00")
        assert result.utcoffset() == timedelta(hours=2)

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            tail_channel._parse_time_spec("")

    def test_garbage_raises_with_helpful_message(self):
        with pytest.raises(ValueError, match=r"could not parse"):
            tail_channel._parse_time_spec("not-a-real-time")


# ---------------------------------------------------------------------------
# _datetime_to_snowflake — Discord epoch math
# ---------------------------------------------------------------------------

class TestDatetimeToSnowflake:
    def test_discord_epoch_is_zero(self):
        epoch = datetime(2015, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert tail_channel._datetime_to_snowflake(epoch) == 0

    def test_one_ms_after_epoch(self):
        # 1 ms past the Discord epoch should yield 1 << 22.
        dt = datetime(2015, 1, 1, 0, 0, 0, 1000, tzinfo=timezone.utc)
        assert tail_channel._datetime_to_snowflake(dt) == 1 << 22

    def test_naive_datetime_assumed_utc(self):
        naive = datetime(2015, 1, 1, 0, 0, 0)  # no tzinfo
        assert tail_channel._datetime_to_snowflake(naive) == 0

    def test_pre_epoch_clamps_to_zero(self):
        ancient = datetime(2000, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        assert tail_channel._datetime_to_snowflake(ancient) == 0

    def test_monotonic_with_time(self):
        a = datetime(2026, 4, 25, 16, 0, 0, tzinfo=timezone.utc)
        b = datetime(2026, 4, 26, 16, 0, 0, tzinfo=timezone.utc)
        assert tail_channel._datetime_to_snowflake(b) > tail_channel._datetime_to_snowflake(a)


# ---------------------------------------------------------------------------
# _backfill_messages — pagination + window filter
# ---------------------------------------------------------------------------

class TestBackfillMessages:
    @pytest.mark.asyncio
    async def test_paginates_until_oldest_predates_since(self):
        # Three batches of 2 messages each, then nothing. Each batch
        # is older than the previous (Discord newest-first).
        client = MagicMock()
        batches = [
            [
                {"id": "300", "timestamp": "2026-04-26T12:00:00Z"},
                {"id": "299", "timestamp": "2026-04-26T11:00:00Z"},
            ],
            [
                {"id": "298", "timestamp": "2026-04-26T10:00:00Z"},
                {"id": "297", "timestamp": "2026-04-26T09:00:00Z"},
            ],
            # 8h window means since=04:00; oldest in this batch is
            # 03:00 (predates since), so loop stops after this batch.
            [
                {"id": "296", "timestamp": "2026-04-26T05:00:00Z"},
                {"id": "295", "timestamp": "2026-04-26T03:00:00Z"},
            ],
        ]
        client.get_messages = AsyncMock(side_effect=batches + [[]])

        since_dt = datetime(2026, 4, 26, 4, 0, 0, tzinfo=timezone.utc)
        result = await tail_channel._backfill_messages(
            client, channel_id=999, since_dt=since_dt,
        )

        # 03:00 should be filtered out (older than since_dt); rest in.
        ids = [m["id"] for m in result]
        # Chronological: oldest-included → newest.
        assert ids == ["296", "297", "298", "299", "300"]
        # Should have made 3 calls (loop broke after seeing 03:00).
        assert client.get_messages.await_count == 3

    @pytest.mark.asyncio
    async def test_until_dt_filters_upper_bound(self):
        client = MagicMock()
        client.get_messages = AsyncMock(side_effect=[
            [
                {"id": "200", "timestamp": "2026-04-26T12:00:00Z"},
                {"id": "199", "timestamp": "2026-04-26T11:00:00Z"},
                {"id": "198", "timestamp": "2026-04-26T10:00:00Z"},
                {"id": "197", "timestamp": "2026-04-26T09:00:00Z"},
            ],
            [],
        ])

        # Window: 09:30 → 11:30. Should keep 10:00 and 11:00 only.
        since_dt = datetime(2026, 4, 26, 9, 30, 0, tzinfo=timezone.utc)
        until_dt = datetime(2026, 4, 26, 11, 30, 0, tzinfo=timezone.utc)
        result = await tail_channel._backfill_messages(
            client, channel_id=999, since_dt=since_dt, until_dt=until_dt,
        )

        ids = [m["id"] for m in result]
        assert ids == ["198", "199"]

    @pytest.mark.asyncio
    async def test_empty_first_batch_returns_empty(self):
        client = MagicMock()
        client.get_messages = AsyncMock(return_value=[])
        result = await tail_channel._backfill_messages(
            client, channel_id=999,
            since_dt=datetime(2026, 4, 26, 0, 0, 0, tzinfo=timezone.utc),
        )
        assert result == []
        assert client.get_messages.await_count == 1


# ---------------------------------------------------------------------------
# _parse_relative_delta — used by --duration and shared with --since-time
# ---------------------------------------------------------------------------

class TestParseRelativeDelta:
    @pytest.mark.parametrize("spec,expected", [
        ("30s", timedelta(seconds=30)),
        ("5m", timedelta(minutes=5)),
        ("1h", timedelta(hours=1)),
        ("2d", timedelta(days=2)),
        ("1w", timedelta(weeks=1)),
        ("1H", timedelta(hours=1)),  # case-insensitive
    ])
    def test_units(self, spec, expected):
        assert tail_channel._parse_relative_delta(spec) == expected

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="empty"):
            tail_channel._parse_relative_delta("")

    def test_iso_format_raises(self):
        # _parse_relative_delta is strict — only relative format.
        # ISO falls through to _parse_time_spec's secondary handler.
        with pytest.raises(ValueError, match="not a relative"):
            tail_channel._parse_relative_delta("2026-04-25T16:00Z")

    def test_unitless_number_raises(self):
        with pytest.raises(ValueError, match="not a relative"):
            tail_channel._parse_relative_delta("30")


# ---------------------------------------------------------------------------
# _discord_message_to_raw — adapter from discord.py Message to raw dict
# ---------------------------------------------------------------------------


class TestDiscordMessageToRaw:
    def _msg(
        self, *, mid=12345, content="hi",
        author_name="alice", display_name=None,
        ts=None, embeds=(), attachments=(),
    ):
        from datetime import datetime, timezone
        from unittest.mock import MagicMock
        msg = MagicMock()
        msg.id = mid
        msg.created_at = ts or datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
        msg.author = MagicMock()
        msg.author.id = 999
        msg.author.name = author_name
        msg.author.display_name = display_name or author_name
        msg.content = content
        msg.embeds = list(embeds)
        msg.attachments = list(attachments)
        return msg

    def test_basic_fields(self):
        msg = self._msg()
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["id"] == "12345"
        assert raw["author"]["username"] == "alice"
        assert raw["author"]["id"] == "999"
        assert raw["content"] == "hi"
        assert raw["embeds"] == []
        assert raw["attachments"] == []

    def test_uses_display_name_over_username(self):
        """display_name reflects guild nicknames; preferred over the
        global ``name`` so the channel reader sees the actual rendered
        name in-context."""
        msg = self._msg(author_name="bob_99", display_name="bob")
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["author"]["username"] == "bob"

    def test_falls_back_to_username_when_display_name_missing(self):
        """If display_name is None / empty, fall back to the bare
        username so the field is never blank."""
        msg = self._msg(author_name="alice", display_name="")
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["author"]["username"] == "alice"

    def test_empty_content_normalizes_to_empty_string(self):
        """Discord can deliver content=None for messages whose body
        was stripped (no MESSAGE_CONTENT intent, or system-message
        types). Adapter must produce a string so the formatter
        doesn't blow up on ``None.split()`` later."""
        msg = self._msg(content=None)
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["content"] == ""

    def test_embeds_serialize_to_dicts(self):
        from unittest.mock import MagicMock
        embed = MagicMock()
        embed.to_dict.return_value = {"title": "an embed"}
        msg = self._msg(embeds=[embed])
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["embeds"] == [{"title": "an embed"}]

    def test_attachments_extract_url_and_filename(self):
        from unittest.mock import MagicMock
        att = MagicMock()
        att.url = "https://cdn.example/a.png"
        att.filename = "a.png"
        msg = self._msg(attachments=[att])
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["attachments"] == [
            {"url": "https://cdn.example/a.png", "filename": "a.png"},
        ]

    def test_iso_timestamp(self):
        from datetime import datetime, timezone
        ts = datetime(2026, 4, 27, 17, 30, 15, tzinfo=timezone.utc)
        msg = self._msg(ts=ts)
        raw = tail_channel._discord_message_to_raw(msg)
        assert raw["timestamp"].startswith("2026-04-27T17:30:15")


# ---------------------------------------------------------------------------
# _should_filter_self_event — Gateway --exclude-self filter
# ---------------------------------------------------------------------------


class TestShouldFilterSelfEvent:
    """The Gateway --exclude-self flag suppresses events authored
    by the client's own user (the tester bot), so an agent that's
    both running tail_channel AND posting via bot_player doesn't
    see its own posts echo back into its Monitor stream.

    Compares by integer id, not Python identity — same lesson as
    the verb-dispatch refactor's ``mention is bot_user`` regression
    where MagicMock identity hid a real-Discord-shape bug.
    """

    def test_disabled_never_filters(self):
        assert not tail_channel._should_filter_self_event(
            exclude_self=False, client_user_id=12345, event_author_id=12345,
        )
        assert not tail_channel._should_filter_self_event(
            exclude_self=False, client_user_id=12345, event_author_id=99999,
        )

    def test_enabled_filters_matching_id(self):
        assert tail_channel._should_filter_self_event(
            exclude_self=True, client_user_id=12345, event_author_id=12345,
        )

    def test_enabled_does_not_filter_other_authors(self):
        assert not tail_channel._should_filter_self_event(
            exclude_self=True, client_user_id=12345, event_author_id=99999,
        )

    def test_unknown_client_user_fails_open(self):
        """Pre-on_ready race: client.user is None. Don't filter
        when we don't yet know who we are — better to leak a few
        events at startup than to silently drop a real player's
        early message because the comparison saw None == None."""
        assert not tail_channel._should_filter_self_event(
            exclude_self=True, client_user_id=None, event_author_id=12345,
        )

    def test_string_id_coerces_to_int_match(self):
        """discord.py exposes id as int, but defensive: ensure a
        string-shaped author id (REST-coming-back) still matches."""
        assert tail_channel._should_filter_self_event(
            exclude_self=True, client_user_id=12345, event_author_id="12345",
        )

    def test_unparseable_id_does_not_match(self):
        """Garbage id in an event payload shouldn't crash the
        callback or accidentally suppress a real event."""
        assert not tail_channel._should_filter_self_event(
            exclude_self=True, client_user_id=12345, event_author_id="not-a-number",
        )
        assert not tail_channel._should_filter_self_event(
            exclude_self=True, client_user_id=12345, event_author_id=None,
        )
