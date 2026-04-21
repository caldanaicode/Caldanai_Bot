"""Pretty-print the ``tail_channel --follow`` HTTP inspector buffer.

Wraps ``GET http://127.0.0.1:8765/tail`` so callers don't have to
curl + pipe to a one-liner every time they want to peek. Output
mirrors ``check_ideas``'s markdown shape (``##`` header per
message, ``>``-quoted body) so a transcript is pastable into a
planning conversation without reformatting. Includes a metadata
footer (buffer usage, dropped count, latest id).

Usage::

    python -m tools.tail_peek LIVE                    # full LIVE buffer
    python -m tools.tail_peek TEST                    # full TEST buffer
    python -m tools.tail_peek LIVE --since <msg_id>   # only newer than id
    python -m tools.tail_peek LIVE --tail 10          # last 10 after filter
    python -m tools.tail_peek LIVE --json             # raw JSON passthrough
    python -m tools.tail_peek LIVE --port 8999        # port override

No DB / auth involved — the inspector is a localhost HTTP
endpoint served by ``tail_channel --follow``. If that process
isn't running, this tool says so and exits non-zero rather than
hanging or emitting a cryptic stack trace.

Cursor tracking is intentionally stateless. Callers pass
``--since <id>`` when they want incremental reads; the tool
doesn't persist the cursor to disk (per the ring-buffer design
goal of avoiding needless filesystem writes for ephemeral tail
state). The metadata header always prints the newest id in the
returned snapshot so a follow-up call knows what to feed in.
"""

import argparse
import datetime
import json
import sys
import urllib.error
import urllib.request
from typing import Optional

# Windows consoles default to cp1252 which mangles em-dashes and
# other non-latin1 glyphs when piping. Reconfigure where supported.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass


_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8765

# Discord snowflakes encode ms since 2015-01-01 UTC in their top 42
# bits (bottom 22 bits are worker id + sequence). We synthesize a
# snowflake from an ISO timestamp to use as a before/after cursor —
# the inspector's since filter is ``id > since`` so an ID with the
# low bits zeroed sorts correctly as "everything strictly after this
# moment."
_DISCORD_EPOCH_MS = 1420070400000


def _snowflake_from_iso(ts: str) -> int:
    """Synthesize a Discord snowflake for an ISO-8601 timestamp.

    Accepts anything ``datetime.fromisoformat`` handles, including
    the trailing ``Z`` shorthand (normalized to ``+00:00``). Raises
    ``ValueError`` on malformed input; callers convert to a
    user-friendly argparse error.
    """
    normalized = ts.replace("Z", "+00:00")
    dt = datetime.datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        # Naive timestamp → treat as UTC so "2026-04-19T00:00" means
        # midnight UTC, not midnight-in-the-operator's-local-tz.
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    t_ms = int(dt.timestamp() * 1000)
    return max(0, (t_ms - _DISCORD_EPOCH_MS) << 22)


def _fetch(host: str, port: int, since: Optional[int]) -> dict:
    """GET the inspector. Converts connection refused / HTTP errors
    to operator-friendly stderr messages + non-zero exit."""
    url = f"http://{host}:{port}/tail"
    if since is not None:
        url = f"{url}?since={since}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} from inspector: {body}", file=sys.stderr)
        raise SystemExit(1)
    except urllib.error.URLError as e:
        print(
            f"Could not reach the inspector at {url}: {e.reason}. "
            f"Is `python -m tools.tail_channel <LIVE|TEST> --follow` "
            "running for this env?",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _format_snapshot(
    snapshot: dict,
    tail: Optional[int],
    before_snowflake: Optional[int] = None,
) -> str:
    """Render the snapshot as pastable markdown.

    ``tail`` (optional) slices to the last N messages after any
    ``since`` filter was applied server-side — useful when the
    buffer is large and only the freshest tail matters. The
    metadata footer always reflects the full buffer state (not
    the post-``tail`` slice) so a reader can tell when messages
    are being hidden vs. rolled off the back of the buffer.

    ``before_snowflake`` (optional) is a client-side upper-bound
    cursor — messages with ``id >= before_snowflake`` are dropped.
    Combined with ``since`` / ``--after`` this yields a timerange
    view of the buffer.
    """
    messages = snapshot.get("messages", [])
    if before_snowflake is not None:
        def _keep(m: dict) -> bool:
            mid = m.get("id")
            if not mid:
                return True
            try:
                return int(mid) < before_snowflake
            except (TypeError, ValueError):
                return True
        messages = [m for m in messages if _keep(m)]
    if tail is not None and tail > 0:
        messages = messages[-tail:]

    buffer_size = snapshot.get("buffer_size", 0)
    buffer_max = snapshot.get("buffer_max", 0)
    dropped = snapshot.get("dropped_count", 0)
    latest_id = messages[-1]["id"] if messages and messages[-1].get("id") else None

    header_parts = [
        f"# Tail peek — buffer {buffer_size}/{buffer_max}, dropped={dropped}",
    ]
    if latest_id:
        header_parts.append(f"latest id: `{latest_id}`")
    if tail is not None and tail > 0 and len(snapshot.get("messages", [])) > tail:
        header_parts.append(f"showing last {tail}")
    lines = [", ".join(header_parts)]

    if not messages:
        lines.append("")
        lines.append("*No messages to display.*")
        return "\n".join(lines) + "\n"

    lines.append(f"*{len(messages)} message(s).*")
    lines.append("")

    for msg in messages:
        timestamp = msg.get("timestamp", "<no timestamp>")
        author = msg.get("author", "<unknown>")
        msg_id = msg.get("id", "")
        content = (msg.get("content") or "").strip()

        suffix = f"  (id={msg_id})" if msg_id else ""
        lines.append(f"## {timestamp} — @{author}{suffix}")
        if content:
            for body_line in content.splitlines():
                lines.append(f"> {body_line}")
        else:
            lines.append("> *(no content)*")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    from tools._common import TAIL_ENVS, resolve_tail_env

    parser = argparse.ArgumentParser(
        usage="python -m tools.tail_peek {LIVE|TEST} [options]",
        description=(
            "Pretty-print a tail_channel inspector's buffer. The "
            "FIRST ARGUMENT picks which env's inspector to read: "
            "LIVE (port 8765) or TEST (port 8766). Override the "
            "port with --port when running a non-default inspector."
        ),
        epilog=(
            "Examples:\n"
            "  python -m tools.tail_peek LIVE\n"
            "  python -m tools.tail_peek LIVE --tail 20\n"
            "  python -m tools.tail_peek TEST --since 1496000000000000000\n"
            "  python -m tools.tail_peek LIVE --after 2026-04-21T00:00:00Z\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "env",
        choices=list(TAIL_ENVS.keys()),
        metavar="ENV",
        help=(
            "REQUIRED. LIVE or TEST. Picks the inspector port "
            "(LIVE=8765, TEST=8766)."
        ),
    )
    parser.add_argument(
        "--host",
        default=_DEFAULT_HOST,
        help=f"Inspector host (default: {_DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Inspector port override. Default is derived from the "
            "``env`` positional (LIVE=8765, TEST=8766)."
        ),
    )

    # --since and --after both set the lower-bound cursor; mutually
    # exclusive so the caller isn't surprised by one silently winning.
    since_group = parser.add_mutually_exclusive_group()
    since_group.add_argument(
        "--since",
        type=int,
        default=None,
        help=(
            "Only show messages with id strictly greater than this "
            "Discord snowflake. Copy from a previous run's 'latest id'."
        ),
    )
    since_group.add_argument(
        "--after",
        default=None,
        help=(
            "Only show messages newer than this ISO timestamp "
            "(e.g. 2026-04-19T00:00:00Z). Synthesizes a snowflake "
            "from the timestamp and applies it as --since."
        ),
    )

    parser.add_argument(
        "--before",
        default=None,
        help=(
            "Client-side upper-bound: only show messages older than "
            "this ISO timestamp. Combine with --after / --since for a "
            "timerange view."
        ),
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=None,
        help=(
            "Client-side slice: after any --since/--after/--before "
            "filter, show only the last N messages. Metadata footer "
            "still reflects the full buffer so you can see what got "
            "hidden vs. rolled off."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw JSON payload from the endpoint (for scripts).",
    )
    args = parser.parse_args()

    _, default_port = resolve_tail_env(args.env)
    if args.port is None:
        args.port = default_port

    since_value: Optional[int] = args.since
    if args.after is not None:
        try:
            since_value = _snowflake_from_iso(args.after)
        except ValueError as e:
            parser.error(f"--after: invalid ISO timestamp {args.after!r} ({e})")
    before_snowflake: Optional[int] = None
    if args.before is not None:
        try:
            before_snowflake = _snowflake_from_iso(args.before)
        except ValueError as e:
            parser.error(f"--before: invalid ISO timestamp {args.before!r} ({e})")

    snapshot = _fetch(args.host, args.port, since_value)
    if args.json:
        # Apply --before client-side to the JSON too so --json and
        # human output describe the same window.
        if before_snowflake is not None:
            snapshot = dict(snapshot)
            snapshot["messages"] = [
                m for m in snapshot.get("messages", [])
                if not m.get("id") or int(m["id"]) < before_snowflake
            ]
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(_format_snapshot(
            snapshot, args.tail, before_snowflake=before_snowflake,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
