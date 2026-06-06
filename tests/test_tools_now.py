"""Tests for ``tools.now`` — the unattended-clock helper for the
synthesis cron. Pins the output shapes the cron's prompt parses:
bare timestamp, ``--since`` staleness, and ``--expiry`` status flags.
"""

import re
from datetime import datetime, timedelta, timezone

import pytest

from tools import now as now_mod


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+00:00$")


def test_bare_prints_one_iso_utc_line(capsys):
    rc = now_mod.main([])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert _ISO_RE.match(out[0])


def test_parse_iso_accepts_naive_z_and_offset():
    # Bare digest header (naive) is treated as UTC.
    assert now_mod._parse_iso("2026-06-04T16:02:35").tzinfo == timezone.utc
    # Z and explicit offset both normalize to UTC.
    a = now_mod._parse_iso("2026-06-04T16:02:35Z")
    b = now_mod._parse_iso("2026-06-04T16:02:35+00:00")
    assert a == b


def test_since_reports_positive_elapsed(capsys):
    past = now_mod.fmt(now_mod.utc_now() - timedelta(hours=9))
    now_mod.main(["--since", past])
    out = capsys.readouterr().out
    m = re.search(r"elapsed_hours=([\d.]+)", out)
    assert m
    # ~9h ago — allow slack for clock drift during the test.
    assert 8.9 < float(m.group(1)) < 9.2


def test_expiry_ok_when_far(capsys):
    future = now_mod.fmt(now_mod.utc_now() + timedelta(days=6))
    now_mod.main(["--expiry", future])
    assert "status=OK" in capsys.readouterr().out


def test_expiry_warns_within_window(capsys):
    soon = now_mod.fmt(now_mod.utc_now() + timedelta(hours=12))
    now_mod.main(["--expiry", soon])
    assert "status=EXPIRES_SOON" in capsys.readouterr().out


def test_expiry_flags_past_as_expired(capsys):
    gone = now_mod.fmt(now_mod.utc_now() - timedelta(hours=1))
    now_mod.main(["--expiry", gone])
    assert "status=EXPIRED" in capsys.readouterr().out


def test_warn_hours_threshold_is_configurable(capsys):
    # 12h out is OK under a 6h warn window, EXPIRES_SOON under 24h.
    soon = now_mod.fmt(now_mod.utc_now() + timedelta(hours=12))
    now_mod.main(["--expiry", soon, "--warn-hours", "6"])
    assert "status=OK" in capsys.readouterr().out
