"""Surface bg-Vael's in-conversation thoughts from her Claude Code
session log.

bg Vael runs as a separate Claude Code session at
``E:/dev/Vael-Caldanai/workspace/`` and plays Caldanai_Bot's TEST
channel as a naïve player. Her memory files capture intentional
observations she's chosen to write down — but the genuine little
moments live in her assistant text between tool calls and never
make it to memory: a "huh, that's odd" mid-fight, an in-character
sigh after a near-death, a fallacy she briefly entertains then
moves past. Those are exactly the moments that surface design
seeds and friction signal that her summarized memory doesn't
preserve.

Claude Code persists every session as a per-line JSON log at
``~/.claude/projects/<workspace-slug>/<session-id>.jsonl``. This
tool reads the latest session by default, filters to assistant
text content blocks (the prose she emits between tool calls),
and prints them with timestamps so you can scan a session for
voice / discovery / friction without spelunking the raw jsonl.

Usage
-----

::

    python -m tools.vael_thoughts                    # latest session, all text
    python -m tools.vael_thoughts --tail 30          # last 30 thoughts
    python -m tools.vael_thoughts --since 2026-05-02T07:00:00  # newer-than
    python -m tools.vael_thoughts --follow           # tail-and-follow, live
    python -m tools.vael_thoughts --session-id <id>  # specific session
    python -m tools.vael_thoughts --workspace E:/dev/Other  # different agent
    python -m tools.vael_thoughts --list             # list available sessions
    python -m tools.vael_thoughts --json             # raw JSON, one per line

Pairs with the overnight memory-diff cron: the cron picks up
what she wrote down deliberately; this tool picks up what she
*said* moment-to-moment. Together they cover both the curated
and the in-flight signal.

Schema notes
------------

The jsonl schema is internal to Claude Code and could shift
between versions. This tool is forgiving — it accepts unknown
fields, skips entries it can't parse, and only relies on:

- ``type == "assistant"`` to identify assistant turns
- ``message.content[]`` array of content blocks
- ``content[i].type == "text"`` and ``content[i].text`` for prose
- ``timestamp`` (ISO-8601) for ordering

``thinking`` blocks for Sonnet are encrypted-signature and not
human-readable, so they're skipped. If a future model surfaces
thinking as plain text, this tool will need a flag to include it.
"""

import argparse
import datetime
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator, List, Optional, Pattern, Tuple

from dotenv import load_dotenv

# Load main-project .env so BG_VAEL_WORKSPACE (and any sibling
# workspace-config env vars) resolve without pulling in
# caldanai.environment (which mandates DB_CONNECTION). Idempotent;
# safe under repeated tool invocations.
load_dotenv()

# Windows consoles default to cp1252 which mangles em-dashes and
# other non-latin1 glyphs when piping. Reconfigure where supported.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


def _default_workspace() -> Optional[str]:
    """Resolve the default workspace path from ``BG_VAEL_DIR`` env
    var (the bg-agent's root directory); the workspace is the
    ``workspace`` subdirectory of that root.

    Returns None when unset — the CLI errors with a helpful message
    rather than reading from a baked-in operator-specific path.
    Keeps any drive-letter / project-tree layout out of source.
    """
    raw = os.environ.get("BG_VAEL_DIR")
    if not raw:
        return None
    return str(Path(raw) / "workspace")


def _projects_root() -> Path:
    """Locate the Claude Code projects directory.

    On Windows this is ``%USERPROFILE%\\.claude\\projects``. On
    POSIX it's ``$HOME/.claude/projects``. ``Path.home()`` resolves
    to the right place on both.
    """
    return Path.home() / ".claude" / "projects"


def _workspace_slug(workspace: str) -> str:
    """Convert a workspace path to its Claude Code projects-dir slug.

    Claude Code derives the per-workspace projects-dir name by
    replacing path separators (``\\`` / ``/``) and the drive colon
    with ``-``. ``E:\\dev\\Vael-Caldanai\\workspace`` becomes
    ``E--dev-Vael-Caldanai-workspace``. We do the same so callers
    can pass a real path and we resolve to the right log dir.
    """
    s = workspace.replace("\\", "/").rstrip("/")
    s = s.replace(":", "-").replace("/", "-")
    return s


def _session_dir(workspace: str) -> Path:
    return _projects_root() / _workspace_slug(workspace)


def _list_sessions(workspace: str) -> List[Path]:
    """Return all jsonl session files in mtime-descending order."""
    d = _session_dir(workspace)
    if not d.exists():
        return []
    return sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)


def _latest_session(workspace: str) -> Optional[Path]:
    sessions = _list_sessions(workspace)
    return sessions[0] if sessions else None


def _resolve_session_path(workspace: str, session_id: Optional[str]) -> Path:
    """Resolve to a specific session jsonl, or latest if unspecified."""
    if session_id is not None:
        candidate = _session_dir(workspace) / f"{session_id}.jsonl"
        if not candidate.exists():
            raise SystemExit(
                f"No session file found at {candidate}. "
                f"Run with --list to see available session IDs."
            )
        return candidate
    latest = _latest_session(workspace)
    if latest is None:
        raise SystemExit(
            f"No session files in {_session_dir(workspace)}. "
            f"Has Claude Code ever run in {workspace}?"
        )
    return latest


def _format_tool_use(block: dict) -> str:
    """Render a ``tool_use`` content block as a short ``name(args)``
    string for human reading.

    Best-effort summarization: pulls the most-relevant input field
    per tool (Bash → ``command``, Read/Write/Edit → ``file_path``,
    WebFetch → ``url``, etc.). Falls back to truncated JSON when
    no special-case applies.
    """
    name = block.get("name", "?")
    inp = block.get("input") or {}
    if not isinstance(inp, dict):
        return f"{name}(?)"
    summary_keys = (
        "command", "file_path", "url", "pattern", "skill",
        "description", "prompt", "query", "content",
    )
    for key in summary_keys:
        val = inp.get(key)
        if isinstance(val, str) and val.strip():
            snippet = val.strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            return f"{name}({key}={snippet!r})"
    # Fallback: short JSON.
    try:
        rendered = json.dumps(inp, ensure_ascii=False)[:120]
    except (TypeError, ValueError):
        rendered = "..."
    return f"{name}({rendered})"


def _format_user_content(content) -> Optional[str]:
    """Render a user-entry's ``message.content`` (which may be a
    string or a list of blocks) as a single text string, or None if
    nothing readable is present.

    User content can be:
    - A plain string (typed input or Monitor notification)
    - A list of blocks: ``text`` and ``tool_result`` shapes
    """
    if isinstance(content, str):
        return content.strip() or None
    if isinstance(content, list):
        parts: List[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                t = block.get("text", "")
                if isinstance(t, str) and t.strip():
                    parts.append(t.strip())
            elif btype == "tool_result":
                inner = block.get("content")
                if isinstance(inner, str) and inner.strip():
                    parts.append(f"[tool_result] {inner.strip()}")
                elif isinstance(inner, list):
                    for sub in inner:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            t = sub.get("text", "")
                            if isinstance(t, str) and t.strip():
                                parts.append(f"[tool_result] {t.strip()}")
        return "\n".join(parts) if parts else None
    return None


def _iter_assistant_thoughts(
    path: Path,
    since: Optional[datetime.datetime] = None,
    include_sidechains: bool = False,
    mode: str = "text",
) -> Iterator[dict]:
    """Stream ``{timestamp, text, uuid}`` records from a jsonl file.

    Default ``mode="text"``: filter to ``type == "assistant"``
    entries' text-type content blocks (her in-conversation prose).

    ``mode="tool-use"``: assistant entries' ``tool_use`` blocks,
    rendered as ``name(input_summary)``. Surfaces what commands
    she invoked — combat actions, journal posts, memory edits.

    ``mode="user"``: ``type == "user"`` entries instead of
    assistant. Surfaces what bg Vael was responding to (operator
    prompts, Monitor stream notifications, tool results). User
    content can be string or block-list; both are handled.

    Each emission becomes its own record. An assistant turn that
    calls multiple tools may emit several text segments
    interleaved with tool-use blocks; we want each surfaced
    separately for fine-grained filtering downstream.

    By default, entries with ``isSidechain: true`` are skipped.
    Sidechains are sub-agent (Agent-tool) conversations whose
    voice is the sub-agent's, not the main agent's — usually
    noise when you're trying to capture the primary character's
    moment-to-moment thoughts. bg Vael never spawns sidechains
    (her CLAUDE.md forbids the Agent tool); the filter matters
    for other workspaces. Pass ``include_sidechains=True`` to
    surface them.

    ``since`` is optional ISO-cutoff — entries with timestamps at
    or before it are skipped. Useful for incremental scans.
    """
    if mode not in ("text", "tool-use", "user"):
        raise ValueError(f"unknown mode: {mode!r}")
    target_role = "user" if mode == "user" else "assistant"
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("type") != target_role:
                continue
            if not include_sidechains and entry.get("isSidechain"):
                continue
            ts_str = entry.get("timestamp")
            if ts_str:
                try:
                    ts = datetime.datetime.fromisoformat(
                        ts_str.replace("Z", "+00:00")
                    )
                except ValueError:
                    ts = None
            else:
                ts = None
            if since is not None and ts is not None and ts <= since:
                continue
            uuid = entry.get("uuid", "")
            content = (entry.get("message") or {}).get("content") or []

            if mode == "user":
                # User content can be string or block-list — handle both.
                rendered = _format_user_content(content)
                if rendered:
                    yield {"timestamp": ts_str, "text": rendered, "uuid": uuid}
                continue

            # Assistant modes — content is always a block list.
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if mode == "text":
                    if block.get("type") != "text":
                        continue
                    text = block.get("text", "").strip()
                    if not text:
                        continue
                    yield {"timestamp": ts_str, "text": text, "uuid": uuid}
                elif mode == "tool-use":
                    if block.get("type") != "tool_use":
                        continue
                    text = _format_tool_use(block)
                    yield {"timestamp": ts_str, "text": text, "uuid": uuid}


def _apply_filters(
    records: Iterator[dict],
    min_length: Optional[int] = None,
    max_length: Optional[int] = None,
    match: Optional[Pattern] = None,
) -> Iterator[dict]:
    """Apply length / regex filters to a record stream.

    All filters are AND'd. ``match`` is a compiled regex applied
    case-insensitively against ``record["text"]``. ``min_length``
    and ``max_length`` operate on the unstripped text length so
    callers can predict the gate by counting characters in a sample.
    """
    for rec in records:
        text = rec["text"]
        if min_length is not None and len(text) < min_length:
            continue
        if max_length is not None and len(text) > max_length:
            continue
        if match is not None and not match.search(text):
            continue
        yield rec


def _frequency_counts(records: List[dict]) -> "List[Tuple[int, str]]":
    """Group records by stripped text and return ``[(count, text), ...]``
    sorted by count descending, then text ascending.

    Repetition surfaces *behavioral* texture that length alone
    misses: an agent that mutters "Locked." 68 times is doing
    something different from one with 68 distinct one-liners.
    Repeated short phrases are the agent's combat-loop fingerprint;
    repeated medium phrases are template-leak (e.g. flavor strings
    bleeding into voice). Both worth surfacing.
    """
    from collections import Counter
    counter = Counter(r["text"].strip() for r in records)
    return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))


def _print_repeats(items: "List[Tuple[str, int]]", top_n: int) -> None:
    """Render ``--repeats`` output: header + top-N count/text rows."""
    total = sum(n for _, n in items)
    unique = len(items)
    print(f"unique thoughts: {unique} / total: {total}")
    print()
    if not items:
        return
    width = len(str(items[0][1]))
    for text, n in items[:top_n]:
        # Truncate long entries so the column stays readable; the
        # full text is always recoverable via --match <substr>.
        snippet = text if len(text) <= 100 else text[:97] + "..."
        print(f"  {n:>{width}}x  {snippet}")


def _length_stats(records: List[dict]) -> dict:
    """Return histogram + summary stats for a record list.

    Buckets match the heuristic boundaries useful for thought
    triage: sub-50 chars are usually combat-tactical mutters, 50-150
    are command-decision-with-context, 150-300 are observation +
    reasoning, 300+ are full reflective beats. Worth sticking to
    these so callers comparing across sessions get the same axes.
    """
    if not records:
        return {"count": 0, "buckets": {}, "min": 0, "max": 0, "median": 0}
    lengths = sorted(len(r["text"]) for r in records)
    buckets = {
        "<50": sum(1 for l in lengths if l < 50),
        "50-150": sum(1 for l in lengths if 50 <= l < 150),
        "150-300": sum(1 for l in lengths if 150 <= l < 300),
        "300-600": sum(1 for l in lengths if 300 <= l < 600),
        "600+": sum(1 for l in lengths if l >= 600),
    }
    return {
        "count": len(lengths),
        "buckets": buckets,
        "min": lengths[0],
        "max": lengths[-1],
        "median": lengths[len(lengths) // 2],
    }


def _print_stats(stats: dict) -> None:
    print(f"total thoughts: {stats['count']}")
    if stats["count"] == 0:
        return
    print(f"length min/median/max: {stats['min']} / {stats['median']} / {stats['max']}")
    print()
    print("length distribution:")
    for label, n in stats["buckets"].items():
        bar = "#" * min(50, n)
        print(f"  {label:>8}  {n:5d}  {bar}")


def _format_local(ts_str: Optional[str]) -> str:
    """Render an ISO-8601 timestamp in operator local time, short form."""
    if not ts_str:
        return "?"
    try:
        dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except ValueError:
        return ts_str
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _print_thoughts(records: List[dict], as_json: bool) -> None:
    if as_json:
        for rec in records:
            print(json.dumps(rec, ensure_ascii=False))
        return
    for rec in records:
        ts = _format_local(rec.get("timestamp"))
        print(f"[{ts}]")
        print(rec["text"])
        print()


def _follow(
    path: Path,
    since: Optional[datetime.datetime],
    as_json: bool,
    include_sidechains: bool = False,
    mode: str = "text",
    poll_seconds: float = 2.0,
) -> None:
    """Tail-follow the jsonl, emitting new content as it lands.

    Re-reads the file from scratch on each poll because jsonl
    entries can be appended between reads — we track the last
    yielded uuid and skip everything up through it. Cheap enough
    for a live capture; the file is small relative to memory.

    The same ``mode`` selector that drives the one-shot read
    applies here — follow can target text, tool-use, or user
    streams independently.
    """
    seen: set = set()
    cutoff = since
    # Initial backfill — print everything matching the cutoff, then
    # switch to "new only" mode for subsequent polls.
    for rec in _iter_assistant_thoughts(
        path, since=cutoff, include_sidechains=include_sidechains, mode=mode,
    ):
        # uuid alone collides when one entry emits multiple blocks
        # (one assistant turn, multiple text segments or tool_uses).
        # Pair (uuid, text) for de-dup so each block shows once.
        key = (rec["uuid"], rec["text"])
        seen.add(key)
        _print_thoughts([rec], as_json)
        sys.stdout.flush()
    try:
        while True:
            time.sleep(poll_seconds)
            for rec in _iter_assistant_thoughts(
                path, since=cutoff, include_sidechains=include_sidechains,
                mode=mode,
            ):
                key = (rec["uuid"], rec["text"])
                if key in seen:
                    continue
                seen.add(key)
                _print_thoughts([rec], as_json)
                sys.stdout.flush()
    except KeyboardInterrupt:
        return


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--workspace",
        default=None,
        help=(
            "Workspace path whose Claude Code session log to read. "
            "Defaults to ``$BG_VAEL_DIR/workspace`` when that env "
            "var is set; otherwise must be supplied explicitly. "
            "Keeps operator-specific path layout out of source."
        ),
    )
    ap.add_argument(
        "--session-id",
        default=None,
        help=(
            "Specific session UUID to read. Default: latest session "
            "in the workspace, by file mtime."
        ),
    )
    ap.add_argument(
        "--tail",
        type=int,
        default=None,
        help="Print only the last N thoughts. Useful for quick scans.",
    )
    ap.add_argument(
        "--since",
        default=None,
        help=(
            "ISO-8601 cutoff; only emit thoughts strictly after this "
            "timestamp. Naive datetimes are treated as UTC."
        ),
    )
    ap.add_argument(
        "--follow", "-f",
        action="store_true",
        help=(
            "After printing the initial batch, poll the file and "
            "print new thoughts as they land. Ctrl-C to stop."
        ),
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help=(
            "List available session jsonl files for the workspace, "
            "newest first, with mtime and size. Skips the read."
        ),
    )
    ap.add_argument(
        "--json",
        action="store_true",
        help=(
            "Emit one JSON record per line ({timestamp, text, uuid}) "
            "instead of the formatted text view."
        ),
    )
    ap.add_argument(
        "--include-sidechains",
        action="store_true",
        help=(
            "Include text from sub-agent (Agent-tool) sidechain "
            "conversations. Default: skipped, since their voice is "
            "the sub-agent's, not the main agent's. bg Vael never "
            "spawns sidechains, so this is a no-op for her log."
        ),
    )
    ap.add_argument(
        "--mode",
        choices=("text", "tool-use", "user"),
        default="text",
        help=(
            "What to surface from each entry. "
            "``text`` (default): assistant text content blocks — her "
            "in-conversation prose. "
            "``tool-use``: assistant tool_use blocks rendered as "
            "``name(input_summary)`` — what commands she invoked. "
            "``user``: user-role entries (operator prompts + Monitor "
            "stream notifications + tool results) — what she was "
            "responding to."
        ),
    )
    ap.add_argument(
        "--match",
        default=None,
        metavar="REGEX",
        help=(
            "Case-insensitive regex applied to the thought text. "
            "Matches anywhere in the body (use ^/$ anchors for "
            "start/end). Useful for surfacing fallacy chains "
            "(e.g. --match '1\\.5x|multiplier') or relational "
            "moments (--match 'kin|caels|serena')."
        ),
    )
    ap.add_argument(
        "--min-length",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Drop thoughts shorter than N characters. Useful for "
            "filtering out terse combat mutters when looking for "
            "reflective beats — try --min-length 200 for full "
            "observation-and-reasoning thoughts."
        ),
    )
    ap.add_argument(
        "--max-length",
        type=int,
        default=None,
        metavar="N",
        help="Drop thoughts longer than N characters.",
    )
    ap.add_argument(
        "--longest",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Sort thoughts by text length descending and emit the "
            "top N. Surfaces the richest reflections — these are "
            "where in-fiction voice and design seeds tend to live. "
            "Mutually exclusive with --tail."
        ),
    )
    ap.add_argument(
        "--stats",
        action="store_true",
        help=(
            "Print a length-distribution histogram and summary "
            "instead of emitting thoughts. Honors --match / "
            "--min-length / --max-length / --since for "
            "filtered-subset stats."
        ),
    )
    ap.add_argument(
        "--repeats",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Group filtered thoughts by exact text and print the "
            "top N most-repeated, with counts. Surfaces combat-loop "
            "fingerprint (e.g. 'Locked.' 68x) and any flavor "
            "template leak. Mutually exclusive with --longest, "
            "--tail, and --stats."
        ),
    )
    args = ap.parse_args(argv)

    view_modes = [
        ("--tail", args.tail is not None),
        ("--longest", args.longest is not None),
        ("--stats", bool(args.stats)),
        ("--repeats", args.repeats is not None),
    ]
    active = [name for name, on in view_modes if on]
    if len(active) > 1:
        ap.error(f"mutually exclusive view modes: {', '.join(active)}")

    if args.workspace is None:
        args.workspace = _default_workspace()
    if not args.workspace:
        ap.error(
            "No workspace: pass --workspace <path> or set "
            "BG_VAEL_DIR in the environment so the default "
            "(``$BG_VAEL_DIR/workspace``) resolves."
        )

    if args.list:
        sessions = _list_sessions(args.workspace)
        if not sessions:
            print(
                f"No session files in {_session_dir(args.workspace)}",
                file=sys.stderr,
            )
            return 1
        for p in sessions:
            stat = p.stat()
            mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            size_kb = stat.st_size / 1024
            print(f"{p.stem}  {mtime}  {size_kb:>8.1f} KB")
        return 0

    since: Optional[datetime.datetime] = None
    if args.since is not None:
        try:
            since = datetime.datetime.fromisoformat(
                args.since.replace("Z", "+00:00")
            )
            if since.tzinfo is None:
                since = since.replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            ap.error(f"--since must be ISO-8601, got: {args.since!r}")

    match: Optional[Pattern] = None
    if args.match is not None:
        try:
            match = re.compile(args.match, re.IGNORECASE)
        except re.error as e:
            ap.error(f"--match regex invalid: {e}")

    path = _resolve_session_path(args.workspace, args.session_id)

    if args.follow:
        _follow(
            path, since, args.json, args.include_sidechains,
            mode=args.mode,
        )
        return 0

    records = list(
        _apply_filters(
            _iter_assistant_thoughts(
                path,
                since=since,
                include_sidechains=args.include_sidechains,
                mode=args.mode,
            ),
            min_length=args.min_length,
            max_length=args.max_length,
            match=match,
        )
    )

    if args.stats:
        _print_stats(_length_stats(records))
        return 0

    if args.repeats is not None:
        _print_repeats(_frequency_counts(records), args.repeats)
        return 0

    if args.longest is not None:
        records = sorted(records, key=lambda r: -len(r["text"]))[: args.longest]
    elif args.tail is not None:
        records = records[-args.tail:]

    _print_thoughts(records, args.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
