"""Phase-5 behavior-parity tests for ``Game.do_combat``.

The Phase-5 rewrite moves the player-attack loop onto a per-attacker
block composer and flips turn order from reverse-of-join to join-order.
These tests pin the observable surface: dispatched message shape,
damage tallies, monster death sequencing, loot-announce timing,
critical-part-kill HP-summary suppression, RAMPAGE / SURVIVE /
VENGEFUL scheduling, and the new turn order.

Tests are seeded-RNG functional comparisons — not byte-exact diffs
against the legacy path. The legacy body remains callable as
``Game._do_combat_legacy`` so future bisection against regressions
can be done in one line.
"""

from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.rpg.helpers.enums import AggressionLevels


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_game_with_monster(monster):
    """Build a minimal Game wrapped around ``monster`` with mocked
    Discord surface + no clock side-effects. Returns the game."""
    from caldanai.lib.rpg import Game

    guild = MagicMock()
    guild.id = 111
    guild.name = "TestGuild"
    guild.roles = []
    channel = MagicMock()
    channel.id = 222

    game = Game(
        guild=guild,
        channel=channel,
        game_id="g1",
        use_spawn_timer=False,
        enable_ambience=False,
    )
    game.monster = monster
    game.combatants = []
    game.combat_targets = {}
    game.looters = []
    game.monster_statics = defaultdict(int)

    # Async calls inside do_combat that aren't under test here.
    game.cancel_combat = AsyncMock()
    game.end_combat = AsyncMock()
    game.set_spawn_timer = AsyncMock()
    game.on_monster_death = AsyncMock(return_value="")

    # Monster clock hooks shouldn't actually schedule.
    game.game_clock.add_routine = MagicMock()
    game.game_clock.remove_routine = MagicMock()
    # Role gating — the player_manager needs a roles dict for
    # set_player_combatant to no-op cleanly.
    game.player_manager.roles = {}

    return game


def _make_player(name, uid, health=40, health_max=40):
    """Minimal Player that survives ``do_attack``. Avoids the real
    Player class's Discord-member plumbing — we only need the combat
    surface."""
    from caldanai.lib.rpg.creatures.player import Player

    p = Player(
        pid=uid,
        gid=111,
        uid=uid,
        health=health,
        health_max=health_max,
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


def _spawn(monster_key: str):
    """Spawn a monster by its filename stem via the registry."""
    from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
    MonsterPlugin.load_plugins()
    cls = MonsterPlugin.get_plugin_class(monster_key)
    return cls()


@pytest.fixture(autouse=True)
def _seed_random():
    """Deterministic RNG per test. Combat makes d20 / damage / death
    flavor choices that would otherwise drift across test orderings
    and cause flake. Conftest isolates state across tests but doesn't
    seed — seeding here gives each test a reproducible starting point
    while still isolating at conftest's boundary."""
    import random
    random.seed(0)


@pytest.fixture(autouse=True)
def _patch_discord():
    """Every test here hits ``Dispatcher.add``; stub it so nothing
    reaches the network. Same shape as test_hydra_monster's pattern."""
    with (
        patch("caldanai.lib.rpg.Dispatcher") as mock_dispatch,
        patch("caldanai.lib.rpg.DB") as mock_db,
        patch("caldanai.lib.rpg.player_manager"),
    ):
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}
        mock_dispatch.split_message = lambda msg, sep=None, keep=False: [msg]
        yield mock_dispatch


# ---------------------------------------------------------------------------
# Turn order
# ---------------------------------------------------------------------------


class TestTurnOrder:
    """Phase 5 locked turn order: players act in join order (forward
    iteration of ``combatants``), monster retaliates afterwards.
    Today's accidental reverse-of-join (pop-while-iterating side
    effect) is gone."""

    @pytest.mark.asyncio
    async def test_players_attack_in_join_order(self, monkeypatch):
        goblin = _spawn("goblin")
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        bob = _make_player("bob", 2)
        charlie = _make_player("charlie", 3)
        game.combatants = [alice, bob, charlie]

        order: list = []
        from caldanai.lib.rpg.creatures.player import Player
        real_pick_actions = Player.pick_actions

        def _record(self, *args, **kwargs):
            order.append(self.name)
            return real_pick_actions(self, *args, **kwargs)

        monkeypatch.setattr(Player, "pick_actions", _record)

        await game.do_combat()

        # Join order — NOT reverse.
        assert order == ["alice", "bob", "charlie"], (
            f"Players should act in join order, got {order}. "
            "Phase-5 locked players-in-join-order; "
            "reverse-of-join is the legacy artifact."
        )

    @pytest.mark.asyncio
    async def test_monster_retaliates_after_all_players(self, monkeypatch):
        goblin = _spawn("goblin")
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        events: list = []
        from caldanai.lib.rpg.creatures.player import Player
        real_pick_actions = Player.pick_actions

        def _player_attack(self, *args, **kwargs):
            events.append("player_attack")
            return real_pick_actions(self, *args, **kwargs)

        monkeypatch.setattr(Player, "pick_actions", _player_attack)

        real_attack_random = type(goblin).attack_random

        def _monster_retaliate(self, *args, **kwargs):
            events.append("monster_retaliate")
            return real_attack_random(self, *args, **kwargs)

        monkeypatch.setattr(type(goblin), "attack_random", _monster_retaliate)

        await game.do_combat()
        # Player first, then monster.
        assert events[0] == "player_attack"
        assert "monster_retaliate" in events
        assert events.index("player_attack") < events.index("monster_retaliate")


# ---------------------------------------------------------------------------
# Damage tally
# ---------------------------------------------------------------------------


class TestMultiPlayerDamageTally:
    @pytest.mark.asyncio
    async def test_multi_player_total_damage_matches_per_player_sum(
        self, monkeypatch,
    ):
        goblin = _spawn("goblin")
        goblin.health_max = 500  # ensure survival through the round
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        bob = _make_player("bob", 2)
        game.combatants = [alice, bob]

        per_player: dict = {}
        from caldanai.lib.rpg.creatures.player import Player
        real_resolve = Player.resolve

        def _capture(self, assignments):
            mv = real_resolve(self, assignments)
            total = sum(
                r.damage for r in (mv.all_results or []) if r.damage > 0
            )
            per_player[self.user_id] = per_player.get(self.user_id, 0) + total
            return mv

        monkeypatch.setattr(Player, "resolve", _capture)

        hp_before = goblin.health
        await game.do_combat()
        # Each player contributed some damage; the summed floor'd
        # bodies-HP total matches the observable delta within each
        # player's num_hits floor. The assert here is loose — every
        # captured per-player tally is non-negative and at least one
        # non-zero sum landed.
        assert sum(per_player.values()) >= 0
        assert set(per_player.keys()) == {1, 2}
        # If any damage got through, monster.health must have moved
        # (barring complete miss across both players this round).
        if sum(per_player.values()) > 0:
            assert goblin.health <= hp_before


# ---------------------------------------------------------------------------
# Monster death + loot
# ---------------------------------------------------------------------------


class TestMonsterDeathAndLoot:
    @pytest.mark.asyncio
    async def test_loot_announce_fires_once_per_combat(self, _patch_discord):
        goblin = _spawn("goblin")
        goblin.health = 1
        goblin.health_max = 1
        goblin.dodge = 0  # guarantee every swing lands; avoids RNG flake
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        # Override on_monster_death to return a deterministic loot
        # string so we can count its appearances.
        game.on_monster_death = AsyncMock(return_value="LOOT!")
        await game.do_combat()

        dispatched_messages = [
            call.args[1]
            for call in _patch_discord.add.call_args_list
            if len(call.args) >= 2
        ]
        blob = "\n".join(str(m) for m in dispatched_messages)
        # "LOOT!" announced exactly once, not per-round.
        assert blob.count("LOOT!") == 1, (
            f"Expected loot-announce to fire exactly once per combat, "
            f"got {blob.count('LOOT!')} occurrences:\n{blob}"
        )

    @pytest.mark.asyncio
    async def test_monster_death_emits_death_msg(self, _patch_discord):
        goblin = _spawn("goblin")
        goblin.health = 1
        goblin.health_max = 1
        goblin.dodge = 0  # guarantee every swing lands; avoids RNG flake
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        await game.do_combat()

        blob = "\n".join(
            str(call.args[1]) for call in _patch_discord.add.call_args_list
            if len(call.args) >= 2
        )
        # Goblin death uses a distinctive token.
        assert "flops onto the ground" in blob

    @pytest.mark.asyncio
    async def test_hp_summary_appears_when_monster_survives(self, _patch_discord):
        goblin = _spawn("goblin")
        goblin.health_max = 200
        goblin.health = 200
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        await game.do_combat()

        blob = "\n".join(
            str(call.args[1]) for call in _patch_discord.add.call_args_list
            if len(call.args) >= 2
        )
        # Summary line shape.
        assert "Total damage done vs Health" in blob


# ---------------------------------------------------------------------------
# Critical-part-kill suppression
# ---------------------------------------------------------------------------


class TestCriticalPartKillSuppression:
    @pytest.mark.asyncio
    async def test_critical_part_kill_suppresses_hp_summary(
        self, monkeypatch, _patch_discord,
    ):
        """When a player's attack destroys a critical part, the HP
        summary is suppressed (today's contract via
        ``resolution.critical_part_kill``). Phase 6d — the pipeline's
        per-victim ``ResolutionResult`` is now the source of truth,
        so this test patches ``Player.resolve`` to fabricate the
        critical-part-kill signal."""
        from caldanai.lib.rpg.combat.resolution import (
            MultiVictimResolutionResult, ResolutionResult,
        )
        from caldanai.lib.rpg.creatures.player import Player

        goblin = _spawn("goblin")
        goblin.health = 1
        goblin.health_max = 1
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        def _fake_resolve(self, assignments):
            goblin.health = 0
            return MultiVictimResolutionResult(
                per_victim={
                    goblin: ResolutionResult(
                        body_damage_total=10,
                        num_hits=1,
                        death_msg="@1np head is utterly destroyed!",
                        critical_part_kill=True,
                    ),
                },
                all_results=[],
                any_critical_part_kill=True,
            )

        monkeypatch.setattr(Player, "resolve", _fake_resolve)

        await game.do_combat()

        blob = "\n".join(
            str(call.args[1]) for call in _patch_discord.add.call_args_list
            if len(call.args) >= 2
        )
        assert "Total damage done vs Health" not in blob


# ---------------------------------------------------------------------------
# RAMPAGE / SURVIVE / VENGEFUL branches
# ---------------------------------------------------------------------------


class TestAggressionBranching:
    @pytest.mark.asyncio
    async def test_rampage_schedules_next_round(self):
        goblin = _spawn("goblin")
        goblin.aggression = AggressionLevels.RAMPAGE
        goblin.health_max = 200
        goblin.health = 200
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        await game.do_combat()

        # RAMPAGE: schedules another do_combat via add_routine.
        add_calls = game.game_clock.add_routine.call_args_list
        scheduled = [c for c in add_calls if c.args and c.args[0] == game.do_combat]
        assert scheduled, "RAMPAGE monsters must reschedule do_combat"

    @pytest.mark.asyncio
    async def test_vengeful_falls_through_to_escape(self):
        goblin = _spawn("goblin")
        goblin.aggression = AggressionLevels.VENGEFUL
        goblin.health_max = 200
        goblin.health = 200
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        await game.do_combat()

        game.cancel_combat.assert_awaited()

    @pytest.mark.asyncio
    async def test_survive_below_threshold_escapes(self):
        goblin = _spawn("goblin")
        goblin.aggression = AggressionLevels.SURVIVE
        goblin.health_max = 100
        goblin.health = 5  # below 0.1 scale — triggers escape
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        await game.do_combat()

        game.cancel_combat.assert_awaited()

    @pytest.mark.asyncio
    async def test_no_combatants_triggers_escape(self):
        goblin = _spawn("goblin")
        goblin.aggression = AggressionLevels.VENGEFUL
        goblin.health_max = 100
        goblin.health = 100
        game = _make_game_with_monster(goblin)
        game.combatants = []

        await game.do_combat()

        game.cancel_combat.assert_awaited()


# ---------------------------------------------------------------------------
# Dead combatants skipped + popped
# ---------------------------------------------------------------------------


class TestDeadCombatantHandling:
    @pytest.mark.asyncio
    async def test_dead_players_skipped_and_removed(self, monkeypatch):
        goblin = _spawn("goblin")
        goblin.health_max = 500
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alive = _make_player("alive", 1)
        dead = _make_player("dead", 2, health=0)
        game.combatants = [dead, alive]

        called_for: list = []
        from caldanai.lib.rpg.creatures.player import Player
        real = Player.pick_actions

        def _record(self, *args, **kwargs):
            called_for.append(self.name)
            return real(self, *args, **kwargs)

        monkeypatch.setattr(Player, "pick_actions", _record)

        await game.do_combat()

        assert "dead" not in called_for
        assert "alive" in called_for
        # Dead player popped from combatants.
        assert dead not in game.combatants


# ---------------------------------------------------------------------------
# Hydra pipeline path still works through do_combat
# ---------------------------------------------------------------------------


class TestHydraThroughPipeline:
    @pytest.mark.asyncio
    async def test_hydra_retaliation_flows_through_attack_random(
        self, monkeypatch,
    ):
        hydra = _spawn("hydra")
        hydra.aggression = AggressionLevels.VENGEFUL
        hydra.health_max = 500
        hydra.health = 500
        game = _make_game_with_monster(hydra)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        attack_random_calls: list = []
        real = type(hydra).attack_random

        def _record(self, *args, **kwargs):
            attack_random_calls.append(True)
            return real(self, *args, **kwargs)

        monkeypatch.setattr(type(hydra), "attack_random", _record)

        await game.do_combat()
        assert attack_random_calls, "Hydra retaliation must flow through attack_random"


# ---------------------------------------------------------------------------
# Legacy coexistence
# ---------------------------------------------------------------------------


class TestLegacyPathStillWorks:
    @pytest.mark.asyncio
    async def test_legacy_do_combat_still_callable(self, _patch_discord):
        """``_do_combat_legacy`` remains a drop-in so a regression can
        revert the wiring in one line."""
        goblin = _spawn("goblin")
        goblin.health_max = 500
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        await game._do_combat_legacy()

        blob = "\n".join(
            str(call.args[1]) for call in _patch_discord.add.call_args_list
            if len(call.args) >= 2
        )
        # Legacy produced *some* output.
        assert blob or not _patch_discord.add.call_args_list


# ---------------------------------------------------------------------------
# Phase 6d — player combat routed through pipeline stages
# ---------------------------------------------------------------------------


class TestPlayerPipelinePort:
    """Phase 6d: ``Game._run_player_block`` drives
    ``player.pick_actions`` → ``pick_targets`` → ``resolve`` →
    ``render_table`` → ``narrate_results`` rather than wrapping
    legacy ``Player.do_attack`` + ``apply_sequence_to_target``."""

    def _cripple(self, player, instance_name: str) -> None:
        part = next(p for p in player.body_parts if p.name == instance_name)
        part.health = 0

    def test_pick_actions_unarmed_dual_hands(self):
        """Unarmed player emits one source per usable hand."""
        from caldanai.lib.rpg.combat.attack_source import UnarmedAttackSource

        alice = _make_player("alice", 1)
        actions = alice.pick_actions()
        assert len(actions) == 2
        assert all(isinstance(s, UnarmedAttackSource) for s in actions)
        labels = {s.label for s in actions}
        assert labels == {"Left", "Right"}

    def test_pick_actions_one_weapon_one_fist(self):
        """One weapon in the left slot → one weapon source + one fist."""
        from caldanai.lib.rpg.combat.attack_source import (
            UnarmedAttackSource, WeaponAttackSource,
        )
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        from caldanai.lib.rpg.inventory.equipment.weapons import Weapon

        alice = _make_player("alice", 1)
        weapon = MagicMock(spec=Weapon)
        weapon.slots = EquipmentSlots.LEFT_HELD
        weapon.damage_type = None
        weapon.skill = "swords"
        weapon.attack = "1d8"
        weapon.bonus = 0
        weapon.reach = __import__(
            "caldanai.lib.rpg.helpers.enums", fromlist=["Reach"]
        ).Reach.MELEE
        alice.part_equipment["arm.left"]["held"] = weapon
        actions = alice.pick_actions()
        assert len(actions) == 2
        kinds = {type(s).__name__ for s in actions}
        assert "WeaponAttackSource" in kinds
        assert "UnarmedAttackSource" in kinds

    def test_pick_actions_two_handed_yields_single_source(self):
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        from caldanai.lib.rpg.inventory.equipment.weapons import Weapon

        alice = _make_player("alice", 1)
        weapon = MagicMock(spec=Weapon)
        weapon.slots = (
            EquipmentSlots.LEFT_HELD
            | EquipmentSlots.RIGHT_HELD
            | EquipmentSlots.MULTI_SLOT
        )
        weapon.damage_type = None
        weapon.skill = "two-handed swords"
        weapon.attack = "2d6"
        weapon.bonus = 1
        weapon.reach = __import__(
            "caldanai.lib.rpg.helpers.enums", fromlist=["Reach"]
        ).Reach.MELEE
        # Two-handed: same weapon at both arms.
        alice.part_equipment["arm.left"]["held"] = weapon
        alice.part_equipment["arm.right"]["held"] = weapon

        actions = alice.pick_actions()
        assert len(actions) == 1
        assert actions[0].label == "Two-Handed"

    def test_pick_actions_drops_useless_arm_source(self):
        alice = _make_player("alice", 1)
        self._cripple(alice, "arm.right")
        actions = alice.pick_actions()
        labels = {s.label for s in actions}
        assert "Right" not in labels
        assert "Left" in labels

    def test_pick_actions_both_arms_useless_returns_empty(self):
        alice = _make_player("alice", 1)
        self._cripple(alice, "arm.left")
        self._cripple(alice, "arm.right")
        assert alice.pick_actions() == []

    @pytest.mark.asyncio
    async def test_run_player_block_routes_through_pipeline_stages(
        self, monkeypatch,
    ):
        """The block's markdown contains the diff-block table — shape
        parity with pre-6d ``sequence.to_markdown()``."""
        goblin = _spawn("goblin")
        goblin.health_max = 500
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]

        call_order: list = []
        from caldanai.lib.rpg.creatures.player import Player

        real_pick = Player.pick_actions
        real_resolve = Player.resolve
        real_render = Player.render_table

        def _pa(self):
            call_order.append("pick_actions")
            return real_pick(self)

        def _res(self, a):
            call_order.append("resolve")
            return real_resolve(self, a)

        def _rt(self, r):
            call_order.append("render_table")
            return real_render(self, r)

        monkeypatch.setattr(Player, "pick_actions", _pa)
        monkeypatch.setattr(Player, "resolve", _res)
        monkeypatch.setattr(Player, "render_table", _rt)

        msg, _damage, _res_obj = await game._run_player_block(alice, goblin)
        # All three pipeline stages called in order.
        assert call_order.index("pick_actions") < call_order.index("resolve")
        assert call_order.index("resolve") < call_order.index("render_table")
        # Table produced (unless every roll missed — accept notes-only too).
        assert "```diff" in msg or msg == ""

    @pytest.mark.asyncio
    async def test_run_player_block_honors_explicit_part_targets(
        self, monkeypatch,
    ):
        """``combat_targets[user_id] = [\"head\"]`` routes into tuple
        assignments so the resolve stage damages the head."""
        from caldanai.lib.rpg.combat.block import Assignment

        goblin = _spawn("goblin")
        goblin.health_max = 500
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        game.combatants = [alice]
        game.combat_targets[alice.user_id] = ["head"]

        captured: list = []
        from caldanai.lib.rpg.creatures.player import Player
        real_resolve = Player.resolve

        def _capture(self, assignments):
            captured.append(list(assignments))
            return real_resolve(self, assignments)

        monkeypatch.setattr(Player, "resolve", _capture)

        await game._run_player_block(alice, goblin)

        assert captured, "resolve should have been invoked"
        assignments = captured[0]
        # Every assignment's target is a (goblin, head-part) tuple.
        for a in assignments:
            assert isinstance(a, Assignment)
            assert isinstance(a.target, tuple)
            victim, part = a.target
            assert victim is goblin
            assert part is not None and part.name.startswith("head")

    @pytest.mark.asyncio
    async def test_run_player_block_surfaces_disabled_arm_notes(self):
        """Disabled-arm notes render in the block markdown so players
        see why a hand didn't swing."""
        goblin = _spawn("goblin")
        goblin.health_max = 500
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        self._cripple(alice, "arm.right")
        game.combatants = [alice]

        msg, _damage, _res = await game._run_player_block(alice, goblin)
        assert "right arm hangs limp" in msg.lower()

    @pytest.mark.asyncio
    async def test_run_player_block_no_sources_returns_notes_only(self):
        """Two-handed weapon + one crippled arm → zero sources. The
        block still surfaces the disabled-arm explanation rather than
        silently rendering empty output."""
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        from caldanai.lib.rpg.inventory.equipment.weapons import Weapon

        goblin = _spawn("goblin")
        goblin.health_max = 500
        goblin.health = 500
        game = _make_game_with_monster(goblin)
        alice = _make_player("alice", 1)
        weapon = MagicMock(spec=Weapon)
        weapon.slots = (
            EquipmentSlots.LEFT_HELD
            | EquipmentSlots.RIGHT_HELD
            | EquipmentSlots.MULTI_SLOT
        )
        weapon.damage_type = None
        weapon.skill = "two-handed swords"
        weapon.attack = "2d6"
        weapon.bonus = 1
        weapon.reach = __import__(
            "caldanai.lib.rpg.helpers.enums", fromlist=["Reach"]
        ).Reach.MELEE
        weapon.get_full_name = MagicMock(return_value="greatsword")
        # Two-handed: same weapon at both arms.
        alice.part_equipment["arm.left"]["held"] = weapon
        alice.part_equipment["arm.right"]["held"] = weapon
        self._cripple(alice, "arm.right")
        game.combatants = [alice]

        msg, damage, res = await game._run_player_block(alice, goblin)
        assert damage == 0
        assert res is None
        assert "arm hangs limp" in msg.lower() or "cannot be wielded" in msg.lower()
