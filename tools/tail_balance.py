"""Aggregate balance-relevant metrics from a ``tail_channel`` HTTP
inspector buffer.

Complements the other tail tools:

- ``tail_channel`` — raw follower + inspector host
- ``tail_peek`` — pretty-print the buffer for a human eyeball
- ``tail_watch`` — filtered event stream (errors / complaints / wipes)
- **``tail_balance`` (this)** — roll up the last N hours of play into
  numbers an operator can read: spawn counts, monster outcomes, player
  deaths, hit/miss/crit rates, per-player activity

Exists because "how did balance go since <time>?" is a recurring
question and grepping the buffer by hand is tedious. The summary is
terse, deterministic, and read-only — no state is written anywhere.

Usage::

    python -m tools.tail_balance LIVE                           # last 24 h
    python -m tools.tail_balance LIVE --since-hours 8           # last 8 h
    python -m tools.tail_balance LIVE --after 2026-04-21T00:00:00Z
    python -m tools.tail_balance TEST --json                    # machine-readable
    python -m tools.tail_balance LIVE --port 8999               # port override

The tool polls the inspector once (no subscription) and filters
client-side by timestamp. On an empty or stale buffer it prints a
one-line "no data" summary rather than erroring out.
"""

import argparse
import datetime as dt
import io
import json
import re
import sys
import urllib.request
from collections import Counter
from typing import Dict, List, Optional, Tuple


# Windows default stdout is cp1252 which chokes on "→" (among others
# from the bot's combat tables). Force UTF-8 so the report prints
# cleanly regardless of platform encoding.
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# Monster display names we recognize in the bot's bold-header output.
# New monsters don't NEED to be added here — unrecognized names fall
# into an "other" bucket — but listing the common ones keeps the
# summary readable.
_KNOWN_MONSTERS = {
    "bandit", "bearowl", "cyclops", "doppelganger", "dragon",
    "flying math teacher", "giant", "goblin", "golem", "hydra",
    "elemental hydra", "hexed hydra", "swamp hydra",
    "math teacher", "minotaur", "pixie", "sheep", "skeleton",
    "spirit", "toad", "vampire", "werewolf",
}

# Phrases that signal a monster leaving the fight alive (flees / escapes
# / times out). Keyed on substrings present in the bot's ``escape``
# flavor strings across the monster roster. Not exhaustive — novel
# escape lines fall through.
_ESCAPE_HINTS = (
    "circles the area lazily",
    "vanishes into the night",
    "disappears from sight",
    "trudges off",
    "melts into a pool of shadows",
    "dematerializes",
    "retreats",
    "circles once",
    "melts back into the forest",
    "takes to the skies",
    "fades back into the mist",
    "subsides into a rough standing stone",
    "stomp off",
    "flutters away",
    "vanishing back into the 9th dimension",
    "pencils down",
    "skitters off",
)


def _parse_ts(s: str) -> Optional[dt.datetime]:
    """Parse the ISO timestamps the inspector emits. Returns ``None``
    on malformed input (so one bad message doesn't sink the whole
    report)."""
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _fetch(host: str, port: int) -> List[dict]:
    url = f"http://{host}:{port}/tail"
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.loads(r.read().decode("utf-8"))
    return data.get("messages", []) or []


def _filter_after(
    messages: List[dict], cutoff: Optional[dt.datetime],
) -> List[dict]:
    if cutoff is None:
        return messages
    out = []
    for m in messages:
        ts = _parse_ts(m.get("timestamp", ""))
        if ts is not None and ts >= cutoff:
            out.append(m)
    return out


def _extract_monster_name(content: str) -> Optional[str]:
    """Bot's monster-info block opens with ``**<Monster Name>**`` on
    its own line. Return the lowercased name if we recognize it."""
    for line in content.split("\n"):
        stripped = line.strip()
        if (
            stripped.startswith("**")
            and stripped.endswith("**")
            and stripped.count("**") == 2
        ):
            name = stripped.strip("*").strip().lower()
            # Exclude bot profile cards and other non-monster bold headers.
            if name in _KNOWN_MONSTERS:
                return name
    return None


def _is_escape(content: str) -> bool:
    low = content.lower()
    return any(hint in low for hint in _ESCAPE_HINTS)


def _is_death_narration(content: str) -> bool:
    """Bot death flavor keys on ``crumples to the ground lifelessly``."""
    return "crumples to the ground lifelessly" in content.lower()


def _player_name_from_death_line(line: str) -> Optional[str]:
    """Bot prints ``"<Player Name> crumples to the ground lifelessly!"``."""
    idx = line.lower().find("crumples to the ground")
    if idx <= 0:
        return None
    candidate = line[:idx].strip()
    # Strip possible markdown-mention decorations.
    candidate = candidate.replace("*", "").strip()
    return candidate or None


_HIT_RE = re.compile(r"→\s*HIT")
_MISS_RE = re.compile(r"→\s*MISS")
_CRIT_RE = re.compile(r"→\s*CRIT")
_FUMBLE_RE = re.compile(r"→\s*FUMBLE")


def _summarize(messages: List[dict]) -> dict:
    """Walk the messages once, accumulate the balance rollup."""
    spawns: Counter = Counter()
    escapes: Counter = Counter()
    player_deaths: Counter = Counter()
    player_activity: Counter = Counter()
    hits = 0
    misses = 0
    crits = 0
    fumbles = 0
    current_monster: Optional[str] = None
    total_msgs = len(messages)
    first_ts: Optional[dt.datetime] = None
    last_ts: Optional[dt.datetime] = None

    for m in messages:
        ts = _parse_ts(m.get("timestamp", ""))
        if ts is not None:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        content = m.get("content", "") or ""
        author = m.get("author", "") or ""
        low_author = author.lower()
        is_bot = "caldanai bot" in low_author

        name = _extract_monster_name(content)
        if name is not None:
            spawns[name] += 1
            current_monster = name

        if is_bot and _is_escape(content) and current_monster is not None:
            escapes[current_monster] += 1
            current_monster = None

        if is_bot and _is_death_narration(content):
            for line in content.split("\n"):
                pn = _player_name_from_death_line(line)
                if pn:
                    player_deaths[pn] += 1

        hits += len(_HIT_RE.findall(content))
        misses += len(_MISS_RE.findall(content))
        crits += len(_CRIT_RE.findall(content))
        fumbles += len(_FUMBLE_RE.findall(content))

        if author and not is_bot:
            player_activity[author.lstrip("@")] += 1

    total_rolls = hits + misses + crits + fumbles
    return {
        "window": {
            "first_ts": first_ts.isoformat() if first_ts else None,
            "last_ts": last_ts.isoformat() if last_ts else None,
            "message_count": total_msgs,
        },
        "spawns": dict(spawns.most_common()),
        "escapes": dict(escapes.most_common()),
        "player_deaths": dict(player_deaths.most_common()),
        "player_activity": dict(player_activity.most_common(10)),
        "rolls": {
            "hit": hits,
            "miss": misses,
            "crit": crits,
            "fumble": fumbles,
            "total": total_rolls,
            "hit_rate": (
                round((hits + crits) / total_rolls, 3)
                if total_rolls else None
            ),
            "crit_rate": (
                round(crits / total_rolls, 3)
                if total_rolls else None
            ),
        },
    }


def _format_report(summary: dict) -> str:
    """Render the summary as a compact human-readable block."""
    w = summary["window"]
    if w["message_count"] == 0 or not w["first_ts"]:
        return "# Tail balance — no messages in window."

    lines: List[str] = []
    lines.append("# Tail balance")
    lines.append(
        f"Window: {w['first_ts']} -> {w['last_ts']} "
        f"({w['message_count']} messages)"
    )
    lines.append("")
    if summary["spawns"]:
        lines.append("## Monster spawns")
        for name, count in summary["spawns"].items():
            escapes = summary["escapes"].get(name, 0)
            tag = f" ({escapes} escaped)" if escapes else ""
            lines.append(f"  - {name}: {count}{tag}")
        lines.append("")
    else:
        lines.append("## Monster spawns: none")
        lines.append("")

    if summary["player_deaths"]:
        lines.append("## Player deaths")
        for name, count in summary["player_deaths"].items():
            lines.append(f"  - {name}: {count}")
        lines.append("")
    else:
        lines.append("## Player deaths: none")
        lines.append("")

    r = summary["rolls"]
    lines.append("## Combat rolls")
    if r["total"]:
        lines.append(
            f"  hit: {r['hit']}  crit: {r['crit']}  miss: {r['miss']}  "
            f"fumble: {r['fumble']}  (total {r['total']})"
        )
        lines.append(
            f"  hit-including-crit rate: {r['hit_rate']:.0%}  "
            f"crit rate: {r['crit_rate']:.1%}"
        )
    else:
        lines.append("  (no attack rolls in window)")
    lines.append("")

    if summary["player_activity"]:
        lines.append("## Most-active players (top 10 by message count)")
        for name, count in summary["player_activity"].items():
            lines.append(f"  - {name}: {count}")
    return "\n".join(lines)


def _compute_cutoff(
    after: Optional[str], since_hours: Optional[float],
) -> Optional[dt.datetime]:
    if after:
        parsed = _parse_ts(after)
        if parsed is None:
            print(f"bad --after: {after!r}", file=sys.stderr)
            sys.exit(2)
        return parsed
    if since_hours is not None:
        now = dt.datetime.now(dt.timezone.utc)
        return now - dt.timedelta(hours=since_hours)
    return None


def main(argv: Optional[List[str]] = None) -> int:
    from tools._common import TAIL_ENVS, resolve_tail_env

    ap = argparse.ArgumentParser(
        usage="python -m tools.tail_balance {LIVE|TEST} [options]",
        description=(
            "Roll up balance metrics (spawns, deaths, hit/miss/crit "
            "rates, per-player activity) from a tail_channel "
            "inspector. The FIRST ARGUMENT picks which env to "
            "aggregate: LIVE (port 8765) or TEST (port 8766)."
        ),
        epilog=(
            "Examples:\n"
            "  python -m tools.tail_balance LIVE\n"
            "  python -m tools.tail_balance LIVE --since-hours 8\n"
            "  python -m tools.tail_balance TEST --after 2026-04-21T00:00:00Z\n"
            "  python -m tools.tail_balance LIVE --json\n"
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
        help="Inspector port override. Default derived from ``env``.",
    )
    group = ap.add_mutually_exclusive_group()
    group.add_argument(
        "--since-hours", type=float, default=24,
        help="Only count messages from the last N hours (default 24).",
    )
    group.add_argument(
        "--after", default=None,
        help="Only count messages on/after this ISO timestamp "
             "(e.g. 2026-04-21T00:00:00Z).",
    )
    ap.add_argument(
        "--json", action="store_true",
        help="Emit the structured summary as JSON instead of the "
             "rendered report.",
    )
    args = ap.parse_args(argv)

    _, default_port = resolve_tail_env(args.env)
    port = args.port if args.port is not None else default_port

    cutoff = _compute_cutoff(args.after, args.since_hours)
    try:
        messages = _fetch(args.host, port)
    except Exception as e:
        print(
            f"fetch error: {e}\n"
            f"(Is ``python -m tools.tail_channel {args.env} --follow`` "
            f"running on port {port}?)",
            file=sys.stderr,
        )
        return 1

    filtered = _filter_after(messages, cutoff)
    summary = _summarize(filtered)
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(_format_report(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
