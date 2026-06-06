"""Print the current wall-clock time as an ISO-8601 UTC timestamp.

Exists so the bg-Vael synthesis cron (and any other unattended
``tools/``-allowlisted automation) can stamp the REAL current time
instead of inferring "now" from the latest entry in the hourly digest.

The synthesis cron has no clock during an unattended fire, so it used
to derive "now" from the freshest ``## <iso>`` section in
``_vael_digest.md``. When the digest collector lags or stalls — e.g.
bg Vael stuck on a permission prompt for hours — that inference
silently back-dates the synthesis window (a real 6h gap got stamped as
2.5h on 2026-06-04 when the collector had been frozen ~9h). A real
clock read makes the staleness obvious instead of invisible.

Covered by the existing ``Bash(python -m tools.*)`` permission
allowlist, so it runs without a fresh permission prompt mid-cron — the
whole reason this is a tool and not an inline ``Get-Date`` shell-out.

Modes:

- ``python -m tools.now``                 → ``2026-06-05T01:20:00+00:00``
- ``python -m tools.now --since <iso>``   → adds ``elapsed_hours`` since
  a prior timestamp (use the digest's latest section header to detect a
  stalled collector).
- ``python -m tools.now --expiry <iso>``  → adds ``remaining_hours`` and
  a ``status`` flag (OK / EXPIRES_SOON / EXPIRED) for the cron's 7-day
  auto-expiry, so a fire near rollover can warn before the job silently
  drops.
"""

import argparse
from datetime import datetime, timedelta, timezone

_ISO = "%Y-%m-%dT%H:%M:%S+00:00"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(_ISO)


def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 string to an aware UTC datetime.

    Accepts a trailing ``Z`` and naive timestamps (assumed UTC) so the
    digest's bare ``## 2026-06-04T16:02:35`` headers parse without
    massaging.
    """
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.now",
        description="Print the current UTC time as an ISO-8601 timestamp.",
    )
    parser.add_argument(
        "--since",
        metavar="ISO",
        help="Report hours elapsed since this timestamp (collector-staleness check).",
    )
    parser.add_argument(
        "--expiry",
        metavar="ISO",
        help="Report hours until this timestamp + a status flag (cron 7-day expiry check).",
    )
    parser.add_argument(
        "--warn-hours",
        type=float,
        default=24.0,
        help="EXPIRES_SOON threshold for --expiry, in hours (default: 24).",
    )
    args = parser.parse_args(argv)

    now = utc_now()
    print(fmt(now))

    if args.since:
        elapsed = (now - _parse_iso(args.since)).total_seconds() / 3600.0
        print(f"since={_parse_iso(args.since).strftime(_ISO)} elapsed_hours={elapsed:.2f}")

    if args.expiry:
        expiry = _parse_iso(args.expiry)
        remaining = (expiry - now).total_seconds() / 3600.0
        if remaining <= 0:
            status = "EXPIRED"
        elif remaining <= args.warn_hours:
            status = "EXPIRES_SOON"
        else:
            status = "OK"
        print(f"expiry={expiry.strftime(_ISO)} remaining_hours={remaining:.2f} status={status}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
