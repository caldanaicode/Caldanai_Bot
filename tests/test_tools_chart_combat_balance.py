"""Smoke tests for ``tools/chart_combat_balance.py``.

The interesting orchestrations to lock in:

- Monster enumeration finds the bestiary (>5 plugins).
- ``build_figure`` returns a usable matplotlib Figure for both
  populated and empty-data cases (so a transient enumeration
  failure can't crash the dry-run path).
- The dry-run path writes a non-empty PNG to disk.
- ``main(["--no-player"])`` runs end-to-end without raising.

Discord upload is intentionally NOT exercised here — the
upload path requires ``discord.py`` connecting to a live
gateway and a valid bot token. The ``--post`` path is small
enough (resolve channel, resolve token, call discord.Client)
that integration testing is the appropriate level."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless backend for the test runner
import matplotlib.pyplot as plt
import pytest

from caldanai.lib.rpg.helpers.enums import Size
from tools import chart_combat_balance as ccb


class TestEnumerateMonsterClasses:
    def test_finds_more_than_five_monsters(self):
        classes = ccb._enumerate_monster_classes()
        # The bestiary today has ~15-20 plugins; >5 is a generous
        # lower bound that catches "registry never populated".
        assert len(classes) > 5, (
            f"expected >5 monster plugin classes, got {len(classes)}"
        )

    def test_classes_are_unique(self):
        classes = ccb._enumerate_monster_classes()
        assert len(classes) == len(set(classes)), (
            "expected each plugin class to appear once after "
            "alias dedup"
        )


class TestSampleMonsterStats:
    def test_known_monster_returns_sample(self):
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin

        MonsterPlugin.load_plugins()
        cls = MonsterPlugin.get_plugin_class("goblin")
        assert cls is not None
        sample = ccb._sample_monster_stats(cls, trials=3)
        assert sample is not None
        assert isinstance(sample["size"], Size)
        assert sample["dodge"] >= 0
        assert sample["defense"] >= 0
        assert sample["hp"] > 0
        assert sample["label"]


class TestCollectSamples:
    def test_collects_monsters_and_player(self):
        samples = ccb.collect_samples(trials=2, include_player=True)
        assert len(samples) > 5
        assert any(s.get("is_player") for s in samples), (
            "expected a player baseline when include_player=True"
        )

    def test_no_player_excludes_baseline(self):
        samples = ccb.collect_samples(trials=2, include_player=False)
        assert all(not s.get("is_player") for s in samples)


class TestBuildFigure:
    def test_empty_samples_produces_figure(self):
        fig = ccb.build_figure([])
        try:
            assert fig is not None
            assert hasattr(fig, "savefig")
        finally:
            plt.close(fig)

    def test_populated_samples_produces_figure(self):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0},
            {"label": "player", "size": Size.MEDIUM,
             "dodge": 6.0, "defense": 6.0, "hp": 20.0,
             "is_player": True},
        ]
        fig = ccb.build_figure(fake_samples)
        try:
            assert fig is not None
            # At least one Axes attached, with a non-empty title.
            assert fig.axes
            ax = fig.axes[0]
            assert ax.get_title()
        finally:
            plt.close(fig)


class TestSaveFigureToPath:
    def test_writes_non_empty_png(self, tmp_path: Path):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0},
        ]
        fig = ccb.build_figure(fake_samples)
        out = tmp_path / "subdir" / "balance.png"
        ccb.save_figure_to_path(fig, out)
        assert out.is_file()
        # PNG signature in the first eight bytes — guards against
        # a backend silently writing an empty buffer.
        head = out.read_bytes()[:8]
        assert head.startswith(b"\x89PNG\r\n\x1a\n"), (
            f"expected PNG signature, got {head!r}"
        )
        assert out.stat().st_size > 1000, (
            f"PNG looks too small ({out.stat().st_size} bytes) "
            f"to actually contain the chart"
        )


class TestMainDryRun:
    def test_main_dry_run_writes_png(self, tmp_path: Path):
        out = tmp_path / "balance.png"
        ret = ccb.main(["--output", str(out), "--no-player", "--trials", "2"])
        assert ret == 0
        assert out.is_file()
        assert out.stat().st_size > 1000

    def test_main_dry_run_with_player_baseline(self, tmp_path: Path):
        out = tmp_path / "balance.png"
        ret = ccb.main(["--output", str(out), "--trials", "2"])
        assert ret == 0
        assert out.is_file()


class TestHpToMarkerArea:
    def test_min_hp_gets_min_area(self):
        all_hps = [10.0, 50.0, 100.0]
        area = ccb._hp_to_marker_area(10.0, all_hps)
        assert area == pytest.approx(80.0)

    def test_max_hp_gets_max_area(self):
        all_hps = [10.0, 50.0, 100.0]
        area = ccb._hp_to_marker_area(100.0, all_hps)
        assert area == pytest.approx(800.0)

    def test_degenerate_single_value(self):
        # All same HP -> caller still gets a non-zero, mid-ish area.
        area = ccb._hp_to_marker_area(50.0, [50.0, 50.0])
        assert area > 0
