"""Tests for tools.playtest_monster_duel.

The tool itself is a thin harness around ``MonsterPlugin.attack_random``
on both sides. What's worth pinning is the aim-recording — that the
patched ``pick_random_part`` / ``_collapse_to_region`` wrappers
capture pre- and post-collapse target distributions correctly, and
that the recorder bookkeeping scopes to the right creature when
attacker and defender swap turns.
"""

from collections import Counter
from unittest import TestCase

from tools.playtest_monster_duel import (
    DuelOutcome,
    _AimRecorder,
    _render_distribution,
    _run_one_duel,
)


class AimRecorderTests(TestCase):
    def test_recorder_patches_and_restores_module_functions(self):
        """The recorder's ``install`` / ``restore`` lifecycle must
        leave the module in its original state — otherwise one
        harness run poisons the next."""
        from caldanai.lib.rpg import creatures as cm

        orig_pick = cm.pick_random_part
        orig_collapse = cm._collapse_to_region

        rec = _AimRecorder()
        rec.install()
        self.assertIsNot(cm.pick_random_part, orig_pick)
        self.assertIsNot(cm._collapse_to_region, orig_collapse)

        rec.restore()
        self.assertIs(cm.pick_random_part, orig_pick)
        self.assertIs(cm._collapse_to_region, orig_collapse)

    def test_bind_then_unbind_tracks_aim_distribution(self):
        """A short goblin-vs-bandit duel produces non-empty aim
        distributions for both attackers. Exact numbers are
        RNG-dependent; the invariant is "we recorded something."""
        rec = _AimRecorder()
        rec.install()
        try:
            outcome = _run_one_duel("goblin", "bandit", rounds_cap=20, recorder=rec)
        finally:
            rec.restore()

        # At least one side must have landed aims — a 20-round
        # duel between two non-trivial monsters reliably produces
        # pick_random_part calls on both sides.
        total_aims = (
            sum(outcome.attacker_aim_pre.values())
            + sum(outcome.defender_aim_pre.values())
        )
        self.assertGreater(total_aims, 0)

    def test_same_size_baseline_collapse_never_fires(self):
        """Goblin (SMALL, 0.75) vs bandit (MEDIUM, 1.0): ratio
        0.75, nowhere near the collapse threshold (2.0). Post-
        collapse distribution should match pre-collapse."""
        rec = _AimRecorder()
        rec.install()
        try:
            outcome = _run_one_duel("goblin", "bandit", rounds_cap=20, recorder=rec)
        finally:
            rec.restore()

        # Pre and post counters should be identical when collapse
        # is inactive — the wrapper still records them both, but
        # they're the same parts each time.
        self.assertEqual(outcome.attacker_aim_pre, outcome.attacker_aim_post)
        self.assertEqual(outcome.defender_aim_pre, outcome.defender_aim_post)

    def test_extreme_ratio_collapse_consolidates_on_torso(self):
        """Cyclops (HUGE, 1.5) vs pixie (TINY, 0.5): ratio 3.0,
        above the 2.0 threshold. Every non-torso pick walks one
        level up toward torso. Pixie has a flat topology (every
        non-torso part is a direct child of torso), so post-
        collapse picks are 100% torso.

        Dragon would also have ratio 3.0 but its ``attack_random``
        override pre-empts the pipeline with a breath-attack AOE
        that bypasses ``pick_random_part``, so recording is
        unreliable on dragons. Cyclops has no such override.

        Averaging across a few trials to smooth RNG variance —
        a single duel can resolve in one swing and record only
        a handful of picks."""
        rec = _AimRecorder()
        rec.install()
        try:
            aggregated_pre = Counter()
            aggregated_post = Counter()
            for _ in range(5):
                outcome = _run_one_duel(
                    "cyclops", "pixie", rounds_cap=30, recorder=rec,
                )
                aggregated_pre.update(outcome.attacker_aim_pre)
                aggregated_post.update(outcome.attacker_aim_post)
        finally:
            rec.restore()

        total_picks = sum(aggregated_pre.values())
        self.assertGreater(total_picks, 0)

        # Every landing is torso — the pixie's flat tree means
        # one level of walk-up from any non-torso pick lands on
        # torso.
        self.assertEqual(list(aggregated_post.keys()), ["torso"])
        self.assertEqual(sum(aggregated_post.values()), total_picks)


class RenderDistributionTests(TestCase):
    def test_empty_counter_produces_placeholder_line(self):
        out = _render_distribution(Counter(), "sample")
        self.assertIn("(no picks recorded)", out)

    def test_populated_counter_renders_sorted_by_count(self):
        c = Counter({"torso": 10, "head": 3, "eye": 1})
        out = _render_distribution(c, "aim")
        lines = out.splitlines()
        # First line is the header.
        self.assertIn("aim (n=14)", lines[0])
        # Parts listed in descending-count order.
        body = [line.strip().split()[0] for line in lines[1:]]
        self.assertEqual(body, ["torso", "head", "eye"])

    def test_percentages_sum_near_one_hundred(self):
        c = Counter({"torso": 70, "head": 20, "eye": 10})
        out = _render_distribution(c, "aim")
        # Extract the percent numbers.
        import re
        pcts = [float(m.group(1)) for m in re.finditer(r"\(\s*(\d+\.\d)%", out)]
        self.assertAlmostEqual(sum(pcts), 100.0, places=1)


class DuelOutcomeTests(TestCase):
    def test_duel_produces_a_winner_or_stalemate(self):
        rec = _AimRecorder()
        rec.install()
        try:
            outcome = _run_one_duel("goblin", "sheep", rounds_cap=50, recorder=rec)
        finally:
            rec.restore()
        self.assertIn(outcome.winner, {"attacker", "defender", "stalemate"})
        self.assertIsInstance(outcome, DuelOutcome)
        self.assertGreaterEqual(outcome.rounds, 1)
