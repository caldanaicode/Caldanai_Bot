"""Smoke tests for ``tools/chart_combat_balance.py``.

The interesting orchestrations to lock in:

- Monster enumeration finds the bestiary (>5 plugins).
- ``build_figure`` returns a usable matplotlib Figure for both
  populated and empty-data cases (so a transient enumeration
  failure can't crash the dry-run path).
- ``build_survivability_figure`` and ``build_parallel_figure``
  do the same — every view has empty-safe + populated coverage.
- The dry-run path writes a non-empty PNG to disk for each view.
- ``--view {scatter,survivability,parallel}`` dispatches the
  right renderer and writes its own default-named output file.
- HP marker scaling spreads the low-HP cluster after the sqrt
  rework (toad-vs-spirit no longer collapse).

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

    def test_sqrt_scaling_spreads_low_end(self):
        # Toad (18) and spirit (33) used to collapse at the
        # bottom when a hydra (300) dominated the upper end.
        # Sqrt scaling should leave them visibly different —
        # specifically, the spirit marker should be at least
        # 2x the *delta-from-floor* the toad gets.
        all_hps = [18.0, 33.0, 80.0, 200.0, 300.0]
        toad = ccb._hp_to_marker_area(18.0, all_hps)
        spirit = ccb._hp_to_marker_area(33.0, all_hps)
        dragon = ccb._hp_to_marker_area(200.0, all_hps)
        hydra = ccb._hp_to_marker_area(300.0, all_hps)
        # Floor still anchored at the smallest value.
        assert toad == pytest.approx(80.0)
        # Spread test: spirit needs to be visibly bigger than
        # toad — with linear scaling the gap is ~21 points^2,
        # easily lost; sqrt should give at least ~110.
        assert (spirit - toad) > 80.0, (
            f"sqrt scaling should spread 18 vs 33 HP visibly, "
            f"got spirit={spirit:.1f} toad={toad:.1f}"
        )
        # Monotonic across the full range.
        assert toad < spirit < dragon < hydra
        # Ceiling still holds at the top.
        assert hydra == pytest.approx(800.0)


class TestSurvivabilityHelpers:
    def test_miss_rate_clamped(self):
        # 1d20 against dodge 0 -> never misses (rate 0).
        assert ccb._miss_rate(0.0) == pytest.approx(0.0)
        # Normal dodge in the bestiary (~6) -> 30%.
        assert ccb._miss_rate(6.0) == pytest.approx(0.3)
        # Sky-high dodge cap at 95% so 1/(1-rate) doesn't blow up.
        assert ccb._miss_rate(40.0) == pytest.approx(0.95)

    def test_damage_reduction_clamped(self):
        # No defense -> no reduction.
        assert ccb._damage_reduction(0.0, 8.0) == pytest.approx(0.0)
        # Defense matching avg raw damage -> 100% reduction
        # would divide by zero; clamp at 0.95.
        assert ccb._damage_reduction(20.0, 8.0) == pytest.approx(0.95)

    def test_effective_hp_increases_with_dodge_and_defense(self):
        baseline = ccb._effective_hp(20.0, 0.0, 0.0)
        dodgy = ccb._effective_hp(20.0, 10.0, 0.0)
        tanky = ccb._effective_hp(20.0, 0.0, 4.0)
        assert dodgy > baseline
        assert tanky > baseline


class TestBuildSurvivabilityFigure:
    def test_empty_samples_produces_figure(self):
        fig = ccb.build_survivability_figure([])
        try:
            assert fig is not None
            assert hasattr(fig, "savefig")
        finally:
            plt.close(fig)

    def test_populated_samples_produces_figure(self):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0,
             "attack": 3.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0,
             "attack": 12.0},
            {"label": "player", "size": Size.MEDIUM,
             "dodge": 6.0, "defense": 6.0, "hp": 20.0,
             "attack": 8.0, "is_player": True},
        ]
        fig = ccb.build_survivability_figure(fake_samples)
        try:
            assert fig is not None
            assert fig.axes
            assert fig.axes[0].get_title()
        finally:
            plt.close(fig)

    def test_writes_non_empty_png(self, tmp_path: Path):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0,
             "attack": 3.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0,
             "attack": 12.0},
        ]
        fig = ccb.build_survivability_figure(fake_samples)
        out = tmp_path / "surv.png"
        ccb.save_figure_to_path(fig, out)
        assert out.is_file()
        assert out.read_bytes()[:8].startswith(b"\x89PNG\r\n\x1a\n")
        assert out.stat().st_size > 1000


class TestBuildParallelFigure:
    def test_empty_samples_produces_figure(self):
        fig = ccb.build_parallel_figure([])
        try:
            assert fig is not None
            assert hasattr(fig, "savefig")
        finally:
            plt.close(fig)

    def test_populated_samples_produces_figure(self):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0,
             "attack": 3.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0,
             "attack": 12.0},
            {"label": "claire", "size": Size.MEDIUM,
             "dodge": 5.0, "defense": 5.0, "hp": 40.0,
             "attack": 6.0},
        ]
        fig = ccb.build_parallel_figure(fake_samples)
        try:
            assert fig is not None
            assert fig.axes
            ax = fig.axes[0]
            # Five axes positions on the X axis (dodge / defense /
            # HP / attack / size).
            assert len(ax.get_xticks()) == len(ccb._PARALLEL_AXES)
        finally:
            plt.close(fig)

    def test_writes_non_empty_png(self, tmp_path: Path):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0,
             "attack": 3.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0,
             "attack": 12.0},
        ]
        fig = ccb.build_parallel_figure(fake_samples)
        out = tmp_path / "par.png"
        ccb.save_figure_to_path(fig, out)
        assert out.is_file()
        assert out.read_bytes()[:8].startswith(b"\x89PNG\r\n\x1a\n")
        assert out.stat().st_size > 1000


class TestNormalizeAxis:
    def test_min_zero_max_one(self):
        out = ccb._normalize_axis([10.0, 20.0, 30.0])
        assert out[0] == pytest.approx(0.0)
        assert out[-1] == pytest.approx(1.0)

    def test_degenerate_collapses_to_midpoint(self):
        # All-equal values would produce NaN with naive
        # (v-lo)/(hi-lo); helper collapses to 0.5 instead so the
        # line still draws inside the [0,1] axis.
        out = ccb._normalize_axis([7.0, 7.0, 7.0])
        assert all(v == pytest.approx(0.5) for v in out)


class TestBuildView:
    def test_dispatches_each_view(self):
        fake_samples = [
            {"label": "alice", "size": Size.SMALL,
             "dodge": 8.0, "defense": 4.0, "hp": 12.0,
             "attack": 3.0},
            {"label": "bob", "size": Size.HUGE,
             "dodge": 3.0, "defense": 10.0, "hp": 80.0,
             "attack": 12.0},
        ]
        for view in ("scatter", "survivability", "parallel"):
            fig = ccb.build_view(view, fake_samples)
            try:
                assert fig is not None
                assert fig.axes
            finally:
                plt.close(fig)

    def test_unknown_view_raises(self):
        with pytest.raises(ValueError):
            ccb.build_view("bogus", [])


class TestMainViewDispatch:
    def test_main_survivability_view(self, tmp_path: Path):
        out = tmp_path / "surv.png"
        ret = ccb.main([
            "--view", "survivability",
            "--output", str(out),
            "--no-player", "--trials", "2",
        ])
        assert ret == 0
        assert out.is_file()
        assert out.stat().st_size > 1000

    def test_main_parallel_view(self, tmp_path: Path):
        out = tmp_path / "par.png"
        ret = ccb.main([
            "--view", "parallel",
            "--output", str(out),
            "--no-player", "--trials", "2",
        ])
        assert ret == 0
        assert out.is_file()
        assert out.stat().st_size > 1000

    def test_main_default_output_per_view(
        self, tmp_path: Path, monkeypatch,
    ):
        # Without --output, default name should embed the view id
        # so a survivability run doesn't overwrite a scatter run
        # already on disk.
        monkeypatch.chdir(tmp_path)
        ret = ccb.main([
            "--view", "survivability",
            "--no-player", "--trials", "2",
        ])
        assert ret == 0
        expected = tmp_path / "balance-chart-survivability.png"
        assert expected.is_file(), (
            f"expected default output {expected} to exist; "
            f"contents: {list(tmp_path.iterdir())}"
        )
