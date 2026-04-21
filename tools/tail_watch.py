"""Poll the ``tail_channel --follow`` HTTP inspector and emit
notable messages as one-line events for Monitor-style consumption.

Exists so overnight / AFK monitoring of a live Discord channel can
surface only the things an operator would act on — player questions
about mechanics, potential bug complaints, bot tracebacks, party
wipes — without drowning the operator in normal combat chatter.

Contrast with ``tail_peek`` (pretty-prints everything) and
``tail_channel`` (raw server / buffer): ``tail_watch`` is a filter
for "what needs my attention?"

Usage::

    python -m tools.tail_watch LIVE                 # poll LIVE inspector (port 8765)
    python -m tools.tail_watch TEST --interval 600  # poll TEST, 10-min cadence
    python -m tools.tail_watch LIVE --since <snowflake>
    python -m tools.tail_watch LIVE --port 8999     # port override

Emits one line per notable event::

    [PLAYER-Q] [2026-04-21 05:23] @Celowin: Is that fire working correctly? ...
    [COMPLAINT?] [2026-04-21 05:30] @alice: dragon seems broken ...
    [ERROR] [2026-04-21 05:45] @Caldanai Bot: Traceback (most recent call last) ...
    [WIPE] [2026-04-21 06:01] @Caldanai Bot: (3 deaths in one poll window)

Exits 0 on SIGINT / SIGTERM (for clean Monitor shutdown).
"""

import argparse
import json
import signal
import sys
import time
import urllib.request
from typing import List, Optional


# Phrases in player messages that look like bug-reports or
# balance-complaints. Match lowercased.
_COMPLAINT_HINTS = (
    "broken",
    "bug",
    "weird",
    "doesn't work",
    "doesnt work",
    "isn't working",
    "isnt working",
    "why did",
    "why is",
    "wait what",
)

# Bot-output patterns that indicate an actual error, not combat
# flavor. Combat text contains "damage" / "attack" but never
# ``Traceback`` or the literal string ``Error:``.
_ERROR_HINTS = (
    "traceback",
    "exception",
    "error:",
)

# Party-wipe detection: more than this many "crumples to the ground"
# in one poll window flags as a WIPE event.
_WIPE_THRESHOLD = 2

_BOT_AUTHOR_HINT = "caldanai bot"


def _fetch(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def _classify(msg: dict) -> Optional[str]:
    """Return a tag for the message, or ``None`` if it's not notable."""
    content = msg.get("content", "")
    author = msg.get("author", "") or ""
    low_content = content.lower()
    low_author = author.lower()
    is_bot = _BOT_AUTHOR_HINT in low_author

    if any(hint in low_content for hint in _ERROR_HINTS):
        return "ERROR"
    if not is_bot:
        # Player-authored messages only flow through the player
        # filters; the bot's combat narration routinely contains
        # "?" (questions inside flavor) and complaint-shaped verbs.
        if any(hint in low_content for hint in _COMPLAINT_HINTS):
            return "COMPLAINT?"
        # Player question with no command prefix — short, single-line,
        # directed-at-the-room kind. Filters out ``$`` commands and
        # long multi-paragraph copy-pastes.
        if (
            "?" in content
            and not content.lstrip().startswith("$")
            and len(content) < 300
            and "\n" not in content.strip().strip("\n")
        ):
            return "PLAYER-Q"
    return None


def _one_liner(content: str, limit: int = 180) -> str:
    """Collapse to a single line capped at ``limit`` chars with
    ellipsis when truncated."""
    joined = " ".join(content.split())
    if len(joined) <= limit:
        return joined
    return joined[: limit - 1] + "\u2026"


def _emit_message_events(messages: List[dict]) -> None:
    """Print one line per notable message + a wipe line if many
    ``crumples`` landed in this window. ``flush=True`` on every
    print so Monitor sees the line immediately."""
    wipe_count = 0
    wipe_last_ts = ""
    for m in messages:
        content = m.get("content", "") or ""
        author = m.get("author", "?")
        ts = (m.get("timestamp", "") or "")[:16].replace("T", " ")
        tag = _classify(m)
        if tag:
            print(
                f"[{tag}] [{ts}] {author}: {_one_liner(content)}",
                flush=True,
            )
        lower = content.lower()
        if "crumples to the ground" in lower:
            wipe_count += lower.count("crumples to the ground")
            wipe_last_ts = ts
    if wipe_count >= _WIPE_THRESHOLD:
        print(
            f"[WIPE] [{wipe_last_ts}] ({wipe_count} deaths in this "
            "poll window)",
            flush=True,
        )


def _watch(host: str, port: int, interval: int, since: Optional[str]) -> int:
    base = f"http://{host}:{port}/tail"
    last_id = since or ""

    # Graceful shutdown — SIGINT or SIGTERM (Monitor stop) should
    # exit 0 without a stack trace.
    def _bye(*_):
        print("[watcher] shutting down cleanly.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, _bye)
    try:
        signal.signal(signal.SIGTERM, _bye)
    except Exception:
        # Windows doesn't always allow SIGTERM; SIGINT alone is fine.
        pass

    print(
        f"[watcher] polling {base} every {interval}s — filter="
        "ERROR/COMPLAINT?/PLAYER-Q/WIPE",
        flush=True,
    )
    while True:
        try:
            url = base + (f"?since={last_id}" if last_id else "")
            data = _fetch(url)
        except Exception as e:
            print(f"[watcher] poll error: {e}", flush=True)
            time.sleep(interval)
            continue

        messages = data.get("messages", []) or []
        if messages:
            last_id = messages[-1].get("id", last_id) or last_id
            _emit_message_events(messages)
        time.sleep(interval)


def main(argv: Optional[List[str]] = None) -> int:
    from tools._common import TAIL_ENVS, resolve_tail_env

    ap = argparse.ArgumentParser(
        usage="python -m tools.tail_watch {LIVE|TEST} [options]",
        description=(
            "Filtered watcher over a tail_channel inspector — emits "
            "only notable events (errors, complaints, player "
            "questions, wipes). The FIRST ARGUMENT picks which env "
            "to watch: LIVE (port 8765) or TEST (port 8766)."
        ),
        epilog=(
            "Examples:\n"
            "  python -m tools.tail_watch LIVE\n"
            "  python -m tools.tail_watch TEST --interval 300\n"
            "  python -m tools.tail_watch LIVE --since 1496000000000000000\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "env",
        choices=list(TAIL_ENVS.keys()),
        metavar="ENV",
        help=(
            "REQUIRED. LIVE or TEST. Picks the inspector port "
            "(LIVE=8765, TEST=8766)."
        ),
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument(
        "--port", type=int, default=None,
        help=(
            "Inspector port override. Default derived from ``env``."
        ),
    )
    ap.add_argument(
        "--interval", type=int, default=900,
        help="Poll interval in seconds (default: 900 = 15 min).",
    )
    ap.add_argument(
        "--since", default=None,
        help="Start from this Discord snowflake (inclusive after).",
    )
    args = ap.parse_args(argv)
    _, default_port = resolve_tail_env(args.env)
    port = args.port if args.port is not None else default_port
    return _watch(args.host, port, args.interval, args.since)


if __name__ == "__main__":
    sys.exit(main())
