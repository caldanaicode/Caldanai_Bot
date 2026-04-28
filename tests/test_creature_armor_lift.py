"""Tests for the 2026-04-28 armor / dodge / loadout lift from
``Player`` and ``MonsterPlugin`` down to the base :class:`Creature`.

The lift made monsters and players use the same defense / dodge /
loadout pipeline. These tests pin the symmetry invariants that
motivated the work and the construction-order regression that the
``_emergent_defense`` split protects against.

Cross-references:
- ``project_armor_rework_for_phase_c.md`` — the per-part defense
  context the lift simplified.
- ``feedback_subagent_review_pattern.md`` — this file is part of
  the implementer's deliverable; the parent agent runs the
  reviewer pass after these land.
"""

from contextlib import ExitStack, contextmanager
from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures import (
    Creature,
    effective_defense_breakdown,
    effective_defense_for_part,
)
from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
from caldanai.lib.rpg.creatures.monsters.hydra import Hydra
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.helpers.enums import DamageTypes
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
MonsterPlugin.load_plugins()
Inventory.discover_items()


@contextmanager
def _patch_random(return_value):
    """Patch ``random()`` at BOTH modules monster code reaches for
    it. See the shared helper note in ``test_monster_salvage.py`` —
    duplicated here so this file stays self-contained."""
    with ExitStack() as stack:
        stack.enter_context(patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=return_value,
        ))
        stack.enter_context(patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=return_value,
        ))
        yield


# ---------------------------------------------------------------------------
# Construction-order regression: SPAWN_LOADOUT must NOT inflate per-part HP
# ---------------------------------------------------------------------------


class TestConstructionOrderRegression:
    """Before the lift, ``_scale_part_hp`` read ``self.get_defense()``
    — fine when monsters didn't include worn armor in that pool. The
    lift folded armor into ``get_defense()`` to symmetrize with
    Player. ``_scale_part_hp`` switched to ``_emergent_defense()``
    so a lucky spawn-loadout roll doesn't pump every body part's HP
    upward. These tests pin that contract for bandit (which has a
    SPAWN_LOADOUT) and hydra regrowth (which calls the same scaling
    helper after the fight starts)."""

    def test_bandit_part_hp_independent_of_loadout(self):
        """Per-part ``health_max`` for a fully-equipped bandit (every
        spawn roll succeeds) matches a fully-bare bandit (every spawn
        roll fails). The scaling factor is intrinsic resilience, not
        the luck of the loadout dice — so ``_scale_part_hp`` reads
        ``_emergent_defense()`` on both."""
        # Force the same defense roll on both bandits so we're
        # comparing equal-stat instances. Without this the d12 roll
        # for ``self.defense`` differs and the comparison is muddy.
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=8,
        ):
            with _patch_random(0.0):
                fully_armored = Bandit()
            with _patch_random(1.0):
                bare = Bandit()

        # Sanity: armored bandit really has worn pieces; bare doesn't.
        armored_count = sum(
            1
            for part in fully_armored.body_parts
            for v in (getattr(part, "placements", None) or {}).values()
            if v is not None
        )
        bare_count = sum(
            1
            for part in bare.body_parts
            for v in (getattr(part, "placements", None) or {}).values()
            if v is not None
        )
        assert armored_count > 0, "armored bandit should carry pieces"
        assert bare_count == 0, "bare bandit should carry nothing"

        # Per-part health_max walks the SAME between the two — the
        # scaling factor is intrinsic to the creature, not its gear.
        armored_by_name = {p.name: p.health_max for p in fully_armored.body_parts}
        bare_by_name = {p.name: p.health_max for p in bare.body_parts}
        assert armored_by_name == bare_by_name

    def test_hydra_regrowth_uses_emergent_defense(self):
        """Hydras regrow heads via ``_grow_head_subtree`` →
        ``_make_head(scale=True)`` → ``_compute_scaled_part_hp``. The
        scaling argument now reads ``_emergent_defense()`` so a
        future hydra-with-armor (or a hydra mid-fight whose worn
        armor changed for any reason) gets consistent regrown-head
        HP.

        Hydras don't wear armor today, so this test pins the
        contract by spying on the helper at its source module
        (the hydra path imports it lazily)."""
        h = Hydra()
        captured: list = []

        from caldanai.lib.rpg import creatures as _cmod

        real_helper = _cmod._compute_scaled_part_hp

        def spy_helper(part, body_hp, size, defense):
            captured.append(defense)
            return real_helper(part, body_hp, size, defense)

        with patch(
            "caldanai.lib.rpg.creatures._compute_scaled_part_hp",
            side_effect=spy_helper,
        ):
            head = h._grow_head_subtree(DamageTypes.SLASHING)

        assert captured, "expected helper to be invoked during regrowth"
        # The captured value must equal ``_emergent_defense()`` —
        # NOT ``get_defense()``. They're equal in practice on a
        # bare hydra, but we pin the source-of-truth contract.
        assert captured[0] == h._emergent_defense()


# ---------------------------------------------------------------------------
# Player-monster armor symmetry: same item, same +N, both directions
# ---------------------------------------------------------------------------


class TestArmorSymmetry:
    """The whole point of the lift: monsters and players use one
    pipeline. A defense-bonus piece equipped on either kind of
    creature bumps ``get_defense()`` by the same amount."""

    def test_goblin_get_defense_includes_worn_bonus(self):
        """Equipping a piece with a known defense bonus bumps
        ``goblin.get_defense()`` by exactly that amount."""
        with _patch_random(1.0):
            g = Goblin()
        before = g.get_defense()

        # rough_cap @ ORDINARY has bonuses["defense"] = 1 (per the
        # plugin's authored bonuses, scaled by the ORDINARY 1.0
        # multiplier). We construct it explicitly so the bonus is
        # not stochastic from the spawn-loadout path.
        cap = Inventory.ITEMS["rough_cap"].from_plugin(
            "rough_cap", {"quality": "ORDINARY"},
        )
        bonus = cap.bonuses.get("defense", 0)
        assert bonus > 0, (
            "test setup: rough_cap should grant some defense bonus; "
            "if the plugin is rebalanced to 0, pick a different piece"
        )

        head = g.get_part("head")
        head.placements["worn"] = cap
        after = g.get_defense()
        assert after - before == bonus

    def test_player_get_defense_includes_same_worn_bonus(self):
        """Equipping the SAME class of piece on a player bumps
        ``player.get_defense()`` by the same amount — proves the
        unified pipeline."""
        p = Player(uid=1, gid=2, cid=3)
        before = p.get_defense()

        cap = Inventory.ITEMS["rough_cap"].from_plugin(
            "rough_cap", {"quality": "ORDINARY"},
        )
        bonus = cap.bonuses.get("defense", 0)
        assert bonus > 0

        head = p.get_part("head")
        head.placements["worn"] = cap
        after = p.get_defense()
        assert after - before == bonus

    def test_dragon_breath_pool_acknowledges_monster_armor(self):
        """An armored bandit's ``get_defense()`` exceeds an unarmored
        bandit's by exactly the worn-armor pool. Pre-lift this was
        monsters-don't-get-armor territory; post-lift it's the same
        accumulator the dragon breath / fall-damage / area-effect
        paths already read.

        Worn piece is added explicitly (not via the spawn-loadout
        roll) so the bonus is deterministic — scrap-set quality is
        stochastic at randint(50, 95) and a JUNK roll truncates the
        bonus to 0."""
        # Pin the d12 defense roll so the difference is deterministic.
        with patch(
            "caldanai.lib.rpg.creatures.Dice.quick_roll",
            return_value=8,
        ):
            with _patch_random(1.0):
                armored = Bandit()
                bare = Bandit()
        # Equip an explicit ORDINARY-quality piece so the bonus is
        # not stochastic.
        jerkin = Inventory.ITEMS["rough_jerkin"].from_plugin(
            "rough_jerkin", {"quality": "ORDINARY"},
        )
        worn_def = jerkin.bonuses.get("defense", 0)
        assert worn_def > 0
        torso = armored.get_part("torso")
        torso.placements["worn"] = jerkin

        # The armored bandit's creature-wide defense exceeds the
        # bare one by exactly the worn pool, all else equal.
        assert armored.get_defense() - bare.get_defense() == worn_def


# ---------------------------------------------------------------------------
# Per-part decomposition unchanged: emergence-only baseline
# ---------------------------------------------------------------------------


class TestPerPartDecompositionStable:
    """``effective_defense_for_part`` and
    ``effective_defense_breakdown`` switched their internal base from
    ``Creature.get_defense(creature)`` to ``creature._emergent_defense()``.
    On a player with worn armor, the values must NOT change: the
    Player-overridden ``get_defense`` previously layered armor on top,
    but the per-part path was already deliberately bypassing that
    layering ("Bypass Player.get_defense" comment) by calling the
    ``Creature.``-prefixed unbound method. The lift cleans up the
    bypass by giving the function a name (``_emergent_defense``)."""

    def test_armored_player_torso_breakdown_components(self):
        """Pin a known shape: a deterministic player wearing one
        defense-bonus piece on the torso has a specific
        ``base / part_bonus / armor / drain`` decomposition."""
        p = Player(uid=1, gid=2, cid=3, defense=10, dodge=10)
        torso = p.get_part("torso")
        # Equip a known piece; rough_jerkin contributes a torso
        # defense bonus.
        jerkin = Inventory.ITEMS["rough_jerkin"].from_plugin(
            "rough_jerkin", {"quality": "ORDINARY"},
        )
        torso.placements["worn"] = jerkin

        breakdown = effective_defense_breakdown(p, torso)
        # ``base`` is the emergence-only full-health value — for a
        # MEDIUM creature with ratio 1.0 and a clean roll, this is
        # ``int(self.defense * 1.0 * 1.0) + core_toughness == 10``.
        assert breakdown["base"] == p._emergent_defense()
        # ``armor`` is the local worn-piece bonus on torso.
        assert breakdown["armor"] == jerkin.bonuses.get("defense", 0)
        # ``drain`` is zero at full health.
        assert breakdown["drain"] == 0
        # ``total`` matches the function-of-record.
        assert breakdown["total"] == effective_defense_for_part(p, torso)

    def test_per_part_value_does_not_double_count_worn(self):
        """A torso with a +N defense piece worn on it shows ``+N``
        in the per-part column, not ``+2N``. The lift's split
        between ``_emergent_defense`` (per-part baseline) and
        ``get_defense`` (creature-wide) is the architectural fix
        for the double-count footgun."""
        p = Player(uid=1, gid=2, cid=3, defense=10, dodge=10)
        torso = p.get_part("torso")
        bare_total = effective_defense_for_part(p, torso)

        cap = Inventory.ITEMS["rough_cap"].from_plugin(
            "rough_cap", {"quality": "ORDINARY"},
        )
        bonus = cap.bonuses.get("defense", 0)
        head = p.get_part("head")
        head.placements["worn"] = cap

        # Putting a piece on the HEAD shouldn't change the TORSO's
        # per-part value — armor defense contributions are local.
        torso_after_head_armor = effective_defense_for_part(p, torso)
        assert torso_after_head_armor == bare_total

        # Putting a piece on the torso bumps the torso by exactly
        # the bonus, not double.
        torso_jerkin = Inventory.ITEMS["rough_jerkin"].from_plugin(
            "rough_jerkin", {"quality": "ORDINARY"},
        )
        torso_bonus = torso_jerkin.bonuses.get("defense", 0)
        torso.placements["worn"] = torso_jerkin
        torso_after_torso_armor = effective_defense_for_part(p, torso)
        assert torso_after_torso_armor - bare_total == torso_bonus


# ---------------------------------------------------------------------------
# get_armor_bonuses lifted; both monsters and players see the same accessor
# ---------------------------------------------------------------------------


class TestGetArmorBonusesOnCreature:
    """Lifted from ``Player`` to ``Creature``. Now monsters expose
    it too — useful for any consumer that wants "how much armor pool
    does this creature have right now?"."""

    def test_monster_get_armor_bonuses_aggregates_worn(self):
        # Force a fully-loadout bandit, then explicitly equip a
        # bracer at known ORDINARY quality so the aggregator has
        # something to sum. (The spawn-loadout pieces in the bandit
        # scrap set may roll defense bonuses that vary by
        # quality_range; this test only needs the SUM path to wire
        # cleanly, not the specific authored bonuses.)
        with _patch_random(1.0):
            b = Bandit()
        # Empty start.
        assert b.get_armor_bonuses("defense") == {} or \
            b.get_armor_bonuses("defense").get("defense", 0) == 0

        bracer = Inventory.ITEMS["patchwork_bracer"].from_plugin(
            "patchwork_bracer", {"quality": "ORDINARY"},
        )
        if bracer.bonuses.get("defense", 0) == 0:
            pytest.skip(
                "patchwork_bracer has no defense bonus at ORDINARY; "
                "test fixture needs a different piece"
            )
        arm = b.get_part("arm.left")
        arm.placements["worn.lower"] = bracer
        bonuses = b.get_armor_bonuses("defense")
        assert bonuses["defense"] == bracer.bonuses["defense"]

    def test_monster_get_armor_bonuses_filters_by_name(self):
        with _patch_random(0.0):
            b = Bandit()
        # ``names=()`` returns everything; passing a name returns
        # only that key (or empty if no piece grants it).
        all_bonuses = b.get_armor_bonuses()
        defense_only = b.get_armor_bonuses("defense")
        assert "defense" in all_bonuses or all_bonuses == {}
        assert set(defense_only.keys()) <= {"defense"}
