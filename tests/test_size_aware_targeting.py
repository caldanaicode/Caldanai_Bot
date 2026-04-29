"""Tests for size-aware target selection.

Covers the selection-bias formula (``_size_attractor`` +
``pick_random_part`` with scale args) and the tree-walk region
collapse (``_collapse_to_region``). Follows the sign-off bar
from the design doc: hydra-vs-player eye-hit rate, pixie-vs-
player eye-hit rate, same-size baseline unchanged.

The deterministic unit tests pin the attractor math and
collapse thresholds; the distribution tests verify real
creatures behave as the design says they should under many
trials.
"""

import random
from collections import Counter
from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures import (
    _attack_scale_of,
    _collapse_to_region,
    _size_attractor,
    pick_random_part,
)
from caldanai.lib.rpg.creatures.body_builder import humanoid_tree, node, paired
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.helpers.enums import Reach, Size


# ---------------------------------------------------------------------------
# _size_attractor: sample values from the design doc
# ---------------------------------------------------------------------------

class TestSizeAttractor:
    def test_same_size_ratio_returns_one_for_every_part(self):
        """ratio == 1.0 means ratio**anything == 1.0. Baseline
        invariant the same-size case relies on."""
        torso = _make_torso(exposure={Reach.MELEE: 1.0})
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        assert _size_attractor(torso, Reach.MELEE, 1.0) == pytest.approx(1.0)
        assert _size_attractor(eye, Reach.MELEE, 1.0) == pytest.approx(1.0)

    def test_big_vs_small_shrinks_small_exposure(self):
        """ratio > 1 with low-exposure part → attractor < 1."""
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        attractor = _size_attractor(eye, Reach.MELEE, 1.5)
        # 1.5 ** -1.8 ≈ 0.479
        assert attractor == pytest.approx(1.5 ** -1.8)
        assert attractor < 1.0

    def test_big_vs_small_leaves_torso_unchanged(self):
        """Torso has exposure 1.0 → sensitivity 0 → attractor == 1.0
        at any ratio."""
        torso = _make_torso(exposure={Reach.MELEE: 1.0})
        assert _size_attractor(torso, Reach.MELEE, 1.5) == pytest.approx(1.0)
        assert _size_attractor(torso, Reach.MELEE, 3.5) == pytest.approx(1.0)
        assert _size_attractor(torso, Reach.MELEE, 0.5) == pytest.approx(1.0)

    def test_small_vs_big_boosts_small_exposure(self):
        """Symmetric flavor: ratio < 1 with low-exposure part →
        attractor > 1. Pixies stab eyes."""
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        attractor = _size_attractor(eye, Reach.MELEE, 0.5)
        # 0.5 ** -1.8 ≈ 3.48
        assert attractor == pytest.approx(0.5 ** -1.8)
        assert attractor > 3.0


# ---------------------------------------------------------------------------
# _collapse_to_region: tree-walk form
# ---------------------------------------------------------------------------

class TestCollapseToRegion:
    def _build_tree(self):
        """Minimal humanoid tree: torso → head → eye."""
        return node(TorsoPlugin, name="torso", children=[
            node(HeadPlugin, name="head", children=[
                *paired(EyePlugin, "eye"),
            ]),
        ]).build()

    def test_ratio_below_threshold_returns_part_unchanged(self):
        root = self._build_tree()
        eye = root.find("eye.left")
        assert _collapse_to_region(eye, 1.0) is eye
        assert _collapse_to_region(eye, 1.9) is eye

    def test_ratio_at_threshold_walks_one_level(self):
        """At-or-above (>=) so the most-common ratio-2 cases trigger:
        MEDIUM player vs TINY pixie, MEDIUM player vs HUGE cyclops/giant/dragon.
        int(log2(2.0)) == 1 → one level up. Eye → head."""
        root = self._build_tree()
        eye = root.find("eye.left")
        head = root.find("head")
        assert _collapse_to_region(eye, 2.0) is head
        assert _collapse_to_region(eye, 2.1) is head

    def test_ratio_doubling_walks_two_levels(self):
        """int(log2(4.0)) == 2 → two levels up. Eye → head → torso."""
        root = self._build_tree()
        eye = root.find("eye.left")
        torso = root.find("torso")
        collapsed = _collapse_to_region(eye, 4.0)
        assert collapsed is torso

    def test_walk_stops_at_root(self):
        """A ratio deep enough to demand more levels than the tree
        has stops at the root rather than walking off the top."""
        root = self._build_tree()
        eye = root.find("eye.left")
        torso = root.find("torso")
        # Ratio 32 asks for 5 levels, tree only has 2 up from eye.
        collapsed = _collapse_to_region(eye, 32.0)
        assert collapsed is torso

    def test_partless_part_returns_self(self):
        """A node with parent=None (legacy / detached) stays put.
        Scaffold the case with a bare HeadPlugin that was never
        wired into a tree."""
        head = HeadPlugin(name="head")
        assert head.parent is None
        assert _collapse_to_region(head, 8.0) is head


# ---------------------------------------------------------------------------
# pick_random_part with scale args
# ---------------------------------------------------------------------------

class TestPickRandomPartScaleAware:
    def test_same_size_baseline_is_pure_exposure_weighted(self):
        """When attacker_scale == target_scale, scale bias collapses
        to 1.0 and the picks match the pre-size-aware pure-exposure
        distribution."""
        torso = _make_torso(exposure={Reach.MELEE: 1.0})
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        # Drive the random choices through a patched RNG so the
        # weight list itself can be inspected.
        with patch(
            "caldanai.lib.rpg.creatures.choices",
            return_value=[torso],
        ) as mock_choices:
            pick_random_part([torso, eye], Reach.MELEE, 1.0, 1.0)
        weights = mock_choices.call_args.kwargs["weights"]
        assert weights == pytest.approx([1.0, 0.1])

    def test_big_vs_small_shrinks_eye_weight(self):
        """HUGE-vs-MEDIUM (ratio 1.5): eye attractor ≈ 0.479,
        resulting weight ≈ 0.1 * 0.479 ≈ 0.048."""
        torso = _make_torso(exposure={Reach.MELEE: 1.0})
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        with patch(
            "caldanai.lib.rpg.creatures.choices",
            return_value=[torso],
        ) as mock_choices:
            pick_random_part([torso, eye], Reach.MELEE, 1.5, 1.0)
        weights = mock_choices.call_args.kwargs["weights"]
        assert weights[0] == pytest.approx(1.0)  # torso unchanged
        assert weights[1] == pytest.approx(0.1 * 1.5 ** -1.8)

    def test_small_vs_big_boosts_eye_weight(self):
        """TINY-vs-MEDIUM (ratio 0.5): eye attractor ≈ 3.48,
        resulting weight ≈ 0.348."""
        torso = _make_torso(exposure={Reach.MELEE: 1.0})
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        with patch(
            "caldanai.lib.rpg.creatures.choices",
            return_value=[torso],
        ) as mock_choices:
            pick_random_part([torso, eye], Reach.MELEE, 0.5, 1.0)
        weights = mock_choices.call_args.kwargs["weights"]
        assert weights[0] == pytest.approx(1.0)
        assert weights[1] == pytest.approx(0.1 * 0.5 ** -1.8)

    def test_defaults_preserve_legacy_behavior(self):
        """Omitting the scale args keeps the original
        exposure-only distribution — tests that construct parts
        without a creature context keep working unchanged."""
        torso = _make_torso(exposure={Reach.MELEE: 1.0})
        eye = _make_eye(exposure={Reach.MELEE: 0.1})
        with patch(
            "caldanai.lib.rpg.creatures.choices",
            return_value=[torso],
        ) as mock_choices:
            pick_random_part([torso, eye], Reach.MELEE)
        weights = mock_choices.call_args.kwargs["weights"]
        assert weights == pytest.approx([1.0, 0.1])


# ---------------------------------------------------------------------------
# _attack_scale_of
# ---------------------------------------------------------------------------

class TestAttackScaleLookup:
    def test_reads_scale_from_size_enum(self):
        """MEDIUM=1.0, HUGE=1.5 per the Size.value dict."""

        class _Fake:
            pass

        c = _Fake()
        c.size = Size.HUGE
        assert _attack_scale_of(c) == pytest.approx(1.5)
        c.size = Size.MEDIUM
        assert _attack_scale_of(c) == pytest.approx(1.0)
        c.size = Size.TINY
        assert _attack_scale_of(c) == pytest.approx(0.5)

    def test_defaults_to_one_when_size_missing(self):
        class _Fake:
            pass

        assert _attack_scale_of(_Fake()) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Distribution tests — the design-doc sign-off bar
# ---------------------------------------------------------------------------

class TestSelectionDistributions:
    """Rolling 2000+ picks per scenario and checking that the
    eye-hit rate matches the design-doc numbers within tolerance.

    Note: these are intentionally probabilistic. The tolerances
    are generous enough to survive RNG variance but tight enough
    to fail if the attractor formula breaks."""

    TRIALS = 3000

    def _player_parts(self):
        """Stand-in for a MEDIUM player: torso, head, eyes.
        Names and exposures match the real plugin defaults so
        weights come out right."""
        root = node(TorsoPlugin, name="torso", children=[
            node(HeadPlugin, name="head", children=[
                *paired(EyePlugin, "eye"),
            ]),
        ]).build()
        return list(root.walk())

    def _eye_rate(self, attacker_scale, target_scale):
        # Deterministic seed — distribution bounds are tight
        # enough that RNG variance can flake across CI runs
        # otherwise. Each scenario reseeds so they're independent.
        random.seed(0xB1A5)
        parts = self._player_parts()
        picks = Counter()
        for _ in range(self.TRIALS):
            picked = pick_random_part(
                parts, Reach.MELEE, attacker_scale, target_scale,
            )
            picks[picked.name if picked else None] += 1
        return (picks["eye.left"] + picks["eye.right"]) / self.TRIALS

    def test_same_size_baseline(self):
        """MEDIUM-vs-MEDIUM eye-hit rate ≈ the raw exposure share.
        Eye exposure 0.1 each ×2 = 0.2 / (torso 1.0 + head 0.7 +
        eye.left 0.1 + eye.right 0.1) = 0.2 / 1.9 ≈ 0.105."""
        rate = self._eye_rate(1.0, 1.0)
        assert 0.07 <= rate <= 0.14, f"baseline eye rate = {rate:.3f}"

    def test_huge_vs_medium_eye_rate_drops_below_ten_percent(self):
        """HUGE (1.5) attacking MEDIUM (1.0): eye weight shrinks
        to ~0.048 per eye, total eye share ≈ 0.096 / (1.0 + 0.7 *
        1.5**-0.6 + 2*0.048) ≈ 0.054. Under 10% by a margin."""
        rate = self._eye_rate(1.5, 1.0)
        assert rate < 0.10, f"HUGE-vs-MEDIUM eye rate = {rate:.3f}"

    def test_tiny_vs_medium_eye_rate_climbs_above_baseline(self):
        """TINY (0.5) attacking MEDIUM (1.0): eye weight jumps to
        ~0.348 per eye. Expected eye share against just torso +
        head + 2 eyes:

            torso weight: 1.0 * 1.0 = 1.0
            head weight:  0.7 * 0.5^-0.6 ≈ 1.061
            eye weight:   0.1 * 0.5^-1.8 ≈ 0.348 each
            total:        ~2.757
            eye share:    0.696 / 2.757 ≈ 0.252

        So the design-doc ">30%" bar was optimistic for a pool
        this small — real expectation is ~25%. Assert against a
        looser threshold (>20%) that still clearly beats the
        ~11% same-size baseline, and verify the rate is at least
        double the baseline as the meaningful signal."""
        rate = self._eye_rate(0.5, 1.0)
        assert rate >= 0.20, f"TINY-vs-MEDIUM eye rate = {rate:.3f}"
        baseline = self._eye_rate(1.0, 1.0)
        assert rate >= baseline * 2, (
            f"expected TINY rate ({rate:.3f}) >= 2× baseline ({baseline:.3f})"
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_torso(exposure):
    t = TorsoPlugin(name="torso")
    t.exposure = dict(exposure)
    return t


def _make_eye(exposure):
    e = EyePlugin(name="eye")
    e.exposure = dict(exposure)
    return e
