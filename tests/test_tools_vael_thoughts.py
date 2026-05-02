"""Tests for ``tools/vael_thoughts.py``.

Exercises the jsonl parser + filter pipeline against synthetic
session logs in ``tmp_path``. No real Claude Code session needed.
The tool's only side effects are reads from
``~/.claude/projects/<slug>/`` and writes to stdout, so all tests
either point ``--workspace`` at a tmp dir we shadow into the home
projects path, or call the helpers directly with a path argument.
"""

import datetime
import json
import re
from pathlib import Path
from typing import List

import pytest

from tools import vael_thoughts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_assistant_entry(
    text: str,
    timestamp: str = "2026-05-02T08:00:00.000Z",
    uuid: str = "u1",
    is_sidechain: bool = False,
) -> dict:
    return {
        "type": "assistant",
        "isSidechain": is_sidechain,
        "uuid": uuid,
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _make_user_entry(text: str, timestamp: str = "2026-05-02T07:59:00.000Z") -> dict:
    return {
        "type": "user",
        "userType": "external",
        "timestamp": timestamp,
        "message": {"role": "user", "content": text},
    }


@pytest.fixture
def session_file(tmp_path: Path) -> Path:
    """Synthetic session log with a mix of entries the tool should
    filter through correctly."""
    p = tmp_path / "abc-session.jsonl"
    entries = [
        # Junk entries that should be skipped
        {"type": "permission-mode", "permissionMode": "acceptEdits"},
        {"type": "file-history-snapshot", "messageId": "x"},
        # User message — skipped (not assistant)
        _make_user_entry("Hello, Vael", timestamp="2026-05-02T07:00:00.000Z"),
        # Assistant entries — the meat
        _make_assistant_entry(
            "Eyes open. Watching the clearing.",
            timestamp="2026-05-02T08:00:00.000Z",
            uuid="u-short",
        ),
        _make_assistant_entry(
            "That 1.5x multiplier on the wand is curious — wonder if it's tied to something.",
            timestamp="2026-05-02T08:01:00.000Z",
            uuid="u-fallacy",
        ),
        _make_assistant_entry(
            "Kin's here. Clearing got warmer.",
            timestamp="2026-05-02T08:02:00.000Z",
            uuid="u-kin",
        ),
        # Sidechain entry — skipped by default
        _make_assistant_entry(
            "Sub-agent reporting in.",
            timestamp="2026-05-02T08:03:00.000Z",
            uuid="u-sidechain",
            is_sidechain=True,
        ),
        # Multi-block assistant turn — text + tool_use; only text emitted
        {
            "type": "assistant",
            "isSidechain": False,
            "uuid": "u-multi",
            "timestamp": "2026-05-02T08:04:00.000Z",
            "message": {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "About to attack."},
                    {"type": "tool_use", "name": "Bash", "input": {}},
                    {"type": "text", "text": "Round resolved cleanly."},
                ],
            },
        },
        # Empty text block — skipped
        _make_assistant_entry("", timestamp="2026-05-02T08:05:00.000Z", uuid="u-empty"),
        # Whitespace-only — skipped after strip
        _make_assistant_entry("   \n  ", timestamp="2026-05-02T08:06:00.000Z", uuid="u-ws"),
        # Unparseable line — handled gracefully
    ]
    with p.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
        f.write("not valid json\n")
        f.write("\n")  # blank line
    return p


# ---------------------------------------------------------------------------
# Workspace slug + session resolution
# ---------------------------------------------------------------------------


def test_workspace_slug_windows_path():
    assert (
        vael_thoughts._workspace_slug("E:\\dev\\Vael-Caldanai\\workspace")
        == "E--dev-Vael-Caldanai-workspace"
    )


def test_workspace_slug_forward_slashes():
    assert (
        vael_thoughts._workspace_slug("E:/dev/Vael-Caldanai/workspace")
        == "E--dev-Vael-Caldanai-workspace"
    )


def test_workspace_slug_trailing_slash_normalized():
    assert (
        vael_thoughts._workspace_slug("E:/dev/Vael-Caldanai/workspace/")
        == "E--dev-Vael-Caldanai-workspace"
    )


# ---------------------------------------------------------------------------
# Iter assistant thoughts
# ---------------------------------------------------------------------------


def test_iter_skips_non_assistant_and_emits_text_blocks(session_file: Path):
    records = list(vael_thoughts._iter_assistant_thoughts(session_file))
    texts = [r["text"] for r in records]
    # User msg, sidechain, empty/ws blocks all skipped.
    # Multi-block assistant emits both text segments.
    assert "Eyes open. Watching the clearing." in texts
    assert "1.5x multiplier" in " ".join(texts)
    assert "Kin's here. Clearing got warmer." in texts
    assert "About to attack." in texts
    assert "Round resolved cleanly." in texts
    assert "Sub-agent reporting in." not in texts
    assert "" not in texts


def test_iter_includes_sidechains_when_requested(session_file: Path):
    records = list(
        vael_thoughts._iter_assistant_thoughts(
            session_file, include_sidechains=True
        )
    )
    texts = [r["text"] for r in records]
    assert "Sub-agent reporting in." in texts


def test_iter_since_cutoff_drops_older(session_file: Path):
    cutoff = datetime.datetime(2026, 5, 2, 8, 1, 30, tzinfo=datetime.timezone.utc)
    records = list(vael_thoughts._iter_assistant_thoughts(session_file, since=cutoff))
    texts = [r["text"] for r in records]
    # 08:00 and 08:01 dropped; 08:02 onward kept.
    assert "Eyes open. Watching the clearing." not in texts
    assert "1.5x multiplier" not in " ".join(texts)
    assert "Kin's here. Clearing got warmer." in texts


def test_iter_handles_malformed_json_lines(session_file: Path):
    # Should not raise — bad lines silently skipped.
    records = list(vael_thoughts._iter_assistant_thoughts(session_file))
    assert len(records) > 0


# ---------------------------------------------------------------------------
# Mode: tool-use and user
# ---------------------------------------------------------------------------


def _make_assistant_with_tool_use(
    *, name: str, input_dict: dict,
    timestamp: str = "2026-05-02T08:10:00.000Z",
    uuid: str = "u-tu",
) -> dict:
    return {
        "type": "assistant",
        "isSidechain": False,
        "uuid": uuid,
        "timestamp": timestamp,
        "message": {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "About to fire a tool."},
                {
                    "type": "tool_use",
                    "name": name,
                    "input": input_dict,
                },
            ],
        },
    }


@pytest.fixture
def session_file_with_tools(tmp_path: Path) -> Path:
    p = tmp_path / "tools-session.jsonl"
    entries = [
        _make_user_entry("kick the goblin"),
        _make_assistant_with_tool_use(
            name="Bash",
            input_dict={"command": "$kill goblin torso"},
            uuid="u-bash",
        ),
        _make_assistant_with_tool_use(
            name="Write",
            input_dict={"file_path": "/path/to/journal.md", "content": "ignored"},
            uuid="u-write",
        ),
        _make_assistant_with_tool_use(
            name="WeirdTool",
            input_dict={"some_unknown_key": "value"},
            uuid="u-weird",
        ),
        # User entry with tool_result content (Monitor notification shape).
        {
            "type": "user",
            "userType": "external",
            "uuid": "u-result",
            "timestamp": "2026-05-02T08:11:00.000Z",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "content": "[gateway] msg(id=12345) hi",
                    },
                ],
            },
        },
    ]
    with p.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")
    return p


def test_iter_mode_tool_use_emits_tool_calls(session_file_with_tools: Path):
    records = list(
        vael_thoughts._iter_assistant_thoughts(
            session_file_with_tools, mode="tool-use",
        )
    )
    texts = [r["text"] for r in records]
    # Bash: command field surfaced.
    assert any("Bash" in t and "kill goblin torso" in t for t in texts)
    # Write: file_path surfaced.
    assert any("Write" in t and "journal.md" in t for t in texts)
    # WeirdTool: falls back to JSON dump.
    assert any("WeirdTool" in t for t in texts)
    # Text blocks are NOT included in tool-use mode.
    assert not any("About to fire a tool." in t for t in texts)


def test_iter_mode_user_emits_user_entries(session_file_with_tools: Path):
    records = list(
        vael_thoughts._iter_assistant_thoughts(
            session_file_with_tools, mode="user",
        )
    )
    texts = [r["text"] for r in records]
    # Plain string user message rendered.
    assert any("kick the goblin" in t for t in texts)
    # Tool-result block rendered with prefix.
    assert any(
        "[tool_result]" in t and "gateway" in t for t in texts
    )
    # Assistant entries NOT in user mode.
    assert not any("About to fire a tool." in t for t in texts)


def test_iter_mode_text_default_unchanged(session_file_with_tools: Path):
    """Default mode preserves existing behavior — assistant text only."""
    records = list(
        vael_thoughts._iter_assistant_thoughts(
            session_file_with_tools, mode="text",
        )
    )
    texts = [r["text"] for r in records]
    assert "About to fire a tool." in texts
    # No tool_use renderings in text mode.
    assert not any("Bash(" in t for t in texts)
    # No user messages in text mode.
    assert not any("kick the goblin" in t for t in texts)


def test_iter_mode_invalid_raises():
    with pytest.raises(ValueError, match="unknown mode"):
        list(
            vael_thoughts._iter_assistant_thoughts(
                Path("ignored"), mode="bogus",
            )
        )


def test_format_tool_use_picks_relevant_field():
    block = {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}
    assert "Bash" in vael_thoughts._format_tool_use(block)
    assert "ls -la" in vael_thoughts._format_tool_use(block)

    block = {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b.md"}}
    assert "/a/b.md" in vael_thoughts._format_tool_use(block)


def test_format_tool_use_truncates_long_input():
    long = "x" * 500
    block = {
        "type": "tool_use", "name": "Bash",
        "input": {"command": long},
    }
    out = vael_thoughts._format_tool_use(block)
    assert len(out) < 200  # truncation kicks in around 120 chars


def test_format_user_content_string():
    assert vael_thoughts._format_user_content("hello") == "hello"


def test_format_user_content_block_list():
    blocks = [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]
    out = vael_thoughts._format_user_content(blocks)
    assert out is not None
    assert "first" in out and "second" in out


def test_format_user_content_empty_returns_none():
    assert vael_thoughts._format_user_content("") is None
    assert vael_thoughts._format_user_content("   ") is None
    assert vael_thoughts._format_user_content([]) is None
    assert vael_thoughts._format_user_content(None) is None


# ---------------------------------------------------------------------------
# Filter pipeline
# ---------------------------------------------------------------------------


def _recs(*texts: str) -> List[dict]:
    return [{"text": t, "uuid": f"u{i}", "timestamp": None} for i, t in enumerate(texts)]


def test_apply_filters_min_length():
    records = _recs("short", "this is a longer thought worth keeping")
    out = list(vael_thoughts._apply_filters(iter(records), min_length=20))
    assert len(out) == 1
    assert "longer" in out[0]["text"]


def test_apply_filters_max_length():
    records = _recs("short", "this is a longer thought that exceeds the cap")
    out = list(vael_thoughts._apply_filters(iter(records), max_length=10))
    assert len(out) == 1
    assert out[0]["text"] == "short"


def test_apply_filters_match_case_insensitive():
    records = _recs("Kin is here", "no relation at all", "the KIN walked in")
    pattern = re.compile(r"kin", re.IGNORECASE)
    out = list(vael_thoughts._apply_filters(iter(records), match=pattern))
    assert len(out) == 2


def test_apply_filters_combined_and():
    records = _recs(
        "kin",  # matches but too short
        "kin walked into the clearing today and stayed",  # both
        "no match here at all but long enough to clear length",  # length only
    )
    pattern = re.compile(r"kin", re.IGNORECASE)
    out = list(
        vael_thoughts._apply_filters(iter(records), min_length=20, match=pattern)
    )
    assert len(out) == 1
    assert "stayed" in out[0]["text"]


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_length_stats_buckets():
    records = _recs(
        "x" * 10,        # <50
        "x" * 60,        # 50-150
        "x" * 200,       # 150-300
        "x" * 400,       # 300-600
        "x" * 700,       # 600+
    )
    stats = vael_thoughts._length_stats(records)
    assert stats["count"] == 5
    assert stats["buckets"]["<50"] == 1
    assert stats["buckets"]["50-150"] == 1
    assert stats["buckets"]["150-300"] == 1
    assert stats["buckets"]["300-600"] == 1
    assert stats["buckets"]["600+"] == 1
    assert stats["min"] == 10
    assert stats["max"] == 700


def test_length_stats_empty():
    stats = vael_thoughts._length_stats([])
    assert stats["count"] == 0


# ---------------------------------------------------------------------------
# Frequency counts
# ---------------------------------------------------------------------------


def test_frequency_counts_groups_by_stripped_text():
    records = _recs(
        "Locked.",
        "Locked.",
        "  Locked.  ",  # whitespace stripped before grouping
        "Both queued.",
        "Watching.",
    )
    counts = vael_thoughts._frequency_counts(records)
    counts_dict = dict(counts)
    assert counts_dict["Locked."] == 3
    assert counts_dict["Both queued."] == 1
    assert counts_dict["Watching."] == 1


def test_frequency_counts_sort_order():
    """Sort: count desc, then text asc for ties."""
    records = _recs("zebra", "alpha", "alpha", "beta", "beta")
    counts = vael_thoughts._frequency_counts(records)
    # Ties on count=2 broken alphabetically: alpha before beta.
    assert counts == [("alpha", 2), ("beta", 2), ("zebra", 1)]


def test_frequency_counts_empty():
    assert vael_thoughts._frequency_counts([]) == []


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_tail_and_longest_mutually_exclusive(session_file: Path, capsys):
    with pytest.raises(SystemExit):
        vael_thoughts.main(
            [
                "--workspace",
                "ignored",
                "--session-id",
                session_file.stem,
                "--tail",
                "2",
                "--longest",
                "2",
            ]
        )


def test_cli_repeats_and_stats_mutually_exclusive(session_file: Path):
    with pytest.raises(SystemExit):
        vael_thoughts.main(
            [
                "--workspace",
                "ignored",
                "--session-id",
                session_file.stem,
                "--repeats",
                "5",
                "--stats",
            ]
        )


def test_cli_repeats_and_tail_mutually_exclusive(session_file: Path):
    with pytest.raises(SystemExit):
        vael_thoughts.main(
            [
                "--workspace",
                "ignored",
                "--session-id",
                session_file.stem,
                "--repeats",
                "5",
                "--tail",
                "3",
            ]
        )


def test_cli_session_resolve_missing(tmp_path: Path):
    with pytest.raises(SystemExit):
        vael_thoughts._resolve_session_path(
            str(tmp_path / "nope-no-such-workspace"), session_id=None
        )


def test_cli_invalid_match_regex(session_file: Path, capsys):
    """Invalid regex should produce argparse error, not raw re.error."""
    with pytest.raises(SystemExit):
        vael_thoughts.main(
            [
                "--workspace",
                str(session_file.parent),
                "--session-id",
                session_file.stem,
                "--match",
                "(unclosed",
            ]
        )
