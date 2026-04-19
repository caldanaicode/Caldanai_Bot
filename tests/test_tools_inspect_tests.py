"""Tests for ``tools/inspect_tests.py``.

AST parsing + rendering — pure, no Discord, no DB. We write a
few small fixture test files into ``tmp_path`` and exercise the
inspector against them.
"""

import json
import re
from pathlib import Path

import pytest

from tools import inspect_tests


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_file(tmp_path: Path) -> Path:
    """One class with two async tests, one module-level sync test."""
    p = tmp_path / "test_alpha.py"
    p.write_text(
        '''
def helper():
    pass

def test_module_level():
    assert True


class TestSomething:
    def test_plain(self):
        assert True

    async def test_coroutine(self):
        assert True
''',
        encoding="utf-8",
    )
    return p


@pytest.fixture
def parametrized_file(tmp_path: Path) -> Path:
    """Tests with various parametrize shapes."""
    p = tmp_path / "test_beta.py"
    p.write_text(
        '''
import pytest


class TestParam:
    @pytest.mark.parametrize("raw, expected", [
        ("a", 1),
        ("b", 2),
        ("c", 3),
    ])
    def test_three_cases(self, raw, expected):
        assert True

    @pytest.mark.parametrize("x", [1, 2])
    @pytest.mark.parametrize("y", [10, 20, 30])
    def test_stacked(self, x, y):
        """Stacked parametrize multiplies: 2 × 3 = 6 cases."""
        assert True

    @pytest.mark.parametrize("raw", dynamic_list)  # can't decode, falls back to 1
    def test_dynamic(self, raw):
        assert True
''',
        encoding="utf-8",
    )
    return p


@pytest.fixture
def syntax_broken_file(tmp_path: Path) -> Path:
    p = tmp_path / "test_gamma.py"
    p.write_text("def test_bad(\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# inspect_file — basic parsing
# ---------------------------------------------------------------------------


class TestInspectFile:
    def test_discovers_class_and_module_level_tests(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        names = [t.qualified for t in report.tests]

        assert "test_module_level" in names
        assert "TestSomething::test_plain" in names
        assert "TestSomething::test_coroutine" in names

    def test_detects_async(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        by_name = {t.name: t for t in report.tests}

        assert by_name["test_coroutine"].is_async is True
        assert by_name["test_plain"].is_async is False
        assert by_name["test_module_level"].is_async is False

    def test_skips_non_test_functions(self, simple_file):
        """Helper / fixture / non-``test_``-prefixed functions
        must not appear in the listing."""
        report = inspect_tests.inspect_file(simple_file)
        names = [t.name for t in report.tests]
        assert "helper" not in names

    def test_syntax_error_returns_empty_report_not_raise(
        self, syntax_broken_file, capsys,
    ):
        """A malformed file shouldn't take down a directory walk.
        Empty report + stderr warning is the graceful degradation."""
        report = inspect_tests.inspect_file(syntax_broken_file)
        assert report.tests == []
        captured = capsys.readouterr()
        assert "Syntax error" in captured.err

    def test_missing_file_returns_empty_report(self, tmp_path, capsys):
        report = inspect_tests.inspect_file(tmp_path / "nonexistent.py")
        assert report.tests == []


# ---------------------------------------------------------------------------
# Parametrize expansion
# ---------------------------------------------------------------------------


class TestParametrizeCounting:
    def test_literal_list_counts_expansions(self, parametrized_file):
        report = inspect_tests.inspect_file(parametrized_file)
        by_name = {t.name: t for t in report.tests}

        assert by_name["test_three_cases"].parametrize_cases == 3

    def test_stacked_parametrize_multiplies(self, parametrized_file):
        report = inspect_tests.inspect_file(parametrized_file)
        by_name = {t.name: t for t in report.tests}

        assert by_name["test_stacked"].parametrize_cases == 6

    def test_dynamic_parametrize_falls_back_to_one(self, parametrized_file):
        """A non-literal ``argvalues`` (e.g. a variable) can't be
        decoded statically; treat as a single case so the count
        doesn't silently overreport."""
        report = inspect_tests.inspect_file(parametrized_file)
        by_name = {t.name: t for t in report.tests}

        assert by_name["test_dynamic"].parametrize_cases == 1

    def test_total_collected_sums_per_test(self, parametrized_file):
        """Report.total_collected should equal the sum of
        per-test parametrize counts — our substitute for pytest's
        collection number."""
        report = inspect_tests.inspect_file(parametrized_file)
        assert report.total_collected == 3 + 6 + 1


# ---------------------------------------------------------------------------
# Directory walk
# ---------------------------------------------------------------------------


class TestDiscoverFiles:
    def test_single_file_returns_itself(self, simple_file):
        files = inspect_tests.discover_files(simple_file)
        assert files == [simple_file]

    def test_directory_walks_recursively(self, tmp_path):
        (tmp_path / "subdir").mkdir()
        (tmp_path / "test_a.py").write_text("def test_x(): pass", encoding="utf-8")
        (tmp_path / "subdir" / "test_b.py").write_text(
            "def test_y(): pass", encoding="utf-8",
        )
        # Non-``test_`` files are ignored.
        (tmp_path / "helper.py").write_text("pass", encoding="utf-8")

        files = inspect_tests.discover_files(tmp_path)
        names = sorted(f.name for f in files)
        assert names == ["test_a.py", "test_b.py"]

    def test_missing_path_raises_systemexit(self, tmp_path):
        with pytest.raises(SystemExit):
            inspect_tests.discover_files(tmp_path / "nowhere")


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


class TestRenderers:
    def test_list_groups_by_class(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        out = inspect_tests.render_list([report])

        assert "test_module_level" in out
        assert "TestSomething::test_plain" in out
        assert "TestSomething::test_coroutine" in out
        assert "async" in out  # the async marker surfaces

    def test_list_filtered_by_pattern(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        pattern = re.compile(r"module_level")
        out = inspect_tests.render_list([report], pattern=pattern)

        assert "test_module_level" in out
        assert "test_plain" not in out

    def test_count_reports_numbers(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        out = inspect_tests.render_count([report])

        assert "3 function" in out  # module + 2 class methods
        assert "1 async" in out

    def test_structure_tree_view(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        out = inspect_tests.render_structure([report])

        # Class appears as a header line, methods indented beneath.
        class_idx = out.index("TestSomething")
        plain_idx = out.index("test_plain")
        assert class_idx < plain_idx
        # Module-level bucket rendered as "<module>"
        assert "<module>" in out

    def test_json_is_valid_and_shape_stable(self, simple_file):
        report = inspect_tests.inspect_file(simple_file)
        out = inspect_tests.render_json([report])

        parsed = json.loads(out)
        assert isinstance(parsed, list)
        assert parsed[0]["path"] == str(simple_file)
        test_names = {t["name"] for t in parsed[0]["tests"]}
        assert {"test_module_level", "test_plain", "test_coroutine"} <= test_names
        # is_async field present and typed
        for t in parsed[0]["tests"]:
            assert isinstance(t["is_async"], bool)

    def test_parametrize_multiplier_rendered(self, parametrized_file):
        report = inspect_tests.inspect_file(parametrized_file)
        out = inspect_tests.render_list([report])
        # The "3×" / "6×" suffix lets a reader tell collection
        # expansions apart from raw function counts at a glance.
        assert "3×" in out or "6×" in out


# ---------------------------------------------------------------------------
# Integration: run on the project's own test suite
# ---------------------------------------------------------------------------


class TestSmokeOnRealSuite:
    """Sanity-check against the actual ``tests/`` directory —
    inspector shouldn't raise on any existing file and should
    report at least a few hundred functions."""

    def test_walks_project_tests_cleanly(self):
        tests_dir = Path(__file__).parent
        files = inspect_tests.discover_files(tests_dir)
        assert len(files) > 10  # sanity — project has many test files

        total_tests = 0
        for f in files:
            report = inspect_tests.inspect_file(f)
            total_tests += len(report.tests)
        # The suite has hundreds of tests; exact count is a moving
        # target, but a lower bound catches the "inspector discovers
        # zero due to a regex bug" failure mode.
        assert total_tests > 500
