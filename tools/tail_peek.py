"""Pretty-print the ``tail_channel --follow`` HTTP inspector buffer.

Wraps ``GET http://127.0.0.1:8765/tail`` so callers don't have to
curl + pipe to a one-liner every time they want to peek. Output
mirrors ``check_ideas``'s markdown shape (``##`` header per
message, ``>``-quoted body) so a transcript is pastable into a
planning conversation without reformatting. Includes a metadata
footer (buffer usage, dropped count, latest id).

Usage::

    python -m tools.tail_peek                         # full buffer
    python -m tools.tail_peek --since <message_id>    # only newer than id
    python -m tools.tail_peek --tail 10               # last 10 after filter
    python -m tools.tail_peek --json                  # raw JSON passthrough
    python -m tools.tail_peek --port 8766             # custom port

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
            f"Is `python -m tools.tail_channel --follow` running?",
            file=sys.stderr,
        )
        raise SystemExit(1)


def _format_snapshot(snapshot: dict, tail: Optional[int]) -> str:
    """Render the snapshot as pastable markdown.

    ``tail`` (optional) slices to the last N messages after any
    ``since`` filter was applied server-side — useful when the
    buffer is large and only the freshest tail matters. The
    metadata footer always reflects the full buffer state (not
    the post-``tail`` slice) so a reader can tell when messages
    are being hidden vs. rolled off the back of the buffer.
    """
    messages = snapshot.get("messages", [])
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
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--host",
        default=_DEFAULT_HOST,
        help=f"Inspector host (default: {_DEFAULT_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=_DEFAULT_PORT,
        help=f"Inspector port (default: {_DEFAULT_PORT}).",
    )
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        help=(
            "Only show messages with id strictly greater than this "
            "Discord snowflake. Copy from a previous run's 'latest id'."
        ),
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=None,
        help=(
            "Client-side slice: after any --since filter, show only the "
            "last N messages. Metadata footer still reflects the full "
            "buffer so you can see what got hidden vs. rolled off."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw JSON payload from the endpoint (for scripts).",
    )
    args = parser.parse_args()

    snapshot = _fetch(args.host, args.port, args.since)
    if args.json:
        print(json.dumps(snapshot, indent=2, ensure_ascii=False))
    else:
        print(_format_snapshot(snapshot, args.tail))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
