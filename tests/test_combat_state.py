"""Targeted tests for :class:`caldanai.lib.rpg.combat_state.CombatState`.

Game-level combat behavior is already covered by ``tests/test_game.py``
(``TestEndCombat`` / ``TestCancelCombat`` / ``TestKillMonster``). These
tests lock in the CombatState-internal contract that Game delegates to:
default field values, ``end_combat`` clears state without touching
loot, and the six proxy properties on ``Game`` read/write through.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from caldanai.lib.rpg.combat_state import CombatState


class TestCombatStateDefaults:
    def test_fresh_state_is_empty(self):
        cs = CombatState()
        assert cs.monster is None
        assert cs.monsters == []
        assert cs.combatants == []
        assert cs.combat_targets == {}
        assert cs.looters == []
        assert cs.loot == {}

    def test_collections_are_independent_per_instance(self):
        """Default mutable fields must not leak between instances."""
        a = CombatState()
        b = CombatState()
        a.combatants.append(MagicMock())
        a.loot[1] = [MagicMock()]
        a.monsters.append("goblin")
        assert b.combatants == []
        assert b.loot == {}
        assert b.monsters == []


class TestCombatStateEndCombat:
    @pytest.mark.asyncio
    async def test_end_combat_clears_monster_combatants_targets_looters(self):
        cs = CombatState()
        cs.monster = MagicMock()
        cs.combatants = [MagicMock(), MagicMock()]
        cs.combat_targets = {1: ["head"], 2: ["torso"]}
        cs.looters = [MagicMock()]

        player_manager = MagicMock()
        player_manager.clear_combat_roles = AsyncMock()
        game_clock = MagicMock()
        do_combat = MagicMock()

        await cs.end_combat(player_manager, game_clock, do_combat)

        assert cs.monster is None
        assert cs.combatants == []
        assert cs.combat_targets == {}
        assert cs.looters == []
        game_clock.remove_routine.assert_called_once_with(do_combat)
        player_manager.clear_combat_roles.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_end_combat_preserves_loot(self):
        """Loot lifecycle is the caller's concern — end_combat must not touch it."""
        cs = CombatState()
        cs.loot = {1: [MagicMock(), MagicMock()]}
        loot_before = dict(cs.loot)

        player_manager = MagicMock()
        player_manager.clear_combat_roles = AsyncMock()
        await cs.end_combat(player_manager, MagicMock(), MagicMock())

        assert cs.loot == loot_before

    @pytest.mark.asyncio
    async def test_end_combat_passes_looters_to_clear_combat_roles(self):
        """``clear_combat_roles`` receives the in-flight looters list
        BEFORE it is cleared. Order matters: clearing the looters first
        would strip the data the role-removal needs."""
        cs = CombatState()
        looters = [MagicMock(), MagicMock()]
        cs.looters = list(looters)  # preserve a reference we can compare

        seen_arg = {}

        async def capture(arg):
            seen_arg["looters"] = list(arg)

        player_manager = MagicMock()
        player_manager.clear_combat_roles = capture

        await cs.end_combat(player_manager, MagicMock(), MagicMock())

        assert seen_arg["looters"] == looters
        assert cs.looters == []


class TestGameProxyProperties:
    """The six fields on Game must remain read/write via the legacy
    attribute names — cogs, tests, and monster hooks rely on this."""

    def _make_game(self):
        from caldanai.lib.rpg import Game
        # Bypass __init__ to avoid DB / clock / weather setup;
        # property delegation only needs ``self.combat``.
        game = Game.__new__(Game)
        game.combat = CombatState()
        return game

    def test_monster_roundtrip(self):
        g = self._make_game()
        assert g.monster is None
        m = MagicMock()
        g.monster = m
        assert g.monster is m
        assert g.combat.monster is m

    def test_combatants_roundtrip(self):
        g = self._make_game()
        combatants = [MagicMock(), MagicMock()]
        g.combatants = combatants
        assert g.combatants is combatants
        assert g.combat.combatants is combatants

    def test_combatants_list_mutation_visible(self):
        """Appending to ``game.combatants`` (as cogs do) must be visible
        on the underlying CombatState."""
        g = self._make_game()
        player = MagicMock()
        g.combatants.append(player)
        assert g.combat.combatants == [player]

    def test_combat_targets_roundtrip(self):
        g = self._make_game()
        g.combat_targets = {1: ["head"]}
        assert g.combat.combat_targets == {1: ["head"]}
        g.combat_targets[2] = ["torso"]
        assert g.combat.combat_targets[2] == ["torso"]

    def test_looters_roundtrip(self):
        g = self._make_game()
        looters = [MagicMock()]
        g.looters = looters
        assert g.combat.looters is looters

    def test_loot_roundtrip(self):
        g = self._make_game()
        g.loot = {1: [MagicMock()]}
        assert list(g.combat.loot.keys()) == [1]
        del g.loot[1]
        assert g.combat.loot == {}

    def test_monsters_roundtrip(self):
        g = self._make_game()
        g.monsters = ["goblin"]
        assert g.combat.monsters == ["goblin"]
