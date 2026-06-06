"""Tests for ``caldanai.lib.rpg.combat.resolution.apply_sequence_to_target``.

This pure helper owns the per-hit routing + hook-firing + injury
feedback coalescing loop that was previously duplicated across
``Game.do_combat`` (player -> monster), ``MonsterPlugin.attack_random``
(monster -> player), and ``Hydra.attack_random`` (custom multi-target).

Key invariants pinned here:

- ``target.apply_damage(result.damage, dmg_type=..., target_part=...)``
  is called once per result with positive damage.
- ``on_injury_change`` fires exactly once per unique part whose injury
  level changed across the sequence (never per-hit).
- ``on_destroyed`` fires exactly once per unique part that transitioned
  to USELESS (never on a part that was already destroyed).
- ``attacker.on_target_part_destroyed`` fires only when ``attacker`` is
  passed; default ``attacker=None`` keeps the player -> monster path's
  existing asymmetry.
- ``ResolutionResult.body_damage_total`` is the raw pre-defense sum of
  per-hit damages (floor application is the caller's responsibility).
- ``ResolutionResult.num_hits`` counts results with ``damage > 0`` only.
"""

from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.combat.attack_result import AttackResult, AttackSequence
from caldanai.lib.rpg.combat.resolution import (
    ResolutionResult,
    apply_sequence_to_target,
    compute_body_hp_damage,
    distribute_body_hp,
)
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingPart(BodyPart):
    """BodyPart that records hook invocations for assertion."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.injury_change_calls = []
        self.destroyed_calls = 0
        self.injury_change_return = ""
        self.destroyed_return = ""

    def on_injury_change(self, creature, old_level, new_level) -> str:
        self.injury_change_calls.append((old_level, new_level))
        return self.injury_change_return

    def on_destroyed(self, creature) -> str:
        self.destroyed_calls += 1
        return self.destroyed_return


def _make_creature(health=100, health_max=100, **kwargs):
    defaults = dict(
        name="goblin",
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=health_max,
        health=health,
    )
    defaults.update(kwargs)
    return Creature(**defaults)


def _make_result(damage, target_part, dmg_type=None):
    """Construct a minimal AttackResult for the helper to consume."""
    src = MagicMock()
    src.label = "Test"
    combined = MagicMock()
    combined.isMiss = damage <= 0
    combined.isCritical = False
    combined.isFumble = False
    return AttackResult(
        source=src,
        combined=combined,
        damage=damage,
        multiplier=1.0,
        defense=0,
        dodge=0,
        dmg_type=dmg_type,
        target_part=target_part,
    )


def _make_sequence(attacker, target, results):
    return AttackSequence(
        attacker=attacker, target=target, results=list(results),
    )


# ---------------------------------------------------------------------------
# ResolutionResult shape
# ---------------------------------------------------------------------------


class TestResolutionResultShape:
    def test_fields_present(self):
        rr = ResolutionResult(
            body_damage_total=0,
            injury_feedback_lines=[],
            death_msg="",
            num_hits=0,
        )
        assert rr.body_damage_total == 0
        assert rr.injury_feedback_lines == []
        assert rr.death_msg == ""
        assert rr.num_hits == 0
        assert rr.critical_part_kill is False  # sane default


# ---------------------------------------------------------------------------
# Single-hit sequence
# ---------------------------------------------------------------------------


class TestSingleHit:
    def test_apply_damage_called_once(self):
        arm = _RecordingPart(name="arm", health_max=50)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [_make_result(10, arm)])

        rr = apply_sequence_to_target(seq, target)

        assert arm.health == 40
        assert rr.num_hits == 1
        assert rr.body_damage_total == 10

    def test_no_hook_double_fire_on_single_hit(self):
        """One hit that transitions NONE -> MINOR fires on_injury_change
        exactly once and on_destroyed zero times."""
        arm = _RecordingPart(name="arm", health_max=50)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        # 10 damage on a 50-hp arm -> health 40 -> MINOR level.
        seq = _make_sequence(attacker, target, [_make_result(10, arm)])

        apply_sequence_to_target(seq, target)

        assert len(arm.injury_change_calls) == 1
        assert arm.injury_change_calls[0] == (InjuryLevels.NONE, InjuryLevels.MINOR)
        assert arm.destroyed_calls == 0

    def test_zero_damage_result_is_skipped(self):
        """Misses (``damage == 0``) must not route through apply_damage
        and must not affect num_hits or body_damage_total."""
        arm = _RecordingPart(name="arm", health_max=50)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [_make_result(0, arm)])

        rr = apply_sequence_to_target(seq, target)

        assert arm.health == 50
        assert rr.num_hits == 0
        assert rr.body_damage_total == 0
        assert arm.injury_change_calls == []


# ---------------------------------------------------------------------------
# Multi-hit same part — coalesced hook firing
# ---------------------------------------------------------------------------


class TestMultiHitSamePart:
    def test_apply_damage_called_per_hit(self):
        """Even though hooks coalesce to one call, damage routing still
        happens per hit — the part's health should reflect every hit."""
        arm = _RecordingPart(name="arm", health_max=50)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(
            attacker, target,
            [_make_result(5, arm), _make_result(5, arm), _make_result(5, arm)],
        )

        rr = apply_sequence_to_target(seq, target)

        assert arm.health == 35
        assert rr.num_hits == 3
        assert rr.body_damage_total == 15

    def test_on_injury_change_fires_once_for_coalesced_transition(self):
        """Three hits that move the same part from NONE to MODERATE
        should fire ``on_injury_change`` exactly once, with the
        combined old/new levels."""
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        # 5 damage total across 3 hits -> health 5/10 -> MODERATE.
        seq = _make_sequence(
            attacker, target,
            [_make_result(2, arm), _make_result(2, arm), _make_result(1, arm)],
        )

        apply_sequence_to_target(seq, target)

        assert len(arm.injury_change_calls) == 1
        old, new = arm.injury_change_calls[0]
        assert old == InjuryLevels.NONE
        assert new == InjuryLevels.MODERATE

    def test_no_injury_change_call_when_level_unchanged(self):
        """A sequence whose hits all stay within the same injury level
        must NOT fire ``on_injury_change``."""
        arm = _RecordingPart(name="arm", health_max=100)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        # Two tiny hits on a big arm — stays at NONE.
        # get_injury_level: NONE when health_percent == 1.0.
        # 1 damage drops it to MINOR, which *does* fire a transition,
        # so use 0-damage hits that target the part but don't harm it.
        # But _make_result(0, ...) is treated as a miss — skip entirely.
        # Instead, cause two hits that both leave the level at MINOR.
        seq = _make_sequence(
            attacker, target,
            [_make_result(5, arm), _make_result(5, arm)],
        )

        apply_sequence_to_target(seq, target)

        # 10 damage on 100-hp arm -> 90/100 -> MINOR.
        # Only one transition fires (NONE -> MINOR); not two.
        assert len(arm.injury_change_calls) == 1


# ---------------------------------------------------------------------------
# Destroyed parts
# ---------------------------------------------------------------------------


class TestPartDestruction:
    def test_on_destroyed_fires_once_when_sequence_destroys_part(self):
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        # Two hits, second destroys.
        seq = _make_sequence(
            attacker, target,
            [_make_result(5, arm), _make_result(10, arm)],
        )

        apply_sequence_to_target(seq, target)

        assert arm.is_destroyed()
        assert arm.destroyed_calls == 1

    def test_on_destroyed_does_not_fire_on_already_destroyed_part(self):
        """If a part is already USELESS entering the sequence and the
        sequence just piles on more damage, ``on_destroyed`` must NOT
        fire again."""
        arm = _RecordingPart(name="arm", health_max=10)
        # Pre-destroy the arm.
        arm.health = 0
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(
            attacker, target, [_make_result(5, arm), _make_result(5, arm)],
        )

        apply_sequence_to_target(seq, target)

        assert arm.is_destroyed()
        # Old level was USELESS, new level is USELESS -> no transition, no hook.
        assert arm.destroyed_calls == 0
        assert arm.injury_change_calls == []


# ---------------------------------------------------------------------------
# Attacker-side hook (asymmetry made explicit)
# ---------------------------------------------------------------------------


class _HookingAttacker(Creature):
    """Attacker that records on_target_part_destroyed invocations."""

    def __init__(self, **kwargs):
        super().__init__(
            name=kwargs.pop("name", "fiend"),
            atk=kwargs.pop("atk", "1d4"),
            defense=kwargs.pop("defense", 1),
            dodge=kwargs.pop("dodge", 1),
            health_max=kwargs.pop("health_max", 10),
            health=kwargs.pop("health", 10),
        )
        self.destruction_calls = []

    def on_target_part_destroyed(self, victim, part) -> str:
        self.destruction_calls.append((victim, part))
        return ""


class _MonsterLikeCreature(Creature):
    """Minimal stand-in for ``MonsterPlugin`` — returns a death message
    from ``apply_damage`` on the alive→dead transition, matching
    ``MonsterPlugin.apply_damage``'s contract. Lets the resolution
    tests exercise the critical-part-kill signal without dragging
    the full plugin loader in."""

    def __init__(self, **kwargs):
        super().__init__(
            name=kwargs.pop("name", "test-monster"),
            atk=kwargs.pop("atk", "1d4"),
            defense=kwargs.pop("defense", 1),
            dodge=kwargs.pop("dodge", 1),
            health_max=kwargs.pop("health_max", 50),
            health=kwargs.pop("health", 50),
        )
        self.death = "the test-monster dies dramatically"

    def apply_damage(self, amount, dmg_type=None, target_part=None):
        was_alive = self.health > 0
        super().apply_damage(amount, dmg_type=dmg_type, target_part=target_part)
        if was_alive and self.is_dead():
            return self.death
        return ""


class TestCriticalPartKillSignal:
    """Pin the ``critical_part_kill`` flag (replaces the old
    ``actual_body_damage < health_before`` inference). The flag fires
    when a part-targeted ``apply_damage`` returns a death message —
    i.e. a critical body part was destroyed and that killed the
    target. False-positives against body-HP-depletion and
    non-part-targeted kill paths would defeat the whole point."""

    def _critical_part(self):
        part = _RecordingPart(name="head", health_max=10)
        part.is_critical = True
        return part

    def test_critical_part_kill_sets_flag(self):
        head = self._critical_part()
        target = _MonsterLikeCreature(health_max=50)
        target.body_parts = [head]
        attacker = _make_creature()
        # 10 damage to a 10-HP critical head → destroyed → target dies.
        seq = _make_sequence(attacker, target, [_make_result(10, head)])

        rr = apply_sequence_to_target(seq, target)

        assert target.is_dead()
        assert rr.critical_part_kill is True
        assert rr.death_msg == "the test-monster dies dramatically"

    def test_non_lethal_critical_part_hit_does_not_set_flag(self):
        """A hit on a critical part that doesn't destroy it shouldn't
        trip the flag — only the destroying hit + resulting death
        qualifies."""
        head = self._critical_part()
        target = _MonsterLikeCreature(health_max=50)
        target.body_parts = [head]
        attacker = _make_creature()
        # 4 damage → 6/10, part not destroyed, target alive.
        seq = _make_sequence(attacker, target, [_make_result(4, head)])

        rr = apply_sequence_to_target(seq, target)

        assert not target.is_dead()
        assert rr.critical_part_kill is False

    def test_non_critical_part_destruction_does_not_set_flag(self):
        """Destroying a non-critical part (arm, leg) isn't a
        critical-part kill — even if the target happens to die some
        other way (it won't here, since non-critical parts don't kill
        outright)."""
        arm = _RecordingPart(name="arm", health_max=10)
        arm.is_critical = False
        target = _MonsterLikeCreature(health_max=50)
        target.body_parts = [arm]
        attacker = _make_creature()
        seq = _make_sequence(attacker, target, [_make_result(10, arm)])

        rr = apply_sequence_to_target(seq, target)

        assert arm.is_destroyed()
        assert not target.is_dead()
        assert rr.critical_part_kill is False

    def test_partless_target_kill_does_not_set_flag(self):
        """Partless targets never route through the part-apply path
        (explicitly skipped to avoid double-damage), so they can't
        produce a critical-part-kill signal even when killed."""
        target = _MonsterLikeCreature(health_max=5, health=5)
        target.body_parts = []
        attacker = _make_creature()
        # No target_part; partless → apply_damage skipped in helper.
        seq = _make_sequence(
            attacker, target,
            [_make_result(10, target_part=None)],
        )

        rr = apply_sequence_to_target(seq, target)

        # Target still alive here because helper skipped apply_damage
        # for the partless case — do_combat would then apply the
        # post-defense body total. critical_part_kill must be False
        # regardless of how the caller finishes the job.
        assert rr.critical_part_kill is False


class TestAttackerAsymmetry:
    def test_attacker_auto_inferred_from_sequence_when_hook_defined(self):
        """When the caller omits ``attacker=``, the helper auto-infers
        from ``sequence.attacker`` and fires the hook if the attacker
        defines ``on_target_part_destroyed``. Pre-fix this test pinned
        the opposite (no-fire) behavior; the backlog
        ``attacker_auto_infer`` item flipped it so future multi-victim
        overrides can't silently drop the hook by forgetting the
        kwarg. The player-attacks-monster asymmetry is preserved via
        the ``hasattr`` gate (see below)."""
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker_in_sequence = _HookingAttacker()
        seq = _make_sequence(
            attacker_in_sequence, target, [_make_result(10, arm)],
        )

        apply_sequence_to_target(seq, target)  # no attacker= kwarg

        assert arm.is_destroyed()
        assert len(attacker_in_sequence.destruction_calls) == 1

    def test_auto_infer_respects_hasattr_gate_on_player_like_attacker(self):
        """The player-attacks-monster asymmetry is preserved by the
        ``hasattr`` gate: a sequence.attacker that doesn't define
        ``on_target_part_destroyed`` (e.g. a Player) has nothing to
        fire, so auto-infer is a no-op regardless of what landed."""
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        # Plain Creature: has no ``on_target_part_destroyed`` method —
        # same shape as a Player attacker.
        player_like = _make_creature(health_max=10)
        assert not hasattr(player_like, "on_target_part_destroyed")
        seq = _make_sequence(
            player_like, target, [_make_result(10, arm)],
        )

        # Must not raise; hasattr gate skips the call cleanly.
        apply_sequence_to_target(seq, target)

        assert arm.is_destroyed()

    def test_explicit_attacker_kwarg_overrides_sequence_attacker(self):
        """When the caller passes ``attacker=...`` AND ``sequence.attacker``
        is set to a different value, the explicit kwarg wins. The
        sequence's attacker is not used as a fallback when the kwarg is
        already non-None. Documents the override-to-suppress shape:
        existing callers passing ``attacker=self`` keep their exact
        behavior even after the auto-infer landed."""
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        sequence_attacker = _HookingAttacker(name="sequence_attacker")
        explicit_attacker = _HookingAttacker(name="explicit_attacker")
        seq = _make_sequence(
            sequence_attacker, target, [_make_result(10, arm)],
        )

        apply_sequence_to_target(seq, target, attacker=explicit_attacker)

        assert arm.is_destroyed()
        # Explicit kwarg fired the hook; sequence.attacker did not.
        assert len(explicit_attacker.destruction_calls) == 1
        assert sequence_attacker.destruction_calls == []

    def test_attacker_passed_fires_hook_once_per_destroyed_part(self):
        """When the caller passes ``attacker=...``, the hook fires
        exactly once per part that transitioned into USELESS."""
        arm = _RecordingPart(name="arm", health_max=10)
        leg = _RecordingPart(name="leg", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm, leg]
        attacker = _HookingAttacker()
        seq = _make_sequence(
            attacker, target,
            [
                _make_result(5, arm),
                _make_result(5, arm),   # destroys arm
                _make_result(10, leg),  # destroys leg
            ],
        )

        apply_sequence_to_target(seq, target, attacker=attacker)

        assert arm.is_destroyed()
        assert leg.is_destroyed()
        # Fires on both destroyed parts, exactly once each.
        destroyed_parts = [p for _, p in attacker.destruction_calls]
        assert len(destroyed_parts) == 2
        assert arm in destroyed_parts
        assert leg in destroyed_parts

    def test_attacker_hook_not_fired_on_non_destroying_hits(self):
        """If no part transitions to USELESS, the attacker hook does
        not fire even when attacker is passed."""
        arm = _RecordingPart(name="arm", health_max=100)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _HookingAttacker()
        seq = _make_sequence(attacker, target, [_make_result(5, arm)])

        apply_sequence_to_target(seq, target, attacker=attacker)

        assert not arm.is_destroyed()
        assert attacker.destruction_calls == []

    def test_attacker_hook_skips_already_destroyed_parts(self):
        """A part already USELESS before the sequence does not trigger
        the attacker hook again, mirroring ``on_destroyed`` behavior."""
        arm = _RecordingPart(name="arm", health_max=10)
        arm.health = 0  # already USELESS
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _HookingAttacker()
        seq = _make_sequence(attacker, target, [_make_result(5, arm)])

        apply_sequence_to_target(seq, target, attacker=attacker)

        assert attacker.destruction_calls == []


# ---------------------------------------------------------------------------
# body_damage_total and num_hits
# ---------------------------------------------------------------------------


class TestAggregateFields:
    def test_body_damage_total_sums_positive_hits_only(self):
        """``body_damage_total`` is the sum of ``result.damage`` across
        hits with positive damage — before any defense/floor application.
        Caller is responsible for floor math."""
        arm = _RecordingPart(name="arm", health_max=50)
        leg = _RecordingPart(name="leg", health_max=50)
        target = _make_creature(health_max=100)
        target.body_parts = [arm, leg]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(
            attacker, target,
            [
                _make_result(0, arm),    # miss
                _make_result(3, arm),
                _make_result(7, leg),
            ],
        )

        rr = apply_sequence_to_target(seq, target)

        assert rr.num_hits == 2
        assert rr.body_damage_total == 10

    def test_pre_floor_total_matches_sequence_total(self):
        """The helper's body_damage_total matches
        ``sequence.total_damage()`` for any sequence of hits, confirming
        the helper isn't applying the floor itself."""
        arm = _RecordingPart(name="arm", health_max=100)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(
            attacker, target,
            [_make_result(2, arm), _make_result(3, arm), _make_result(5, arm)],
        )

        rr = apply_sequence_to_target(seq, target)

        assert rr.body_damage_total == seq.total_damage()


# ---------------------------------------------------------------------------
# Injury feedback lines
# ---------------------------------------------------------------------------


class TestInjuryFeedback:
    def test_produces_feedback_line_on_level_transition(self):
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        # 6 damage -> 4/10 -> MODERATE.
        seq = _make_sequence(attacker, target, [_make_result(6, arm)])

        rr = apply_sequence_to_target(seq, target)

        # At least one line — the formatted injury string — is produced
        # for parts that land on a non-NONE injury level.
        assert any("moderate" in line.lower() for line in rr.injury_feedback_lines)

    def test_feedback_line_prefixes_target_name_possessive(self):
        """Regression (backlog item): anonymous "The right leg seems
        lightly battered." becomes unreadable in multi-target rounds
        (hydra today, swarms / AoE later). Owner-possessive prefix
        via ``@1npc`` disambiguates. For a monster target named
        "goblin", renders as "The goblin's right arm…" — the parser's
        ``np`` form auto-prepends the article for article-using
        creatures (matches the parser docstring's intent). Functional
        goal met: whose part it is, is unambiguous, and the phrasing
        is grammatical."""
        arm = _RecordingPart(name="arm.right", health_max=10)
        target = _make_creature(name="goblin", health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        # 4 damage -> 6/10 -> MINOR.
        seq = _make_sequence(attacker, target, [_make_result(4, arm)])

        rr = apply_sequence_to_target(seq, target)

        joined = "\n".join(rr.injury_feedback_lines)
        assert "The goblin's right arm seems" in joined, (
            f"owner-prefixed phrasing missing in: {joined!r}"
        )
        # The old bare "The right arm seems..." (no owner) should no
        # longer appear — we strip "the " before prepending the owner.
        assert "The right arm seems" not in joined, (
            f"anonymous pre-fix phrasing still present in: {joined!r}"
        )

    def test_feedback_line_prefixes_player_target_with_bare_possessive(self):
        """Player-victim counterpart to the monster regression above.
        Players carry ``uses_article=False`` so ``@1npc`` renders as a
        bare name-possessive (``"Caels's"``), without the leading
        article. The owner-prefix branch then attributes the line to
        the player so multi-target rounds attacking a party
        (future AoE / ranged splash) read as e.g.
        ``"Caels's right leg seems lightly battered."`` rather than
        the anonymous ``"The right leg seems lightly battered."``."""
        leg = _RecordingPart(name="leg.right", health_max=10)
        target = _make_creature(name="Caels", health_max=100)
        target.uses_article = False
        target.body_parts = [leg]
        attacker = _make_creature(name="bandit")
        # 4 damage -> 6/10 -> MINOR.
        seq = _make_sequence(attacker, target, [_make_result(4, leg)])

        rr = apply_sequence_to_target(seq, target)

        joined = "\n".join(rr.injury_feedback_lines)
        assert "Caels's right leg seems" in joined, (
            f"owner-prefixed phrasing missing in: {joined!r}"
        )
        # No stray article — players are named-entities, no "The Caels's".
        assert "The Caels" not in joined, (
            f"article leaked into player possessive in: {joined!r}"
        )

    def test_multi_victim_aoe_attributes_each_injury_to_its_owner(self):
        """Hydra-style AoE rounds (and future ranged-splash / swarm)
        call ``apply_sequence_to_target`` once per victim, then a
        downstream stage concatenates the lines. Without per-line
        owner attribution the stream reads as anonymous ``"The right
        leg…" / "The left arm…"`` and the reader can't tell whose
        part each line refers to. This pins that each victim's line
        carries that victim's possessive — so a streamed
        ``"\n".join(...)`` of both ``injury_feedback_lines`` lists
        stays unambiguous."""
        # Two named victims with article-disambiguated bodies — one
        # player-shaped (``uses_article=False``), one monster-shaped.
        # Mirrors the realistic case where an AoE hits the player and
        # an allied passerby / cohort at the same time, or two
        # adjacent monsters from a future PC-side AoE.
        caels_leg = _RecordingPart(name="leg.right", health_max=10)
        caels = _make_creature(name="Caels", health_max=100)
        caels.uses_article = False
        caels.body_parts = [caels_leg]

        goblin_arm = _RecordingPart(name="arm.left", health_max=10)
        goblin = _make_creature(name="goblin", health_max=100)
        goblin.body_parts = [goblin_arm]

        attacker = _make_creature(name="hydra")
        seq_caels = _make_sequence(attacker, caels, [_make_result(4, caels_leg)])
        seq_goblin = _make_sequence(attacker, goblin, [_make_result(4, goblin_arm)])

        rr_caels = apply_sequence_to_target(seq_caels, caels, attacker=attacker)
        rr_goblin = apply_sequence_to_target(seq_goblin, goblin, attacker=attacker)

        joined = "\n".join(
            rr_caels.injury_feedback_lines + rr_goblin.injury_feedback_lines
        )
        assert "Caels's right leg" in joined, (
            f"player-victim owner missing in: {joined!r}"
        )
        assert "The goblin's left arm" in joined, (
            f"monster-victim owner missing in: {joined!r}"
        )
        # Sanity: neither anonymous form survives the round.
        assert "The right leg seems" not in joined
        assert "The left arm seems" not in joined

    def test_hook_return_strings_included_in_feedback(self):
        """Non-empty returns from on_injury_change / on_destroyed are
        appended to the feedback lines."""
        arm = _RecordingPart(name="arm", health_max=10)
        arm.injury_change_return = "ARM-HURT-MSG"
        arm.destroyed_return = "ARM-DEAD-MSG"
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [_make_result(10, arm)])

        rr = apply_sequence_to_target(seq, target)

        joined = "\n".join(rr.injury_feedback_lines)
        assert "ARM-HURT-MSG" in joined
        assert "ARM-DEAD-MSG" in joined

    def test_attacker_hook_return_included_in_feedback(self):
        """When the attacker's on_target_part_destroyed returns text,
        it appears in the feedback lines — mirroring the monster ->
        player path's flavor layering."""
        arm = _RecordingPart(name="arm", health_max=10)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]

        class _FlavorAttacker(_HookingAttacker):
            def on_target_part_destroyed(self, victim, part) -> str:
                super().on_target_part_destroyed(victim, part)
                return "ATTACKER-FLAVOR"

        attacker = _FlavorAttacker()
        seq = _make_sequence(attacker, target, [_make_result(10, arm)])

        rr = apply_sequence_to_target(seq, target, attacker=attacker)

        joined = "\n".join(rr.injury_feedback_lines)
        assert "ATTACKER-FLAVOR" in joined


# ---------------------------------------------------------------------------
# death_msg propagation
# ---------------------------------------------------------------------------


class TestDeathMessage:
    def test_death_msg_from_critical_part_captured(self):
        """If per-part routing through ``target.apply_damage`` returns a
        non-empty death message (critical part destruction path), the
        helper captures it on the result."""
        head = _RecordingPart(name="head", health_max=10, is_critical=True)
        target = _make_creature(health_max=100)
        target.body_parts = [head]

        # Swap apply_damage so we can assert on the return path.
        real_apply = target.apply_damage
        death_returns = []

        def spy(amount, dmg_type=None, target_part=None):
            real_apply(
                amount,
                dmg_type=dmg_type,
                target_part=target_part,
            )
            msg = "CRIT-DEATH" if target.is_dead() else ""
            death_returns.append(msg)
            return msg

        target.apply_damage = spy

        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [_make_result(10, head)])

        rr = apply_sequence_to_target(seq, target)

        assert rr.death_msg == "CRIT-DEATH"

    def test_death_msg_is_empty_when_no_death(self):
        arm = _RecordingPart(name="arm", health_max=50)
        target = _make_creature(health_max=100)
        target.body_parts = [arm]
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [_make_result(5, arm)])

        rr = apply_sequence_to_target(seq, target)

        assert rr.death_msg == ""

    def test_gear_drop_line_does_not_swallow_later_death_line(self):
        """Regression (LIVE cyclops fight, 2026-06-04): a multi-source
        retaliation where an EARLIER source destroys a gear-bearing
        non-fatal part and a LATER source lands the fatal blow.

        ``Player.apply_damage`` returns a CONFLATED string — gear-drop
        narration for the newly-useless part PLUS a death tail on the
        alive->dead transition. The old first-non-empty-wins capture
        let the right-hand's "torch slips free" line claim the single
        ``death_msg`` slot, so the neck-kill's "crumples lifelessly"
        line was silently dropped: the player died with no death
        message in the channel. Every non-empty ``apply_damage`` return
        must now survive, in hit order."""
        hand = _RecordingPart(name="hand", health_max=6)  # non-critical
        neck = _RecordingPart(name="neck", health_max=8, is_critical=True)
        target = _make_creature(name="Vael", health_max=21)
        target.body_parts = [hand, neck]

        # Mimic ``Player.apply_damage``'s conflated return: a gear-drop
        # line for a newly-destroyed non-critical part, a crumple tail
        # on death — joined into one string per call.
        real_apply = target.apply_damage

        def player_like_apply(amount, dmg_type=None, target_part=None):
            was_alive = not target.is_dead()
            real_apply(amount, dmg_type=dmg_type, target_part=target_part)
            lines = []
            if (
                target_part is not None
                and target_part.is_destroyed()
                and not target_part.is_critical
            ):
                lines.append("Their torch slips free.")
            if was_alive and target.is_dead():
                lines.append("Vael crumples to the ground lifelessly!")
            return "\n".join(lines)

        target.apply_damage = player_like_apply

        attacker = _make_creature(name="cyclops")
        # Hand destroyed FIRST (drops gear), neck destroyed SECOND (kills).
        seq = _make_sequence(
            attacker, target,
            [_make_result(6, hand), _make_result(8, neck)],
        )

        rr = apply_sequence_to_target(seq, target)

        assert target.is_dead()
        assert "Their torch slips free." in rr.death_msg
        assert "Vael crumples to the ground lifelessly!" in rr.death_msg
        # In-fiction order: gear leaves while still alive, then death.
        assert rr.death_msg.index("torch") < rr.death_msg.index("crumples")


# ---------------------------------------------------------------------------
# Empty / null-route sequence
# ---------------------------------------------------------------------------


class TestEmptySequence:
    def test_empty_sequence_is_noop(self):
        target = _make_creature(health_max=100)
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [])

        rr = apply_sequence_to_target(seq, target)

        assert rr.num_hits == 0
        assert rr.body_damage_total == 0
        assert rr.injury_feedback_lines == []
        assert rr.death_msg == ""

    def test_partless_target_skips_apply_damage_to_avoid_double_damage(self):
        """Regression: when a result targets a partless creature
        (e.g. Spirit), ``apply_sequence_to_target`` must NOT call
        ``apply_damage`` — the legacy path in ``Creature.apply_damage``
        would decrement body HP here, and the caller (``do_combat``)
        ALSO subtracts the post-defense body total afterwards.
        Letting both fire produced double-damage (playtested
        2026-04-18: Spirit at 16 HP took 19 damage from a single
        10-damage crit after defense). Body HP is the caller's sole
        responsibility across both partless and parts paths; the
        sequence resolver just accumulates the totals."""
        target = _make_creature(health_max=100)
        # No body_parts on target — target_part=None stays None.
        attacker = _make_creature(name="bandit")
        seq = _make_sequence(attacker, target, [_make_result(10, None)])

        rr = apply_sequence_to_target(seq, target)

        # Body HP unchanged — caller (do_combat) owns body HP for
        # partless targets.
        assert target.health == 100
        # Totals still accumulate so the caller can apply them.
        assert rr.num_hits == 1
        assert rr.body_damage_total == 10


# ---------------------------------------------------------------------------
# distribute_body_hp — Core Dmg column reconciles with applied body HP
# ---------------------------------------------------------------------------


def _bleed_part(name, rate):
    part = _RecordingPart(name=name, health_max=50)
    part.bleed_rate = rate
    return part


class TestDistributeBodyHp:
    """The Core Dmg column must sum to exactly the body HP that
    ``apply_damage`` writes (``compute_body_hp_damage``). The old per-row
    ``int(final * rate * mod)`` dropped fractional carry AND skipped the
    ``max(num_hits, …)`` floor, so a landed hit could show 0 while the
    body still took >= 1 for it — the live hydra mismatch (column summed
    to 1, bleed-through line said 2)."""

    def _result(self, damage, rate):
        return _make_result(damage, _bleed_part(f"p{rate}", rate))

    def _applied(self, results, victim):
        rr = ResolutionResult(
            body_damage_total=sum(r.damage for r in results if r.damage > 0),
            num_hits=sum(1 for r in results if r.damage > 0),
        )
        return compute_body_hp_damage(rr, victim, results=results)

    def test_reported_hydra_scenario_column_sums_to_bleedthrough(self):
        """leg 3@0.3 + torso 2@0.55 → float-sum 2.0 → applied 2, but the
        old column showed int(0.9)=0 and int(1.1)=1 (sum 1). The fix
        apportions the real total so the column sums to 2."""
        victim = _make_creature(health_max=22)
        results = [self._result(3, 0.3), self._result(2, 0.55)]

        alloc = distribute_body_hp(results, victim)

        assert sum(alloc) == self._applied(results, victim) == 2
        assert alloc == [1, 1]  # 2 apportioned across the 2 hits

    def test_surplus_distributed_by_bleed_share(self):
        """8@0.5 + 2@0.5 → float-sum 5.0 → applied 5, apportioned purely
        by bleed-share (4.0 vs 1.0) → [4, 1]; no per-hit floor."""
        victim = _make_creature(health_max=100)
        results = [self._result(8, 0.5), self._result(2, 0.5)]

        alloc = distribute_body_hp(results, victim)

        assert sum(alloc) == self._applied(results, victim) == 5
        assert alloc == [4, 1]

    def test_misses_get_zero_and_dont_count(self):
        victim = _make_creature(health_max=100)
        hit = self._result(4, 0.5)
        miss = _make_result(0, _bleed_part("missed", 0.5))  # damage 0
        results = [miss, hit]

        alloc = distribute_body_hp(results, victim)

        assert alloc[0] == 0  # the miss contributes nothing
        assert sum(alloc) == self._applied(results, victim)

    def test_bleed_mod_scales_the_total(self):
        """A creature-wide BLEED_MOD > 1 raises the applied total; the
        apportionment must still sum to it."""
        victim = _make_creature(health_max=100)
        victim.BLEED_MOD = 2.0
        results = [self._result(3, 0.5), self._result(3, 0.5)]
        # float-sum 3.0 * 2.0 = 6.0 → applied 6.
        alloc = distribute_body_hp(results, victim)

        assert sum(alloc) == self._applied(results, victim) == 6

    def test_sum_always_equals_applied_invariant(self):
        victim = _make_creature(health_max=100)
        for spec in ([(1, 0.2)], [(5, 0.4), (1, 0.9)],
                     [(2, 0.1), (2, 0.1), (9, 0.8)], [(7, 1.0)]):
            results = [self._result(d, r) for d, r in spec]
            alloc = distribute_body_hp(results, victim)
            assert sum(alloc) == self._applied(results, victim)
            assert all(a >= 0 for a in alloc)  # floor at 0, not 1

    def test_light_scratches_floor_to_zero(self):
        """Floor lowered from num_hits to 0 (2026-06-06): a flurry of
        light scratches that bleeds < 1 in total deals 0 body HP, and the
        Core Dmg column shows 0 for every row — nobody dies from
        scratches. The old num_hits floor would have forced N body HP."""
        victim = _make_creature(health_max=100)
        # 2*0.1 + 2*0.1 + 1*0.1 = 0.5 → int 0.
        results = [self._result(2, 0.1), self._result(2, 0.1),
                   self._result(1, 0.1)]
        alloc = distribute_body_hp(results, victim)
        assert self._applied(results, victim) == 0
        assert alloc == [0, 0, 0]
        # A single sub-1 bleed also floors to 0 (was 1 under the old floor).
        one = [self._result(5, 0.05)]  # 0.25 → int 0
        assert distribute_body_hp(one, victim) == [0]
        assert self._applied(one, victim) == 0
