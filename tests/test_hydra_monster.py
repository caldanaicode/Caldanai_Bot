"""Tests for the Phase 1.C item 3.2 ``Hydra`` monster plugin.

The hydra is the proving-ground monster that exercises the entire Phase
1.A + 1.B foundation end-to-end. It introduces the first monster with:

- Body parts composed at ``__init__`` time (torso + legs + tail +
  ``STARTING_HEADS`` live non-critical ``HeadPlugin`` instances).
- Turn-based regrowth handled in ``on_combat_round`` (2 new heads per
  destroyed head, capped by ``MAX_HEADS``).
- Multi-source attacks: ``get_attack_sources`` returns one
  ``NaturalAttackSource`` per live hydra head, giving the hydra a
  single-target multi-hit pattern (dual-wield-style).
- **Two independent death conditions**: critical-torso destruction
  (via the standard ``Creature.apply_damage`` critical-part-destroyed
  routing) AND all-heads-destroyed (checked in ``on_combat_round``
  before regrowth would otherwise save the hydra).

Scope is strictly **baseline**. Variants, multi-target attacks, per-head
damage types, and breath attacks are queued as Q.2-Q.7 in the design
doc and are out of scope for this test module.

Deterministic setup
-------------------

The hydra's baseline stats use dice strings (``20d10`` health, ``1d6``
attack, etc.). Tests that need deterministic HP override
``hydra.health_max`` / ``hydra.health`` directly after construction.
Tests that exercise ``apply_damage`` against body parts use explicit
``health_max`` overrides on the parts as well, so that damage routing
lands deterministically.
"""

import pytest

from caldanai import PluginManager
from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import Reach
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.hydra import Hydra, VARIANTS
from caldanai.lib.rpg.inventory import Inventory


def _default_variant():
    """Return the default 'hydra' variant dict from the VARIANTS table."""
    return next(v for v in VARIANTS if v["name"] == "hydra")


def _make_default_hydra():
    """Construct a Hydra forced to the default 'hydra' variant (3 heads).

    Temporarily replaces VARIANTS with a single-element list so that
    ``random.choices`` always picks the default variant.
    """
    import caldanai.lib.rpg.creatures.monsters.hydra as _mod
    original = _mod.VARIANTS
    default = _default_variant()
    _mod.VARIANTS = [default]
    try:
        return Hydra()
    finally:
        _mod.VARIANTS = original


def _starting_heads():
    """Return the starting head count of the default 'hydra' variant."""
    return _default_variant()["starting_heads"]


def _make_hydra_head(name="head", **kwargs):
    """Create a hydra-style head: non-critical HeadPlugin with hydra exposure."""
    return BodyPart.make(
        "head", is_critical=False, name=name,
        exposure={Reach.MELEE: 0.4, Reach.REACH: 0.5,
                  Reach.THROWN: 0.7, Reach.RANGED: 1.0},
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _load_plugins():
    """Ensure monster and body-part plugin discovery has run before
    every test in this module. The hydra composes body parts via
    ``BodyPart.make`` and is itself a monster plugin, so both registries
    must be populated."""
    from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin

    BodyPartPlugin.load_plugins()
    MonsterPlugin.load_plugins()
    if not Inventory.ITEMS:
        Inventory.discover_items()
    yield


# ---------------------------------------------------------------------------
# Plugin discovery & factory
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_hydra_is_discoverable_via_loaded_plugins(self):
        """``Hydra`` must appear in the monster plugin registry so that
        ``MonsterPlugin.get_random_monster`` can select it."""
        assert Hydra in PluginManager.LOADED_PLUGINS[MonsterPlugin]

    def test_hydra_instantiates_without_error(self):
        h = Hydra()
        assert isinstance(h, Hydra)
        assert isinstance(h, MonsterPlugin)

    def test_max_heads_is_ten(self):
        """Class-level pin: baseline hydra can regrow up to 10 live heads."""
        assert Hydra.MAX_HEADS == 10

    def test_starting_heads_is_three(self):
        """The default 'hydra' variant starts with 3 heads — below the cap
        so that regrowth is visible and dramatic over the first few rounds."""
        assert _starting_heads() == 3


# ---------------------------------------------------------------------------
# Initial composition
# ---------------------------------------------------------------------------


class TestInitialComposition:
    def test_fresh_hydra_has_starting_heads_live_head_instances(self):
        h = _make_default_hydra()
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        assert len(live_heads) == _starting_heads()

    def test_live_head_count_is_not_max_heads(self):
        """Pin that STARTING_HEADS != MAX_HEADS so that regrowth is
        visible in early-game combat."""
        h = _make_default_hydra()
        live_heads = [
            p for p in h.body_parts if isinstance(p, HeadPlugin) and not p.is_critical
        ]
        assert len(live_heads) < Hydra.MAX_HEADS

    def test_has_critical_torso(self):
        h = Hydra()
        torsos = [p for p in h.body_parts if isinstance(p, TorsoPlugin)]
        assert len(torsos) == 1
        assert torsos[0].is_critical is True

    def test_has_four_legs(self):
        h = Hydra()
        legs = [p for p in h.body_parts if isinstance(p, LegPlugin)]
        assert len(legs) == 4

    def test_has_one_tail(self):
        h = Hydra()
        tails = [p for p in h.body_parts if isinstance(p, TailPlugin)]
        assert len(tails) == 1

    def test_total_body_part_count_matches_composition(self):
        """1 torso + 4 legs + 1 tail + starting_heads heads."""
        h = _make_default_hydra()
        assert len(h.body_parts) == 1 + 4 + 1 + _starting_heads()


# ---------------------------------------------------------------------------
# get_attack_sources — one source per live head
# ---------------------------------------------------------------------------


class TestGetAttackSources:
    def test_returns_one_source_per_live_head(self):
        h = _make_default_hydra()
        sources = h.get_attack_sources()
        assert len(sources) == _starting_heads()

    def test_each_source_is_a_natural_attack_source(self):
        h = Hydra()
        sources = h.get_attack_sources()
        for source in sources:
            assert isinstance(source, NaturalAttackSource)

    def test_each_source_uses_class_attack_dice_string(self):
        """Each head's attack source mirrors the hydra's ``atk`` dice.
        Pins that per-head damage-type variation is NOT implemented here
        (queued as Q.4)."""
        h = Hydra()
        for source in h.get_attack_sources():
            # NaturalAttackSource stores the dice string on ``_atk``.
            assert source._atk == h.attack

    def test_each_source_label_contains_head_display_name(self):
        """Combat display needs to distinguish heads. Each source label
        includes the head's display name (``"head 1"`` etc.)."""
        h = _make_default_hydra()
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        labels = [s.label for s in h.get_attack_sources()]
        for head in live_heads:
            assert any(
                head.display_name in label for label in labels
            ), f"No attack source label mentions {head.display_name!r}: {labels}"

    def test_destroying_one_head_drops_attack_source_count(self):
        h = _make_default_hydra()
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        # Destroy one head by zeroing its HP directly.
        live_heads[0].health = 0
        assert live_heads[0].is_destroyed()

        sources = h.get_attack_sources()
        assert len(sources) == _starting_heads() - 1

    def test_headless_returns_single_defensive_flailing_source(self):
        """Defensive case: if all heads are destroyed before
        ``on_combat_round`` has a chance to fire the last-head death
        check, ``get_attack_sources`` must not raise. It returns a
        single ``NaturalAttackSource`` labeled with ``"headless
        flailing"``."""
        h = Hydra()
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0

        sources = h.get_attack_sources()
        assert len(sources) == 1
        assert isinstance(sources[0], NaturalAttackSource)
        assert "headless flailing" in sources[0].label.lower()


# ---------------------------------------------------------------------------
# on_combat_round — regrowth + last-head death
# ---------------------------------------------------------------------------


class TestOnCombatRoundNoOp:
    def test_no_damage_no_destroyed_heads_returns_empty_string(self):
        """Fresh hydra with no damage dealt. Nothing to regrow, nothing
        to say."""
        h = Hydra()
        msg = h.on_combat_round({})
        assert msg == ""

    def test_no_damage_body_parts_unchanged(self):
        h = Hydra()
        before_len = len(h.body_parts)
        before_ids = [id(p) for p in h.body_parts]
        h.on_combat_round({})
        assert len(h.body_parts) == before_len
        assert [id(p) for p in h.body_parts] == before_ids


class TestOnCombatRoundRegrowth:
    def test_one_destroyed_head_spawns_two_new_heads(self):
        h = _make_default_hydra()
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        live_heads[0].health = 0

        msg = h.on_combat_round({})

        live_after = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        # Started with STARTING_HEADS, killed 1, regrew 2 -> +1 net.
        assert len(live_after) == _starting_heads() - 1 + 2
        assert isinstance(msg, str)
        assert msg != ""

    def test_regrowth_removes_destroyed_head_from_body_parts(self):
        """After regrowth, destroyed heads are removed from body_parts
        so they don't contribute debuffs or appear in the targeting pool."""
        h = Hydra()
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        victim = live_heads[0]
        victim.health = 0

        h.on_combat_round({})

        assert victim.is_destroyed()
        # Destroyed head removed from the list.
        assert victim not in h.body_parts

    def test_regrowth_does_not_change_hydra_health(self):
        """Regrowth spawns heads, it doesn't heal the body. A hydra that
        was at half HP before the round should still be at half HP after
        regrowth."""
        h = Hydra()
        h.health_max = 50
        h.health = 25

        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        live_heads[0].health = 0

        h.on_combat_round({})

        assert h.health == 25

    def test_regrowth_respects_max_heads_cap(self):
        """Setup: 9 live heads + 1 destroyed = ``MAX_HEADS - 1`` live.
        Regrowth would want 2 new heads but only has 1 slot available.
        Result: 1 spawned (not 2), total live = 10 = ``MAX_HEADS``."""
        h = Hydra()
        # Reset body parts: keep torso/legs/tail, wipe all existing heads.
        non_heads = [
            p for p in h.body_parts if not (isinstance(p, HeadPlugin) and not p.is_critical)
        ]
        h.body_parts = list(non_heads)
        # Add exactly 9 live heads + 1 destroyed head.
        for i in range(Hydra.MAX_HEADS - 1):
            h.body_parts.append(
                _make_hydra_head(name=f"live head {i + 1}")
            )
        dead = _make_hydra_head(name="dead head")
        dead.health = 0
        h.body_parts.append(dead)

        assert sum(
            1 for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ) == Hydra.MAX_HEADS - 1

        h.on_combat_round({})

        live_after = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        assert len(live_after) == Hydra.MAX_HEADS

    def test_regrowth_at_exact_cap_spawns_nothing(self):
        """10 live + 1 destroyed. Regrowth has zero available slots.
        Result: no new heads spawned, flavor string mentions ``"biological limit"``."""
        h = Hydra()
        non_heads = [
            p for p in h.body_parts if not (isinstance(p, HeadPlugin) and not p.is_critical)
        ]
        h.body_parts = list(non_heads)
        for i in range(Hydra.MAX_HEADS):
            h.body_parts.append(
                _make_hydra_head(name=f"live head {i + 1}")
            )
        dead = _make_hydra_head(name="dead head")
        dead.health = 0
        h.body_parts.append(dead)

        msg = h.on_combat_round({})

        # No new heads spawned, and the destroyed head was cleaned up.
        live_after = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        assert len(live_after) == Hydra.MAX_HEADS
        # Destroyed head removed from body_parts.
        destroyed_after = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and p.is_destroyed()
        ]
        assert len(destroyed_after) == 0
        assert "biological limit" in msg.lower()


class TestOnCombatRoundLastHeadDeath:
    """The load-bearing win-condition test — the whole point of the
    turn-based regrowth mechanic is that the player CAN win by killing
    every live head in a single round. If regrowth fired before the
    death check, the player could never wipe out all heads."""

    def test_all_heads_destroyed_sets_health_to_zero(self):
        h = Hydra()
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0

        h.on_combat_round({})

        assert h.health == 0

    def test_all_heads_destroyed_returns_last_head_flavor(self):
        h = Hydra()
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0

        msg = h.on_combat_round({})

        assert isinstance(msg, str)
        assert "last head" in msg.lower()

    def test_all_heads_destroyed_does_not_spawn_new_heads(self):
        """Death check must fire BEFORE regrowth — otherwise regrowth
        would save the hydra and the win condition would be
        unreachable."""
        h = Hydra()
        head_count_before = sum(
            1 for p in h.body_parts if isinstance(p, HeadPlugin) and not p.is_critical
        )
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0

        h.on_combat_round({})

        head_count_after = sum(
            1 for p in h.body_parts if isinstance(p, HeadPlugin) and not p.is_critical
        )
        assert head_count_after == head_count_before

    def test_death_check_fires_before_regrowth_ordering_pin(self):
        """Ordering pin: destroying all live heads and calling
        ``on_combat_round`` must set ``self.health = 0``. If the
        implementation reversed the order (regrow first, then death
        check), the regrown heads would make the creature 'healthy'
        and the death condition would never be reached."""
        h = Hydra()
        h.health_max = 100
        h.health = 100
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health = 0

        h.on_combat_round({})

        # If regrowth ran first, the hydra would have live heads and
        # the death check wouldn't fire. The fact that health == 0 pins
        # the ordering.
        assert h.health == 0


# ---------------------------------------------------------------------------
# End-to-end via apply_damage
# ---------------------------------------------------------------------------


class TestEndToEndApplyDamage:
    def _hydra_with_deterministic_hp(self):
        h = _make_default_hydra()
        h.health_max = 500
        h.health = 500
        # Give each hydra head a known, manageable max HP so apply_damage
        # routing is deterministic.
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health_max = 10
                p.health = 10
        return h

    def test_apply_damage_destroys_head_then_regrowth_spawns_two(self):
        h = self._hydra_with_deterministic_hp()
        victim = next(
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        )

        h.apply_damage(50, target_part=victim)
        assert victim.is_destroyed()
        # Hydra is not dead — the victim is non-critical and siblings
        # still live.
        assert h.health > 0

        h.on_combat_round({})

        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        assert len(live_heads) == _starting_heads() - 1 + 2

    def test_apply_damage_destroys_all_then_on_combat_round_kills_hydra(self):
        """Second-pass: destroy all four heads individually via
        ``apply_damage``, then call ``on_combat_round`` — the hydra's
        all-heads-destroyed death condition fires."""
        h = self._hydra_with_deterministic_hp()

        # First, destroy one and regrow to 4 heads.
        first_victim = next(
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        )
        h.apply_damage(50, target_part=first_victim)
        h.on_combat_round({})

        # Ensure regrown heads also have deterministic HP for the next pass.
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed():
                p.health_max = 10
                p.health = 10

        # Destroy all live heads one by one via apply_damage.
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        assert len(live_heads) == 4
        for head in live_heads:
            h.apply_damage(50, target_part=head)
            assert head.is_destroyed()

        # Hydra body took full collateral damage from each head hit
        # (Model D unified HP), but should still be alive — the death
        # condition is triggered only by on_combat_round (not by
        # non-critical part destruction).
        # (We sized health_max to 500 to prevent overkill.)
        h.on_combat_round({})

        assert h.health == 0


# ---------------------------------------------------------------------------
# Critical-torso dual-win-condition pin
# ---------------------------------------------------------------------------


class TestCriticalTorsoDualWinCondition:
    """The hydra has TWO independent death conditions:

    1. Critical torso destroyed (via standard ``Creature.apply_damage``
       critical-part routing from Phase 1 item 1.9).
    2. All live heads destroyed (via ``Hydra.on_combat_round``).

    These are independent lethals per the user's clarification about
    critical parts. A torso attack can end the fight just as well as a
    head-chopping strategy.
    """

    def test_torso_is_critical(self):
        h = Hydra()
        torso = next(p for p in h.body_parts if isinstance(p, TorsoPlugin))
        assert torso.is_critical is True

    def test_destroying_torso_kills_hydra_via_apply_damage(self):
        """End-to-end pin: damage routed to the torso through
        ``Creature.apply_damage`` must trigger the critical-part death
        routing (``self.health = 0``) regardless of how many live heads
        remain. This pins that the hydra's head-based win condition
        does NOT shadow the torso's critical-part path."""
        h = _make_default_hydra()
        h.health_max = 500
        h.health = 500
        torso = next(p for p in h.body_parts if isinstance(p, TorsoPlugin))
        torso.health_max = 10
        torso.health = 10

        h.apply_damage(50, target_part=torso)

        assert torso.is_destroyed()
        assert h.health == 0
        # Live heads still present — the torso path is the only reason
        # the hydra is dead.
        live_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical and not p.is_destroyed()
        ]
        assert len(live_heads) == _starting_heads()  # torso kill, heads untouched


# ---------------------------------------------------------------------------
# Destroyed head cleanup — migrated from test_hydra_head_plugin.py
# ---------------------------------------------------------------------------


class TestDestroyedHeadCleanup:
    """After ``on_combat_round``, destroyed heads are removed from
    ``body_parts`` and therefore don't contribute debuffs or appear
    in the targeting pool."""

    def test_destroyed_head_removed_after_regrowth(self):
        h = Hydra()
        heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
        ]
        heads[0].health = 0

        h.on_combat_round({})

        destroyed = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
            and p.is_destroyed()
        ]
        assert len(destroyed) == 0

    def test_destroyed_head_does_not_contribute_debuffs(self):
        """After regrowth, only live heads remain in body_parts,
        so destroyed heads cannot contribute stat debuffs."""
        from caldanai.lib.rpg.helpers.enums import Stat

        h = Hydra()
        h.health_max = 500
        h.health = 500
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                p.health_max = 10
                p.health = 10

        # Destroy one head.
        victim = next(
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
        )
        victim.health = 0

        h.on_combat_round({})

        # No destroyed heads in body_parts means no USELESS-row debuffs.
        for p in h.body_parts:
            if isinstance(p, HeadPlugin) and not p.is_critical:
                assert not p.is_destroyed()

    def test_destroyed_heads_not_targetable_after_cleanup(self):
        """Destroyed heads should not appear in body_parts after
        on_combat_round, making them untargetable."""
        h = Hydra()
        heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
        ]
        heads[0].health = 0

        h.on_combat_round({})

        all_heads = [
            p for p in h.body_parts
            if isinstance(p, HeadPlugin) and not p.is_critical
        ]
        for head in all_heads:
            assert not head.is_destroyed()


# ---------------------------------------------------------------------------
# Loot table — pins existing-item references only
# ---------------------------------------------------------------------------


class TestLoot:
    def test_loot_has_at_least_three_entries(self):
        h = Hydra()
        assert len(h.loot) >= 3

    def test_every_loot_key_resolves_in_inventory(self):
        """Every loot key must exist in ``Inventory.ITEMS`` — this pins
        that we didn't reference item plugins that don't exist (the user
        explicitly said to use existing items only; new hydra-themed
        items are deferred until after this phase)."""
        h = Hydra()
        for key in h.loot.keys():
            assert key in Inventory.ITEMS, (
                f"Hydra loot references non-existent item {key!r}"
            )

    def test_get_loot_does_not_warn_on_missing_items(self):
        """Exercise the loot factory end-to-end by calling
        ``get_loot`` a few times. It should not raise and every item
        (when rolled) should be a real ``Item``."""
        from caldanai.lib.rpg.inventory import Item

        h = Hydra()
        # Run a few times — frequencies are <1.0 so we may get empty
        # lists, but we should never see a crash.
        for _ in range(10):
            items = h.get_loot()
            for it in items:
                assert isinstance(it, Item)
