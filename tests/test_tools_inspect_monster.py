"""Smoke tests for ``tools/inspect_monster``."""

import pytest

from tools.inspect_monster import inspect, main


class TestInspectMonster:
    def test_known_monster_renders_stats(self):
        out = inspect("goblin")
        assert "GOBLIN" in out
        assert "body_hp=" in out
        assert "bleed_rate=" in out
        assert "defense_bonus=" in out

    def test_defense_and_dodge_show_raw_arrow_effective(self):
        """``raw->effective`` arrow makes size-mod and emergence
        aggregation visible at a glance."""
        out = inspect("bearowl")
        # Header line carries both ``defense=N->M`` and ``dodge=N->M``.
        assert "defense=" in out
        assert "dodge=" in out
        # The arrow is the explicit "raw vs effective" signal.
        # At least two ``->`` arrows on the bearowl header line
        # (one for defense, one for dodge).
        header = out.split("\n", 2)[1]
        assert header.count("->") >= 2, (
            f"expected raw->effective arrows in header: {header!r}"
        )

    def test_defense_surfaces_torso_effective(self):
        """Header surfaces ``(torso N)`` alongside ``raw->effective``
        so the operator-side number matches what $look shows on the
        spawn embed (post 2026-04-28 contract). Bearowl has torso
        defense_bonus=+3, so torso-effective should differ from the
        bare creature pool."""
        out = inspect("bearowl")
        header = out.split("\n", 2)[1]
        assert "(torso " in header, (
            f"expected '(torso N)' suffix on bearowl header: {header!r}"
        )

    def test_bodyless_creature_omits_torso_suffix(self):
        """Spirit has no body parts -> no torso anchor -> the
        ``(torso N)`` suffix is omitted gracefully."""
        out = inspect("spirit")
        header = out.split("\n", 2)[1]
        assert "(torso" not in header, (
            f"spirit has no body; should omit (torso ...) suffix: "
            f"{header!r}"
        )

    def test_unknown_monster_returns_message(self):
        out = inspect("not_a_real_stem_xyz")
        assert "unknown monster" in out

    def test_main_exits_zero_on_success(self, capsys):
        ret = main(["goblin"])
        assert ret == 0
        captured = capsys.readouterr()
        assert "GOBLIN" in captured.out

    def test_main_accepts_multiple_stems(self, capsys):
        ret = main(["goblin", "bandit"])
        assert ret == 0
        out = capsys.readouterr().out
        assert "GOBLIN" in out
        assert "BANDIT" in out
