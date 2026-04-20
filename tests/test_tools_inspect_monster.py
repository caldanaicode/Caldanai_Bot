"""Smoke tests for ``tools/inspect_monster``."""

import pytest

from tools.inspect_monster import inspect, main


class TestInspectMonster:
    def test_known_monster_renders_stats(self):
        out = inspect("goblin")
        assert "GOBLIN" in out
        assert "body_hp=" in out
        assert "bleed_rate=" in out
        assert "defense_mod=" in out

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
