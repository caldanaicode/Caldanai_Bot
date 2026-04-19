"""AST-based inspector for Python test files.

Replaces one-off ``python -c "import ast; ..."`` inspection loops
with a stable invocation so ``tools.*`` harness permissions cover
every future use.

Usage::

    python -m tools.inspect_tests <path>                    # default: --list
    python -m tools.inspect_tests <path> --count            # summary counts only
    python -m tools.inspect_tests <path> --list             # per-test listing with line numbers
    python -m tools.inspect_tests <path> --structure        # tree view (class → method)
    python -m tools.inspect_tests <path> --find PATTERN     # regex-filter the listing
    python -m tools.inspect_tests <path> --json             # machine-readable output

``<path>`` is a file or directory. Directories are walked
recursively for ``test_*.py`` (pytest convention).

Parametrize expansion count is a best-effort literal decode of
``@pytest.mark.parametrize``'s second argument when it's a list /
tuple literal. Dynamic / fixture-sourced parametrize falls back
to ``1`` per decorated test (i.e. the raw function, pre-
expansion).

Why this exists: inline ``python -c`` strings require per-line
approval and drift each time they're written. A fixed module
entrypoint lets a single permission cover all invocations and
gives the output a consistent shape for downstream tooling.
"""

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional


# Windows consoles default to cp1252 which mangles non-latin1
# glyphs in captured output. Reconfigure where supported.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class TestEntry:
    """One discovered test — a function or coroutine whose name
    starts with ``test_``."""

    name: str
    line: int
    is_async: bool
    class_name: Optional[str]
    parametrize_cases: int  # ≥ 1; > 1 only when a literal list / tuple was decoded
    decorators: List[str] = field(default_factory=list)

    @property
    def qualified(self) -> str:
        if self.class_name:
            return f"{self.class_name}::{self.name}"
        return self.name


@dataclass
class FileReport:
    path: Path
    tests: List[TestEntry]

    @property
    def class_names(self) -> List[str]:
        """Stable-order list of class names seen (including
        ``None`` → "<module>" as a pseudo-class for module-level
        tests) so ``--structure`` can render a tidy grouping."""
        seen: List[str] = []
        for t in self.tests:
            key = t.class_name or "<module>"
            if key not in seen:
                seen.append(key)
        return seen

    @property
    def total_collected(self) -> int:
        """Approximate pytest collection count — raw function count
        plus parametrize expansions where we could decode them."""
        return sum(t.parametrize_cases for t in self.tests)


# ---------------------------------------------------------------------------
# AST walk
# ---------------------------------------------------------------------------


def _decorator_str(node: ast.expr) -> str:
    """Render a decorator expression back to something readable
    (``pytest.mark.parametrize``, ``staticmethod``, etc.).
    Best-effort — bails to ``ast.dump`` on unexpected shapes so we
    never raise just to list a test."""
    try:
        return ast.unparse(node)
    except Exception:
        return ast.dump(node)


def _parametrize_cases(decorators: Iterable[ast.expr]) -> int:
    """Return the number of parametrize expansions for a test.

    Multiple ``@pytest.mark.parametrize`` stack multiplicatively
    (``N × M``). Only literal list / tuple arguments are decoded;
    variables / fixtures / generator calls count as 1 (we can't
    know statically).
    """
    total = 1
    for dec in decorators:
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        name = ""
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name != "parametrize":
            continue
        # parametrize(argnames, argvalues, ...) — argvalues is the
        # second positional or the ``argvalues`` keyword.
        argvalues: Optional[ast.expr] = None
        if len(dec.args) >= 2:
            argvalues = dec.args[1]
        for kw in dec.keywords or []:
            if kw.arg == "argvalues":
                argvalues = kw.value
                break
        if argvalues is None:
            continue
        if isinstance(argvalues, (ast.List, ast.Tuple)):
            total *= max(1, len(argvalues.elts))
        # else: dynamic parametrize — leave factor at 1.
    return total


def _is_test_name(name: str) -> bool:
    return name.startswith("test_")


def _walk_module(tree: ast.AST, path: Path) -> List[TestEntry]:
    tests: List[TestEntry] = []

    # Top-level: look at module body for module-level test functions
    # and for class definitions whose methods we enumerate.
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_test_name(node.name):
                tests.append(_make_entry(node, class_name=None))
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_test_name(child.name):
                        tests.append(_make_entry(child, class_name=node.name))
    return tests


def _make_entry(
    node,
    class_name: Optional[str],
) -> TestEntry:
    return TestEntry(
        name=node.name,
        line=node.lineno,
        is_async=isinstance(node, ast.AsyncFunctionDef),
        class_name=class_name,
        parametrize_cases=_parametrize_cases(node.decorator_list),
        decorators=[_decorator_str(d) for d in node.decorator_list],
    )


def inspect_file(path: Path) -> FileReport:
    """Parse one Python file and return its test inventory.
    Syntax errors surface as a clear stderr line and an empty
    report — don't let one bad file fail a directory walk."""
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"Could not read {path}: {e}", file=sys.stderr)
        return FileReport(path=path, tests=[])
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as e:
        print(f"Syntax error in {path}: {e}", file=sys.stderr)
        return FileReport(path=path, tests=[])
    return FileReport(path=path, tests=_walk_module(tree, path))


def discover_files(target: Path) -> List[Path]:
    """Return the Python test files to inspect. When given a
    directory, walks recursively for ``test_*.py`` — pytest's
    default discovery pattern."""
    if target.is_file():
        return [target]
    if target.is_dir():
        return sorted(target.rglob("test_*.py"))
    raise SystemExit(f"Path not found: {target}")


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_count(reports: List[FileReport]) -> str:
    """One-line per file summary, plus a total at the bottom."""
    lines: List[str] = []
    total_fns = 0
    total_collected = 0
    total_async = 0
    total_classes = 0
    for r in reports:
        fns = len(r.tests)
        collected = r.total_collected
        asyncs = sum(1 for t in r.tests if t.is_async)
        classes = sum(1 for c in r.class_names if c != "<module>")
        total_fns += fns
        total_collected += collected
        total_async += asyncs
        total_classes += classes
        lines.append(
            f"{r.path}: {fns} function(s), {asyncs} async, "
            f"{classes} class(es), {collected} collected (with parametrize)"
        )
    if len(reports) > 1:
        lines.append("")
        lines.append(
            f"TOTAL: {total_fns} function(s), {total_async} async, "
            f"{total_classes} class(es), {total_collected} collected "
            "(with parametrize)"
        )
    return "\n".join(lines)


def render_list(
    reports: List[FileReport],
    pattern: Optional[re.Pattern] = None,
) -> str:
    """Flat listing: one line per test, grouped by file + class."""
    lines: List[str] = []
    for r in reports:
        if not r.tests:
            continue
        filtered = (
            [t for t in r.tests if pattern.search(t.qualified)]
            if pattern else r.tests
        )
        if not filtered:
            continue
        lines.append(str(r.path))
        for t in filtered:
            tag = "async " if t.is_async else ""
            suffix = (
                f"  [{t.parametrize_cases}×]"
                if t.parametrize_cases > 1 else ""
            )
            cls_prefix = f"{t.class_name}::" if t.class_name else ""
            lines.append(
                f"  {tag}{cls_prefix}{t.name} @ line {t.line}{suffix}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def render_structure(
    reports: List[FileReport],
    pattern: Optional[re.Pattern] = None,
) -> str:
    """Tree view: file → class → method."""
    lines: List[str] = []
    for r in reports:
        if not r.tests:
            continue
        filtered = (
            [t for t in r.tests if pattern.search(t.qualified)]
            if pattern else r.tests
        )
        if not filtered:
            continue
        lines.append(str(r.path))
        seen_classes: List[str] = []
        for t in filtered:
            key = t.class_name or "<module>"
            if key not in seen_classes:
                seen_classes.append(key)
                lines.append(f"  {key}")
            tag = "async " if t.is_async else ""
            suffix = (
                f"  [{t.parametrize_cases}×]"
                if t.parametrize_cases > 1 else ""
            )
            lines.append(f"    {tag}{t.name} @ line {t.line}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n" if lines else ""


def render_json(reports: List[FileReport]) -> str:
    """Machine-readable dump — test name, line, class, async, and
    parametrize-case count, per file."""
    payload = []
    for r in reports:
        payload.append({
            "path": str(r.path),
            "tests": [
                {
                    "name": t.name,
                    "line": t.line,
                    "is_async": t.is_async,
                    "class_name": t.class_name,
                    "parametrize_cases": t.parametrize_cases,
                    "decorators": t.decorators,
                }
                for t in r.tests
            ],
        })
    return json.dumps(payload, indent=2)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "path",
        help="File or directory to inspect. Directories walk recursively for test_*.py.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--list",
        dest="mode",
        action="store_const",
        const="list",
        help="Flat listing grouped by file + class (default).",
    )
    mode.add_argument(
        "--count",
        dest="mode",
        action="store_const",
        const="count",
        help="One-line-per-file summary plus total.",
    )
    mode.add_argument(
        "--structure",
        dest="mode",
        action="store_const",
        const="structure",
        help="Tree view: file → class → test.",
    )
    mode.add_argument(
        "--json",
        dest="mode",
        action="store_const",
        const="json",
        help="Machine-readable JSON dump.",
    )
    parser.add_argument(
        "--find",
        default=None,
        help=(
            "Regex to filter tests by fully-qualified name "
            "(``ClassName::test_name`` for class methods, ``test_name`` "
            "for module-level). Applies to --list and --structure modes."
        ),
    )
    parser.set_defaults(mode="list")
    args = parser.parse_args()

    target = Path(args.path)
    files = discover_files(target)
    reports = [inspect_file(p) for p in files]

    pattern: Optional[re.Pattern] = None
    if args.find:
        try:
            pattern = re.compile(args.find)
        except re.error as e:
            print(f"Invalid --find regex: {e}", file=sys.stderr)
            return 1

    if args.mode == "count":
        print(render_count(reports))
    elif args.mode == "structure":
        print(render_structure(reports, pattern=pattern))
    elif args.mode == "json":
        print(render_json(reports))
    else:  # list
        print(render_list(reports, pattern=pattern))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
