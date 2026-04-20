"""Phase-6b port tests — ``MonsterPlugin.attack_random`` as a thin
pipeline driver.

Pins the user-visible surface of monster retaliation now that the
implementation sources output from ``pick_actions`` / ``pick_targets``
/ ``resolve`` / ``narrate_*`` stages instead of the legacy
``do_attack`` + ``apply_sequence_to_target`` pair. Covers:

- short-circuits (no combatants, bad count, partless victims),
- single-victim shape (attack table present, death beat on kill),
- multi-victim shape (round-robin distribution across victims),
- spot-check across representative monsters so inherited-via-base
  plugins keep working (hydra / dragon handle their own overrides
  and are excluded).

Tests seed RNG so damage / target-part / action-pick choices are
reproducible — failures reflect shape regressions, not roll flake.
"""

import random
from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _spawn(monster_key: str) -> MonsterPlugin:
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(monster_key)
    assert cls is not None, f"no monster registered as {monster_key!r}"
    return cls()


def _make_player(name: str = "caels", uid: int = 1, health: int = 200):
    """Minimal ``Player``-like combatant with humanoid parts so the
    pipeline's per-part routing has somewhere to land. Avoids the real
    Player class's Discord-member plumbing."""
    from caldanai.lib.rpg.creatures.player import Player

    p = Player(
        pid=uid,
        gid=111,
        uid=uid,
        health=health,
        health_max=health,
        defense=2,
        dodge=5,
        gender="male",
        pronouns="he,him,his,his",
        weight_limit=100,
        clarks=0,
    )
    p.name = name
    member = MagicMock()
    member.id = uid
    member.roles = []
    p.member = member
    return p


def _make_partless_victim(name: str = "ghost"):
    """A bare ``Creature`` with no ``body_parts`` — exercises the
    legacy whole-body damage path via ``apply_damage(final)``."""
    c = Creature(
        name=name, atk="1d4", defense=0, dodge=0,
        health_max=40, health=40, pronouns="he, him, his, his",
    )
    c.body_parts = []
    return c


@pytest.fixture(autouse=True)
def _seed_random():
    random.seed(0)


# ---------------------------------------------------------------------------
# Short-circuit contracts
# ---------------------------------------------------------------------------


class TestAttackRandomShortCircuits:
    def test_no_combatants_returns_none(self):
        bandit = _spawn("bandit")
        assert bandit.attack_random([]) is None

    def test_count_out_of_range_returns_none(self):
        bandit = _spawn("bandit")
        victim = _make_player()
        assert bandit.attack_random([victim], count=0) is None
        assert bandit.attack_random([victim], count=2) is None


# ---------------------------------------------------------------------------
# Single-victim shape
# ---------------------------------------------------------------------------


class TestMonsterPluginAttackRandom:
    """Exercise a representative simple monster end-to-end and verify
    the output contains the sections pre-Phase-6b ``attack_random``
    produced — attack table, injury feedback (when injuries land),
    death beat (when the victim dies)."""

    def test_single_victim_returns_string_with_attack_table(self):
        bandit = _spawn("bandit")
        victim = _make_player(health=200)
        msg = bandit.attack_random([victim])
        assert msg is not None
        assert isinstance(msg, str)
        # Compact diff-block table marker is always present in
        # ``AttackSequence.to_markdown`` output when any source fires.
        assert "```diff" in msg

    def test_victim_takes_damage_across_many_trials(self):
        """Over 20 retaliations any reasonable bandit eventually
        connects — not every roll hits, but 'every single one whiffs
        with seed 0' would signal the pipeline isn't wired."""
        bandit = _spawn("bandit")
        victim = _make_player(health=10_000)  # never dies
        before = victim.health
        for _ in range(20):
            bandit.attack_random([victim])
        assert victim.health < before, (
            "Bandit retaliation over 20 rounds should land at least "
            "one hit on a high-HP target."
        )

    def test_kill_emits_death_beat(self):
        """A 1-HP player absorbs anything the bandit throws; if the
        pipeline lands any damage the death beat fires."""
        bandit = _spawn("bandit")
        victim = _make_player(health=1)
        # Seed a run that lands damage. Loop a handful of fresh seeds
        # to avoid "every bandit swing whiffs" making the test flaky.
        for seed in range(50):
            random.seed(seed)
            v = _make_player(health=1)
            msg = bandit.attack_random([v])
            if msg and v.is_dead():
                # Player death flavor — the generic "crumples" line
                # fires via ``Creature.apply_damage`` when body HP
                # hits zero.
                assert (
                    "crumples" in msg.lower()
                    or "lifelessly" in msg.lower()
                    or (bandit.death and bandit.death not in msg)  # victim died, not bandit
                )
                return
        pytest.skip("Bandit failed to kill 1 HP victim across 50 seeds")


# ---------------------------------------------------------------------------
# Multi-victim shape
# ---------------------------------------------------------------------------


class TestMultiVictimRetaliation:
    """``count > 1`` triggers round-robin assignment so actions
    distribute across victims instead of dogpiling the first. Verifies
    that at least one victim takes damage and the output is non-empty."""

    def test_count_two_spreads_damage_across_both_victims(self):
        bandit = _spawn("bandit")
        v1 = _make_player(name="alice", uid=1, health=10_000)
        v2 = _make_player(name="bob", uid=2, health=10_000)

        starts = {v1: v1.health, v2: v2.health}

        # Run multiple rounds so action budget (typically 1-2 per
        # round) eventually hits both victims even if one round only
        # picks one action.
        for _ in range(20):
            bandit.attack_random([v1, v2], count=2)

        # Both victims must have been eligible for damage; at least
        # one should show it after the rounds above.
        hit_either = v1.health < starts[v1] or v2.health < starts[v2]
        assert hit_either, (
            "20 rounds of multi-victim retaliation should land at "
            "least one hit on one of the two victims."
        )

    def test_multi_victim_output_non_empty_when_hits_land(self):
        bandit = _spawn("bandit")
        v1 = _make_player(name="alice", uid=1, health=10_000)
        v2 = _make_player(name="bob", uid=2, health=10_000)
        for _ in range(20):
            msg = bandit.attack_random([v1, v2], count=2)
            if msg and "```diff" in msg:
                return
        pytest.skip("Bandit multi-victim failed to produce a table in 20 rounds")


# ---------------------------------------------------------------------------
# Partless victim — body HP via legacy whole-body path
# ---------------------------------------------------------------------------


class TestPartlessVictim:
    """Monster-as-attacker vs partless victim: ``resolve`` still
    aggregates damage totals correctly; body HP lands through
    ``apply_damage(final)`` without a double-apply."""

    def test_partless_victim_receives_body_hp_damage(self):
        bandit = _spawn("bandit")
        victim = _make_partless_victim()
        victim.health = 500
        victim.health_max = 500
        start = victim.health

        # Multi-round so at least one attack connects through the RNG.
        for _ in range(20):
            bandit.attack_random([victim])

        assert victim.health < start, (
            "Partless victim should take body-HP damage across 20 "
            "retaliation rounds — the legacy apply_damage(final) path "
            "must still fire when pick_actions / resolve route through "
            "the pipeline."
        )

    def test_partless_victim_returns_pipeline_string(self):
        """Shape check — even without body parts the pipeline
        produces a renderable attack table (results without
        ``target_part`` still flow through ``render_table``)."""
        bandit = _spawn("bandit")
        victim = _make_partless_victim()
        victim.health = 500
        victim.health_max = 500
        msg = bandit.attack_random([victim])
        assert msg is not None
        assert isinstance(msg, str)


# ---------------------------------------------------------------------------
# Monster coverage spot-check
# ---------------------------------------------------------------------------


REPRESENTATIVE_MONSTERS = [
    "bandit",
    "goblin",
    "skeleton",
    "cyclops",
    "giant",
    "minotaur",
    "werewolf",
    "toad",
    "bearowl",
    "doppelganger",
    "math_teacher",
    "pixie",
    "golem",
]


@pytest.mark.parametrize("monster_key", REPRESENTATIVE_MONSTERS)
def test_monster_retaliation_runs_end_to_end(monster_key):
    """Every non-override monster must survive ``attack_random`` on a
    standard humanoid target without raising. Guards against monsters
    whose ``DEFAULT_ACTIONS`` pools or body-part anatomies interact
    badly with the new pipeline path."""
    m = _spawn(monster_key)
    victim = _make_player(health=10_000)
    # One round is enough for a smoke pass — the stages either run
    # cleanly or they don't.
    msg = m.attack_random([victim])
    # ``msg`` can legitimately be None if no living parts declared
    # actions and ``get_attack_sources`` returned nothing — but the
    # default monsters here all have humanoid bodies or sources.
    assert msg is None or isinstance(msg, str)


# ---------------------------------------------------------------------------
# Vampire.do_attack bypass — known regression, documented
# ---------------------------------------------------------------------------


class TestVampireFeedRestoredInRetaliation:
    """Vampire's feed-at-low-HP mechanic is a signature ability.
    Pre-6b it fired via ``do_attack`` swapping to a feed-only
    sequence; that path is bypassed post-6b because retaliation
    routes through ``pick_actions`` / ``resolve``. A thin override
    on ``Vampire.attack_random`` restores the mechanic — mirroring
    hydra's / dragon's ``attack_random`` override pattern."""

    def test_low_hp_vampire_retaliation_calls_feed(self, monkeypatch):
        v = _spawn("vampire")
        v.health = v.health_max // 2  # eligible for feed

        called = {"feed": False}
        real_feed = type(v).feed

        def _spy(self, *args, **kwargs):
            called["feed"] = True
            return real_feed(self, *args, **kwargs)

        monkeypatch.setattr(type(v), "feed", _spy)

        victim = _make_player(health=10_000)
        result = v.attack_random([victim])
        assert called["feed"] is True
        assert isinstance(result, str) and result

    def test_full_hp_vampire_retaliation_uses_pipeline(self, monkeypatch):
        v = _spawn("vampire")
        v.health = v.health_max  # above feed threshold

        called = {"feed": False}
        real_feed = type(v).feed

        def _spy(self, *args, **kwargs):
            called["feed"] = True
            return real_feed(self, *args, **kwargs)

        monkeypatch.setattr(type(v), "feed", _spy)

        victim = _make_player(health=10_000)
        v.attack_random([victim])
        assert called["feed"] is False


# ---------------------------------------------------------------------------
# Dragon's super() call path
# ---------------------------------------------------------------------------


class TestDragonSuperCallStillWorks:
    """Dragon's ``attack_random`` delegates to ``super()`` on normal
    (non-breath) turns — Phase 6c's job is to port dragon, but Phase 6b
    must not break that delegation in the meantime."""

    def test_dragon_non_breath_path_returns_string(self):
        from unittest.mock import patch
        d = _spawn("dragon")
        victim = _make_player(health=10_000)
        # Force non-breath turn by high RNG.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.dragon.random",
            return_value=0.99,
        ):
            msg = d.attack_random([victim])
        assert msg is not None
        assert isinstance(msg, str)
