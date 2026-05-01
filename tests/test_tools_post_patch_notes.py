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
from tools._common import split_for_discord


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

    def test_oversize_blurb_no_longer_rejected_at_read(self, tmp_path: Path):
        """``_read_blurb`` used to reject oversize content with a
        SystemExit; the auto-splitter (added 2026-04-30) makes
        that rejection wrong — content over the 2000-char limit
        is now valid and gets chunked at post time. This test
        pins the new contract: read returns content untouched
        regardless of size; the splitter handles the limit."""
        f = tmp_path / "big.md"
        f.write_text("x" * 2500, encoding="utf-8")
        # Should not raise.
        content = post_patch_notes._read_blurb(f)
        assert "x" * 2500 in content


class TestSplitForDiscord:
    """Auto-chunk oversize blurbs at line boundaries so a single
    invocation can post multiple Discord messages without the
    operator manually trimming or splitting. Added 2026-04-30
    to replace the previous oversize-rejection contract."""

    _HEADER = "**Patch notes — 2026-04-30 12:00 UTC**\n"

    def _bullet(self, idx, body="lorem ipsum dolor sit amet"):
        return f"- **Bullet {idx}.** {body}"

    def test_single_chunk_when_under_limit(self):
        """Content under the limit returns as a single-element
        list — caller can treat splitter output uniformly."""
        content = self._HEADER + "\n- one\n- two\n- three"
        chunks = split_for_discord(content, reserve_header=True)
        assert len(chunks) == 1

    def test_two_chunks_when_over_limit(self):
        bullets = [self._bullet(i, "x" * 100) for i in range(20)]
        content = self._HEADER + "\n" + "\n".join(bullets)
        assert len(content) > 2000

        chunks = split_for_discord(content, reserve_header=True)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 2000

    def test_header_only_on_first_chunk(self):
        """The ``**Patch notes — ... UTC**`` header lands on the
        first chunk; subsequent chunks are body-only. Repeating
        the header on continuations would clutter the channel."""
        bullets = [self._bullet(i, "x" * 200) for i in range(15)]
        content = self._HEADER + "\n" + "\n".join(bullets)

        chunks = split_for_discord(content, reserve_header=True)
        assert len(chunks) >= 2
        assert chunks[0].startswith("**Patch notes")
        for chunk in chunks[1:]:
            assert not chunk.startswith("**Patch notes")

    def test_bullets_preserved_intact(self):
        """Splitting at line boundaries means no bullet gets
        broken mid-text. Every body line in every chunk is either
        the header or a whole bullet."""
        bullets = [self._bullet(i, "x" * 100) for i in range(20)]
        content = self._HEADER + "\n" + "\n".join(bullets)

        chunks = split_for_discord(content, reserve_header=True)
        for chunk in chunks:
            for line in chunk.split("\n"):
                if not line or line.startswith("**Patch notes"):
                    continue
                assert line.startswith("- **"), (
                    f"Chunk contained a partial line: {line!r}"
                )

    def test_chunk_count_matches_ceil_division(self):
        """Number of chunks = ceil(total / max_chars). Pin this
        so test_chunks_roughly_even has a predictable target."""
        bullets = [self._bullet(i, "x" * 200) for i in range(40)]
        content = self._HEADER + "\n" + "\n".join(bullets)
        total = len(content)
        expected_n = (total + 1999) // 2000

        chunks = split_for_discord(content, reserve_header=True)
        assert len(chunks) == expected_n

    def test_chunks_roughly_even(self):
        """Target is total/n; line-snapping causes some variance
        but no chunk should be wildly larger or smaller than the
        others. 'Within 50% of target' is the smoke ceiling."""
        bullets = [self._bullet(i, "x" * 150) for i in range(30)]
        content = self._HEADER + "\n" + "\n".join(bullets)
        total = len(content)

        chunks = split_for_discord(content, reserve_header=True)
        n = len(chunks)
        assert n >= 2
        target = total / n
        for chunk in chunks:
            ratio = len(chunk) / target
            assert 0.5 < ratio < 1.5, (
                f"Chunk size {len(chunk)} far from target {target:.0f} "
                f"(ratio {ratio:.2f}); split is unbalanced."
            )

    def test_oversize_single_bullet_raises(self):
        """If a single bullet exceeds the per-message limit,
        line-boundary splitting can't help — SystemExit so the
        operator can intervene rather than silently posting a
        truncated message."""
        huge = self._bullet(1, "x" * 2500)  # > 2000 chars on its own
        content = self._HEADER + "\n" + huge

        with pytest.raises(SystemExit, match="(?i)tighten that line"):
            split_for_discord(content, reserve_header=True)


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
        assert "1/1 guild(s) successful" in captured.out

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
