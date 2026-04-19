"""Tests for ``tools/rename_in_tree.py``.

Literal multi-pair search-and-replace across a glob. Pure file
I/O; we exercise it against ``tmp_path`` fixtures.
"""

from pathlib import Path

import pytest

from tools import rename_in_tree


# ---------------------------------------------------------------------------
# _apply_replacements — core string rewrite
# ---------------------------------------------------------------------------


class TestApplyReplacements:
    def test_single_pair(self):
        out, counts = rename_in_tree._apply_replacements(
            "hello world hello", [("hello", "goodbye")],
        )
        assert out == "goodbye world goodbye"
        assert counts == [2]

    def test_multiple_pairs_in_order(self):
        out, counts = rename_in_tree._apply_replacements(
            "alpha beta gamma",
            [("alpha", "ALPHA"), ("beta", "BETA"), ("gamma", "GAMMA")],
        )
        assert out == "ALPHA BETA GAMMA"
        assert counts == [1, 1, 1]

    def test_pair_order_matters_when_earlier_feeds_later(self):
        """If an earlier replacement produces a string matched by
        a later one, the later one fires on the rewritten content.
        Callers rely on this: ``A → B``, ``B → C`` yields ``C``."""
        out, counts = rename_in_tree._apply_replacements(
            "A", [("A", "B"), ("B", "C")],
        )
        assert out == "C"
        assert counts == [1, 1]

    def test_zero_hits_counted_as_zero(self):
        out, counts = rename_in_tree._apply_replacements(
            "hello", [("absent", "present")],
        )
        assert out == "hello"
        assert counts == [0]

    def test_empty_input(self):
        out, counts = rename_in_tree._apply_replacements(
            "", [("a", "b")],
        )
        assert out == ""
        assert counts == [0]


# ---------------------------------------------------------------------------
# rewrite_file — per-file dry-run vs apply
# ---------------------------------------------------------------------------


class TestRewriteFile:
    def test_dry_run_does_not_write(self, tmp_path):
        p = tmp_path / "source.py"
        p.write_text("hello hello", encoding="utf-8")

        total, counts = rename_in_tree.rewrite_file(
            p, [("hello", "world")], apply=False,
        )

        assert total == 2
        assert counts == [2]
        # File contents unchanged on disk.
        assert p.read_text(encoding="utf-8") == "hello hello"

    def test_apply_writes_changes(self, tmp_path):
        p = tmp_path / "source.py"
        p.write_text("hello hello", encoding="utf-8")

        total, counts = rename_in_tree.rewrite_file(
            p, [("hello", "world")], apply=True,
        )

        assert total == 2
        assert p.read_text(encoding="utf-8") == "world world"

    def test_apply_skipped_when_no_hits(self, tmp_path):
        """When a file has zero matches, apply-mode must not touch
        its mtime / contents — otherwise a broad glob rewrites
        every file's timestamp for no reason."""
        p = tmp_path / "clean.py"
        p.write_text("untouched", encoding="utf-8")
        original_mtime = p.stat().st_mtime_ns

        total, _ = rename_in_tree.rewrite_file(
            p, [("absent", "present")], apply=True,
        )

        assert total == 0
        # Content identical; mtime unchanged (we never opened for write).
        assert p.read_text(encoding="utf-8") == "untouched"
        assert p.stat().st_mtime_ns == original_mtime

    def test_binary_file_skipped_gracefully(self, tmp_path):
        """A binary file caught by a wide glob should not cause a
        crash; we return zero hits and leave it alone."""
        p = tmp_path / "image.png"
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\xff\xd8\xff\x00" * 20)
        before = p.read_bytes()

        total, _ = rename_in_tree.rewrite_file(
            p, [("png", "jpg")], apply=True,
        )

        assert total == 0
        assert p.read_bytes() == before

    def test_multiple_pairs_per_file(self, tmp_path):
        p = tmp_path / "mixed.py"
        p.write_text(
            "LEVEL_COLD LEVEL_COOL LEVEL_HOT", encoding="utf-8",
        )

        total, counts = rename_in_tree.rewrite_file(
            p,
            [
                ("LEVEL_COLD", "Warmth.COLD"),
                ("LEVEL_COOL", "Warmth.COOL"),
                ("LEVEL_HOT", "Warmth.HOT"),
            ],
            apply=True,
        )

        assert total == 3
        assert counts == [1, 1, 1]
        assert p.read_text(encoding="utf-8") == (
            "Warmth.COLD Warmth.COOL Warmth.HOT"
        )


# ---------------------------------------------------------------------------
# _iter_files — glob expansion
# ---------------------------------------------------------------------------


class TestIterFiles:
    def test_expands_glob(self, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        (tmp_path / "b.py").write_text("", encoding="utf-8")
        (tmp_path / "c.txt").write_text("", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        files = rename_in_tree._iter_files(["*.py"])
        names = sorted(f.name for f in files)
        assert names == ["a.py", "b.py"]

    def test_recursive_doublestar(self, tmp_path, monkeypatch):
        (tmp_path / "top.py").write_text("", encoding="utf-8")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.py").write_text("", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        files = rename_in_tree._iter_files(["**/*.py"])
        names = sorted(f.name for f in files)
        assert names == ["nested.py", "top.py"]

    def test_dedupes_across_multiple_globs(self, tmp_path, monkeypatch):
        """A file matched by two overlapping globs should appear
        only once so replacements aren't applied twice."""
        (tmp_path / "a.py").write_text("", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        files = rename_in_tree._iter_files(["*.py", "a*"])
        assert len(files) == 1

    def test_skips_directories(self, tmp_path, monkeypatch):
        """A glob that matches a directory (e.g. ``*``) must only
        return files."""
        (tmp_path / "dir_name").mkdir()
        (tmp_path / "file.txt").write_text("", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        files = rename_in_tree._iter_files(["*"])
        names = [f.name for f in files]
        assert "file.txt" in names
        assert "dir_name" not in names
