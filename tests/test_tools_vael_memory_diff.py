"""Tests for ``tools/vael_memory_diff.py``.

Pure local-filesystem tool — uses ``tmp_path`` for both the
synthetic memory dir and the snapshot root. No real bg Vael
session needed.
"""

import datetime
from pathlib import Path

import pytest

from tools import vael_memory_diff


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def memory_dir(tmp_path: Path) -> Path:
    """Synthetic bg Vael memory dir with a few representative files."""
    d = tmp_path / "memory"
    d.mkdir()
    (d / "MEMORY.md").write_text("# Memory\n\n- file one\n", encoding="utf-8")
    (d / "vael_identity.md").write_text(
        "I am Vael Caldanai.\n", encoding="utf-8"
    )
    (d / "vael_friction_log.md").write_text(
        "Friction log.\n\n- one issue\n", encoding="utf-8"
    )
    return d


@pytest.fixture
def snapshot_root(tmp_path: Path) -> Path:
    return tmp_path / "snapshots"


# ---------------------------------------------------------------------------
# Snapshot creation + listing
# ---------------------------------------------------------------------------


def test_take_snapshot_copies_tree(memory_dir: Path, snapshot_root: Path):
    snap = vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    assert snap.exists()
    # Every file in source should have a copy in snapshot.
    src_files = {p.name for p in memory_dir.iterdir() if p.is_file()}
    snap_files = {p.name for p in snap.iterdir() if p.is_file()}
    assert src_files == snap_files
    # Content matches.
    assert (snap / "MEMORY.md").read_text(encoding="utf-8") == (
        memory_dir / "MEMORY.md"
    ).read_text(encoding="utf-8")


def test_take_snapshot_missing_source_raises(tmp_path: Path):
    with pytest.raises(SystemExit, match="does not exist"):
        vael_memory_diff._take_snapshot(
            tmp_path / "no-such-dir", tmp_path / "snapshots",
        )


def test_take_snapshot_collision_appends_suffix(
    memory_dir: Path, snapshot_root: Path, monkeypatch
):
    """Two snapshots in the same second should not clobber each other."""
    fixed_ts = datetime.datetime(2026, 5, 2, 18, 30, 0)
    monkeypatch.setattr(
        vael_memory_diff, "_iso_timestamp", lambda *a, **kw: "2026-05-02T18-30-00"
    )
    a = vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    b = vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    assert a != b
    # Second snapshot gets a -2 suffix per the dedup logic.
    assert b.name.endswith("-2")


def test_list_snapshots_returns_chronological(
    memory_dir: Path, snapshot_root: Path, monkeypatch
):
    timestamps = ["2026-05-01T10-00-00", "2026-05-02T11-00-00", "2026-05-03T12-00-00"]
    iter_ts = iter(timestamps)
    monkeypatch.setattr(
        vael_memory_diff, "_iso_timestamp",
        lambda *a, **kw: next(iter_ts),
    )
    vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    listed = vael_memory_diff._list_snapshots(snapshot_root)
    assert [p.name for p in listed] == timestamps


def test_list_snapshots_skips_non_iso_dirs(snapshot_root: Path):
    snapshot_root.mkdir()
    (snapshot_root / "2026-05-02T10-00-00").mkdir()
    (snapshot_root / "junk-dir").mkdir()
    (snapshot_root / "README.md").write_text("hi", encoding="utf-8")
    listed = vael_memory_diff._list_snapshots(snapshot_root)
    assert [p.name for p in listed] == ["2026-05-02T10-00-00"]


def test_list_snapshots_empty(snapshot_root: Path):
    assert vael_memory_diff._list_snapshots(snapshot_root) == []


# ---------------------------------------------------------------------------
# Snapshot resolution
# ---------------------------------------------------------------------------


def test_resolve_latest_when_no_name(
    memory_dir: Path, snapshot_root: Path, monkeypatch
):
    iter_ts = iter(["2026-05-01T10-00-00", "2026-05-02T11-00-00"])
    monkeypatch.setattr(
        vael_memory_diff, "_iso_timestamp",
        lambda *a, **kw: next(iter_ts),
    )
    vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    latest = vael_memory_diff._resolve_snapshot(snapshot_root, None)
    assert latest.name == "2026-05-02T11-00-00"


def test_resolve_specific_name(
    memory_dir: Path, snapshot_root: Path, monkeypatch
):
    monkeypatch.setattr(
        vael_memory_diff, "_iso_timestamp",
        lambda *a, **kw: "2026-05-02T11-00-00",
    )
    vael_memory_diff._take_snapshot(memory_dir, snapshot_root)
    found = vael_memory_diff._resolve_snapshot(
        snapshot_root, "2026-05-02T11-00-00",
    )
    assert found.name == "2026-05-02T11-00-00"


def test_resolve_unknown_name_raises(snapshot_root: Path):
    snapshot_root.mkdir()
    with pytest.raises(SystemExit, match="Snapshot not found"):
        vael_memory_diff._resolve_snapshot(snapshot_root, "no-such-snapshot")


def test_resolve_no_snapshots_returns_none(snapshot_root: Path):
    assert vael_memory_diff._resolve_snapshot(snapshot_root, None) is None


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------


def test_classify_added_files(memory_dir: Path, tmp_path: Path):
    snap = tmp_path / "old"
    snap.mkdir()
    (snap / "MEMORY.md").write_text("# Memory\n\n- file one\n", encoding="utf-8")
    # memory_dir has more files than snap.
    added, removed, modified, unchanged = vael_memory_diff._classify_files(
        snap, memory_dir,
    )
    added_names = {p.name for p in added}
    assert "vael_identity.md" in added_names
    assert "vael_friction_log.md" in added_names
    assert removed == []


def test_classify_removed_files(memory_dir: Path, tmp_path: Path):
    snap = tmp_path / "old"
    snap.mkdir()
    # Snapshot has an extra file that current state doesn't.
    (snap / "MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    (snap / "vael_identity.md").write_text("old", encoding="utf-8")
    (snap / "vael_friction_log.md").write_text("old", encoding="utf-8")
    (snap / "vael_extra.md").write_text("removed file", encoding="utf-8")
    added, removed, modified, unchanged = vael_memory_diff._classify_files(
        snap, memory_dir,
    )
    removed_names = {p.name for p in removed}
    assert "vael_extra.md" in removed_names


def test_classify_modified_files(memory_dir: Path, tmp_path: Path):
    snap = tmp_path / "old"
    snap.mkdir()
    (snap / "MEMORY.md").write_text("# Old content\n", encoding="utf-8")
    (snap / "vael_identity.md").write_text(
        "I am Vael Caldanai.\n", encoding="utf-8"  # same as memory_dir
    )
    (snap / "vael_friction_log.md").write_text(
        "old log\n", encoding="utf-8"
    )
    added, removed, modified, unchanged = vael_memory_diff._classify_files(
        snap, memory_dir,
    )
    modified_names = {p.name for p in modified}
    unchanged_names = {p.name for p in unchanged}
    assert "MEMORY.md" in modified_names
    assert "vael_friction_log.md" in modified_names
    assert "vael_identity.md" in unchanged_names


def test_classify_subdirectory_files(tmp_path: Path):
    """Recursive classification — files in subdirs should be tracked."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    (old / "sub").mkdir(parents=True)
    (new / "sub").mkdir(parents=True)
    (old / "sub" / "deep.md").write_text("a", encoding="utf-8")
    (new / "sub" / "deep.md").write_text("b", encoding="utf-8")
    _, _, modified, _ = vael_memory_diff._classify_files(old, new)
    assert any(p.as_posix() == "sub/deep.md" for p in modified)


# ---------------------------------------------------------------------------
# Diff formatting
# ---------------------------------------------------------------------------


def test_format_diff_unified_output(tmp_path: Path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    (old / "f.md").write_text("line one\nline two\n", encoding="utf-8")
    (new / "f.md").write_text("line one\nline two changed\n", encoding="utf-8")
    diff = vael_memory_diff._format_diff(old, new, [Path("f.md")])
    assert "old/f.md" in diff
    assert "new/f.md" in diff
    assert "-line two" in diff
    assert "+line two changed" in diff


def test_format_diff_handles_unreadable(tmp_path: Path):
    """Binary or unreadable files don't crash the diff — they yield
    empty line-lists which difflib handles cleanly."""
    old = tmp_path / "old"
    new = tmp_path / "new"
    old.mkdir()
    new.mkdir()
    # File only on the new side, with unicode content.
    (new / "added.md").write_text("new\nfile\n", encoding="utf-8")
    diff = vael_memory_diff._format_diff(old, new, [Path("added.md")])
    # _format_diff is called with rel_paths in the modified list, so
    # this is a fault-tolerance check: missing-file on one side
    # should produce a one-sided diff rather than crash.
    assert "+new" in diff or diff != ""


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_snapshot_only(memory_dir: Path, tmp_path: Path, capsys):
    snapshot_root = tmp_path / "snaps"
    rc = vael_memory_diff.main([
        "--source", str(memory_dir),
        "--snapshot-root", str(snapshot_root),
        "--snapshot",
    ])
    assert rc == 0
    assert any(p.is_dir() for p in snapshot_root.iterdir())


def test_cli_list_when_empty(tmp_path: Path, capsys):
    snapshot_root = tmp_path / "snaps"
    rc = vael_memory_diff.main([
        "--source", "ignored",
        "--snapshot-root", str(snapshot_root),
        "--list",
    ])
    assert rc == 1


def test_cli_default_mode_diffs_then_snapshots(
    memory_dir: Path, tmp_path: Path, monkeypatch, capsys,
):
    """No-flag invocation: diff vs latest, then take a fresh snapshot."""
    snapshot_root = tmp_path / "snaps"
    iter_ts = iter([
        "2026-05-02T10-00-00",  # initial
        "2026-05-02T11-00-00",  # post-diff fresh snapshot
    ])
    monkeypatch.setattr(
        vael_memory_diff, "_iso_timestamp",
        lambda *a, **kw: next(iter_ts),
    )
    # Initial snapshot.
    vael_memory_diff.main([
        "--source", str(memory_dir),
        "--snapshot-root", str(snapshot_root),
        "--snapshot",
    ])
    # Modify a file.
    (memory_dir / "MEMORY.md").write_text(
        "# Memory\n\n- file one\n- new entry\n", encoding="utf-8",
    )
    # Default mode: diff + snapshot.
    rc = vael_memory_diff.main([
        "--source", str(memory_dir),
        "--snapshot-root", str(snapshot_root),
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Modified" in out
    assert "MEMORY.md" in out
    assert "Fresh snapshot taken" in out
    # Verify the post-diff snapshot exists.
    snapshots = vael_memory_diff._list_snapshots(snapshot_root)
    assert len(snapshots) == 2
