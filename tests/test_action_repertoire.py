"""Tests for ``MonsterPlugin.ACTION_REPERTOIRE`` — the renamed /
reshaped Layer 2 registry — and the callable-native entry convention
(``is_available`` / ``get_dice`` / ``get_narrative``) established in
Phase 3.

Phase 3 ships no concrete monster overrides, so these tests use
synthetic subclasses to exercise both MODIFY (matching part-default
key) and ADD (non-matching key) semantics plus every callable path.
"""

import random
from typing import Dict, Optional
from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.combat.attack_source import AttackSource
from caldanai.lib.rpg.combat.block import Assignment
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import DamageTypes, Reach, Size


class _FxHead(BodyPartPlugin):
    name = "head"
    health_max = 20
    is_critical = False
    DEFAULT_ACTIONS = {
        "bite": {
            "cost": 1,
            "weight": 1.0,
            "dice": "1d4",
            "dmg_type": DamageTypes.PIERCING,
            "reach": Reach.MELEE,
            "label": "bite",
            "narrative": ["@1D bites @2."],
        },
    }


class _FxArm(BodyPartPlugin):
    name = "arm"
    health_max = 15
    is_critical = False
    DEFAULT_ACTIONS = {
        "punch": {
            "cost": 1,
            "weight": 1.0,
            "dice": "1d3",
            "dmg_type": DamageTypes.BLUDGEONING,
            "reach": Reach.MELEE,
            "label": "punch",
            "narrative": ["@1D punches @2."],
        },
    }


def _make_monster(cls=None, budget: int = 2) -> MonsterPlugin:
    if cls is None:
        cls = type("_Mon", (MonsterPlugin,), {"ACTION_BUDGET": budget})
    monster = cls(
        name="synthetic", atk="1d4", defense=2, dodge=3,
        health_max=20, pronouns="she, her, hers, her",
    )
    monster.body_parts = [_FxHead(name="head"), _FxArm(name="arm.left")]
    return monster


class TestRegistryDefault:
    def test_monsterplugin_ships_empty_action_repertoire(self):
        """Phase 3 rename must not populate the registry on any
        concrete monster path — empty dict is the contract."""
        assert MonsterPlugin.ACTION_REPERTOIRE == {}

    def test_legacy_name_is_gone(self):
        """``ACTION_OVERRIDES`` must not be exposed anywhere — renamed
        outright so any stale references fail loudly."""
        assert not hasattr(MonsterPlugin, "ACTION_OVERRIDES")


class TestRepertoireModifySemantics:
    """When a repertoire entry's key matches a part-default action,
    fields from the repertoire overlay the default."""

    def test_override_dice_and_label(self):
        class Wolf(MonsterPlugin):
            ACTION_BUDGET = 2
            ACTION_REPERTOIRE = {
                "head": {
                    "bite": {"dice": "2d6", "label": "savage bite"},
                },
            }

        wolf = _make_monster(Wolf)
        random.seed(0)
        # Loop through seeds until bite gets picked (weighted random).
        for seed in range(20):
            random.seed(seed)
            actions = wolf.pick_actions()
            bite_src = next(
                (s for s in actions if s.damage_type is DamageTypes.PIERCING),
                None,
            )
            if bite_src is not None:
                assert bite_src.label == "savage bite"
                return
        pytest.fail("never selected the bite action in 20 seeds")

    def test_override_preserves_unmentioned_fields(self):
        class Wolf(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {"bite": {"label": "mean bite"}},
            }

        wolf = _make_monster(Wolf)
        pools = wolf._collect_part_action_pools()
        bite = dict(
            [p for p in pools if p[0].name == "head"][0][1]["bite"]
        )
        # Label overridden; other fields inherit from _FxHead default.
        assert bite["label"] == "mean bite"
        assert bite["dmg_type"] is DamageTypes.PIERCING
        assert bite["dice"] == "1d4"


class TestRepertoireAddSemantics:
    """Non-matching keys add brand-new actions that the part didn't
    declare — the minotaur-gore pattern."""

    def test_new_action_appears_in_pool(self):
        class Minotaur(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {
                    "gore": {
                        "cost": 1,
                        "weight": 5.0,
                        "dice": "2d6",
                        "dmg_type": DamageTypes.PIERCING,
                        "reach": Reach.MELEE,
                        "label": "gore",
                        "narrative": ["@1D gores @2."],
                    },
                },
            }

        minotaur = _make_monster(Minotaur)
        pools = minotaur._collect_part_action_pools()
        head_pool = [p for p in pools if p[0].name == "head"][0][1]
        assert set(head_pool.keys()) == {"bite", "gore"}
        assert head_pool["gore"]["label"] == "gore"


class TestIsAvailableCallable:
    """``is_available(actor, target)`` is consulted at ``pick_actions``
    time; falsy vetoes the entry from the pool."""

    def test_always_true_callable_still_allows_selection(self):
        class M(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {
                    "bite": {"is_available": lambda a, t: True},
                },
            }

        m = _make_monster(M)
        pools = m._collect_part_action_pools()
        head_pool = [p for p in pools if p[0].name == "head"][0][1]
        assert "bite" in head_pool

    def test_false_callable_drops_entry(self):
        class M(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {
                    # Veto the inherited bite.
                    "bite": {"is_available": lambda a, t: False},
                },
            }

        m = _make_monster(M)
        pools = m._collect_part_action_pools()
        head_parts = [p for p in pools if p[0].name == "head"]
        # Head's entire pool was just bite; with bite vetoed the part
        # drops out.
        assert head_parts == []

    def test_exception_in_callable_drops_entry_safely(self):
        def _raises(actor, target):
            raise RuntimeError("boom")

        class M(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {"bite": {"is_available": _raises}},
            }

        m = _make_monster(M)
        pools = m._collect_part_action_pools()
        head_parts = [p for p in pools if p[0].name == "head"]
        assert head_parts == []

    def test_callable_is_invoked_with_actor_arg(self):
        seen = []

        def _capture(actor, target):
            seen.append((actor, target))
            return True

        class M(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {"bite": {"is_available": _capture}},
            }

        m = _make_monster(M)
        m._collect_part_action_pools()
        assert seen
        actor, target = seen[0]
        assert actor is m
        assert target is None  # action-pick stage has no target yet


class TestGetDiceCallable:
    """``get_dice(actor, target)`` overrides the static ``dice`` field
    when present."""

    def test_callable_overrides_static_dice(self):
        class Rage(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {
                    "bite": {
                        "dice": "1d4",
                        "get_dice": lambda a, t: "9d9",
                    },
                },
            }

        m = _make_monster(Rage)
        for seed in range(20):
            random.seed(seed)
            actions = m.pick_actions()
            bite_src = next(
                (s for s in actions if s.damage_type is DamageTypes.PIERCING),
                None,
            )
            if bite_src is not None:
                # The source's ``attack`` dice string should be what the
                # callable returned, not the static field.
                assert bite_src._atk == "9d9"
                return
        pytest.fail("bite never selected; could not verify get_dice")

    def test_missing_dice_falls_back_to_size_scaled(self):
        """No static ``dice``, no callable — should size-scale via
        :func:`size_scaled_dice` using the creature's Size."""
        class TinyGuy(MonsterPlugin):
            pass

        m = _make_monster(TinyGuy)
        m.size = Size.TINY
        # Strip the static dice on the fixture's bite entry so the
        # fallback path triggers.
        for part in m.body_parts:
            for action in (getattr(part, "DEFAULT_ACTIONS", {}) or {}).values():
                action.pop("dice", None)
        for seed in range(30):
            random.seed(seed)
            actions = m.pick_actions()
            if actions:
                # Both bite (TINY=1d2) and punch (TINY=1d2) should
                # be 1d2 per the action_dice tier table.
                for src in actions:
                    assert src._atk.startswith("1d")
                return
        pytest.fail("no actions selected across 30 seeds")

    def test_callable_exception_falls_back_to_static(self):
        def _raises(actor, target):
            raise RuntimeError("boom")

        class M(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {
                    "bite": {"dice": "7d7", "get_dice": _raises},
                },
            }

        m = _make_monster(M)
        for seed in range(20):
            random.seed(seed)
            actions = m.pick_actions()
            bite_src = next(
                (s for s in actions if s.damage_type is DamageTypes.PIERCING),
                None,
            )
            if bite_src is not None:
                assert bite_src._atk == "7d7"
                return
        pytest.fail("bite never selected")


class TestGetNarrativeCallable:
    """``get_narrative(actor, target)`` overrides the static
    ``narrative`` list when present at render time."""

    def test_callable_overrides_static_pool(self):
        pool_dynamic = ["@1D performs a dynamic move on @2."]

        class Mimic(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {
                    "bite": {"get_narrative": lambda a, t: pool_dynamic},
                },
            }

        mimic = _make_monster(Mimic)
        victim = Creature(
            name="caels", atk="1d4", defense=0, dodge=0,
            health_max=30, pronouns="he, him, his, his",
        )
        victim.uses_article = False
        for seed in range(30):
            random.seed(seed)
            actions = mimic.pick_actions()
            bite = next(
                (s for s in actions if s.damage_type is DamageTypes.PIERCING),
                None,
            )
            if bite is None:
                continue
            assignments = [Assignment(source=bite, target=victim)]
            out = mimic.narrate_attempt(assignments)
            assert out is not None
            assert "dynamic" in out.lower()
            return
        pytest.fail("bite never selected; could not verify get_narrative")

    def test_missing_get_narrative_uses_static_pool(self):
        class Plain(MonsterPlugin):
            pass

        m = _make_monster(Plain)
        victim = Creature(
            name="caels", atk="1d4", defense=0, dodge=0,
            health_max=30, pronouns="he, him, his, his",
        )
        victim.uses_article = False
        random.seed(2)
        actions = m.pick_actions()
        assignments = [Assignment(source=a, target=victim) for a in actions]
        out = m.narrate_attempt(assignments)
        assert out is not None
        # Static pools for _FxHead / _FxArm include the verb stems.
        assert any(s in out.lower() for s in ("bite", "punch"))

    def test_callable_invoked_with_actor_and_target(self):
        seen = []

        def _capture(actor, target):
            seen.append((actor, target))
            return ["@1D attempts something on @2."]

        class M(MonsterPlugin):
            ACTION_REPERTOIRE = {
                "head": {"bite": {"get_narrative": _capture}},
            }

        m = _make_monster(M)
        victim = Creature(
            name="caels", atk="1d4", defense=0, dodge=0,
            health_max=30, pronouns="he, him, his, his",
        )
        victim.uses_article = False
        for seed in range(30):
            random.seed(seed)
            actions = m.pick_actions()
            bite = next(
                (s for s in actions if s.damage_type is DamageTypes.PIERCING),
                None,
            )
            if bite is None:
                continue
            assignments = [Assignment(source=bite, target=victim)]
            m.narrate_attempt(assignments)
            break
        assert seen
        actor, target = seen[0]
        assert actor is m
        assert target is victim


class TestPartDefaultsStillWorkWithoutRepertoire:
    """Creature with no ``ACTION_REPERTOIRE`` still picks from pure
    part-default actions — the "naked goblin" Q1 promise."""

    def test_pure_part_defaults_produce_sources(self):
        m = _make_monster()
        random.seed(1)
        actions = m.pick_actions()
        assert actions
        for src in actions:
            assert isinstance(src, AttackSource)
