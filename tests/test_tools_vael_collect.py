"""Tests for ``tools/vael_collect.py``.

The collector orchestrates ``vael_memory_diff`` and ``vael_thoughts``
helpers; tests use ``tmp_path`` for state files and a synthetic
memory dir + session jsonl. No real bg Vael session needed.

The collector reads/writes three filesystem locations
(``_DIGEST_PATH``, ``_CURSOR_PATH``, ``_SNAPSHOT_ROOT``) — tests
monkeypatch these to point at ``tmp_path`` so the suite can run
without touching the user's actual digest.
"""

import datetime
import json
import os
from pathlib import Path

import pytest

from tools import vael_collect


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def state_paths(tmp_path: Path, monkeypatch):
    """Redirect the collector's three state files into tmp_path."""
    digest = tmp_path / "_digest.md"
    cursor = tmp_path / "_cursor"
    snap_root = tmp_path / "_snapshots"
    monkeypatch.setattr(vael_collect, "_DIGEST_PATH", digest)
    monkeypatch.setattr(vael_collect, "_CURSOR_PATH", cursor)
    monkeypatch.setattr(vael_collect, "_SNAPSHOT_ROOT", snap_root)
    return digest, cursor, snap_root


@pytest.fixture
def bg_vael_tree(tmp_path: Path, monkeypatch):
    """Synthetic bg Vael tree with memory/ and workspace/ subdirs.

    The session jsonl path mirrors Claude Code's actual layout:
    ``~/.claude/projects/<workspace-slug>/<session-id>.jsonl``.
    Tests that exercise thoughts collection set up a fake session
    log in the right place under Path.home().
    """
    bg_dir = tmp_path / "bg_vael"
    (bg_dir / "memory").mkdir(parents=True)
    (bg_dir / "memory" / "MEMORY.md").write_text(
        "# memory\n", encoding="utf-8"
    )
    (bg_dir / "memory" / "vael_friction_log.md").write_text(
        "friction log\n", encoding="utf-8"
    )
    (bg_dir / "workspace").mkdir(parents=True)
    monkeypatch.setenv("BG_VAEL_DIR", str(bg_dir))
    return bg_dir


# ---------------------------------------------------------------------------
# Cursor management
# ---------------------------------------------------------------------------


def test_read_cursor_returns_none_when_missing(state_paths):
    digest, cursor, _ = state_paths
    assert vael_collect._read_cursor() is None


def test_write_then_read_cursor_roundtrip(state_paths):
    when = datetime.datetime(2026, 5, 2, 22, 0, 0, tzinfo=datetime.timezone.utc)
    vael_collect._write_cursor(when)
    got = vael_collect._read_cursor()
    assert got is not None
    assert got.replace(tzinfo=None) == when.replace(tzinfo=None)


def test_read_cursor_handles_naive_iso(state_paths):
    """Cursor file written by an older format (no tz) should be
    interpreted as UTC, not error."""
    digest, cursor, _ = state_paths
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text("2026-05-02T22:00:00", encoding="utf-8")
    got = vael_collect._read_cursor()
    assert got is not None
    assert got.tzinfo == datetime.timezone.utc


def test_read_cursor_handles_garbage_file(state_paths):
    digest, cursor, _ = state_paths
    cursor.parent.mkdir(parents=True, exist_ok=True)
    cursor.write_text("not-a-timestamp\n", encoding="utf-8")
    assert vael_collect._read_cursor() is None


# ---------------------------------------------------------------------------
# bg Vael dir resolution
# ---------------------------------------------------------------------------


def test_resolve_bg_vael_dir_from_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BG_VAEL_DIR", str(tmp_path))
    got = vael_collect._resolve_bg_vael_dir()
    assert got == tmp_path


def test_resolve_bg_vael_dir_missing_raises(monkeypatch):
    monkeypatch.delenv("BG_VAEL_DIR", raising=False)
    with pytest.raises(SystemExit, match="BG_VAEL_DIR"):
        vael_collect._resolve_bg_vael_dir()


# ---------------------------------------------------------------------------
# Memory diff collection
# ---------------------------------------------------------------------------


def test_first_run_emits_initial_snapshot_section(
    state_paths, bg_vael_tree
):
    """First collection has no prior snapshot to diff against —
    should emit a one-line "first snapshot" section."""
    lines = vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    assert any("First snapshot" in line for line in lines)


def test_no_changes_returns_empty(state_paths, bg_vael_tree):
    """Second collection with no memory changes returns empty."""
    # First call takes initial snapshot.
    vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    # Second call: nothing changed.
    lines = vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    assert lines == []


def test_added_file_surfaces_in_diff(state_paths, bg_vael_tree):
    vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    (bg_vael_tree / "memory" / "vael_milestones.md").write_text(
        "first milestone", encoding="utf-8",
    )
    lines = vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    assert any("Added" in line for line in lines)
    assert any("vael_milestones.md" in line for line in lines)


def test_modified_file_surfaces_with_diff(state_paths, bg_vael_tree):
    vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    (bg_vael_tree / "memory" / "MEMORY.md").write_text(
        "# memory\n## new section\n", encoding="utf-8",
    )
    lines = vael_collect._collect_memory_diff(bg_vael_tree / "memory")
    full = "\n".join(lines)
    assert "Modified" in full
    assert "MEMORY.md" in full
    assert "new section" in full  # actual diff body included


# ---------------------------------------------------------------------------
# Digest append + show
# ---------------------------------------------------------------------------


def test_append_digest_creates_file(state_paths):
    digest, _, _ = state_paths
    vael_collect._append_digest("## first section\nbody\n")
    assert digest.exists()
    assert "first section" in digest.read_text(encoding="utf-8")


def test_append_digest_skips_empty(state_paths):
    digest, _, _ = state_paths
    vael_collect._append_digest("")
    vael_collect._append_digest("   \n  ")
    assert not digest.exists()


def test_show_with_no_digest_errors(state_paths, capsys):
    rc = vael_collect._do_show(tail_chars=1000)
    assert rc == 1
    err = capsys.readouterr().err
    assert "No digest" in err


def test_show_truncates_long_digest(state_paths, capsys):
    digest, _, _ = state_paths
    digest.parent.mkdir(parents=True, exist_ok=True)
    digest.write_text("A" * 5000, encoding="utf-8")
    rc = vael_collect._do_show(tail_chars=1000)
    assert rc == 0
    out = capsys.readouterr().out
    assert "..." in out
    # Only ~last 1000 chars + ellipsis prefix.
    assert len(out) < 1100


# ---------------------------------------------------------------------------
# Reset cursor
# ---------------------------------------------------------------------------


def test_reset_cursor_writes_now(state_paths, capsys):
    rc = vael_collect._do_reset_cursor()
    assert rc == 0
    out = capsys.readouterr().out
    assert "Cursor reset" in out
    cursor = vael_collect._read_cursor()
    assert cursor is not None


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_show_and_reset_mutually_exclusive(state_paths, capsys):
    with pytest.raises(SystemExit):
        vael_collect.main(["--show", "--reset-cursor"])


def test_cli_collect_runs_clean_when_no_session(
    state_paths, bg_vael_tree, capsys,
):
    """The collector should not crash when bg Vael's workspace has
    no session jsonl yet (e.g. fresh setup, dormant agent).
    Memory diff still runs (initial snapshot); thought collection
    silently no-ops."""
    rc = vael_collect.main([])
    assert rc == 0


def test_cli_collect_writes_digest_with_changes(
    state_paths, bg_vael_tree,
):
    """End-to-end: take initial snapshot via first run, then modify
    a file, run again, verify the digest captures the modification."""
    vael_collect.main([])  # initial snapshot
    (bg_vael_tree / "memory" / "vael_tactics.md").write_text(
        "new tactic\n", encoding="utf-8",
    )
    vael_collect.main([])
    digest, _, _ = state_paths
    assert digest.exists()
    body = digest.read_text(encoding="utf-8")
    assert "Memory diff" in body
    assert "vael_tactics.md" in body
