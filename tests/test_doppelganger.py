"""Tests for the Doppelganger monster plugin."""

from unittest.mock import MagicMock

from caldanai.lib.rpg.creatures.monsters.doppelganger import Doppelganger
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.helpers.enums import Qualities


def _make_player(name="TestPlayer", defense=10, dodge=8, health=20, health_max=20):
    player = MagicMock(spec=Player)
    player.name = name
    player.get_defense.return_value = defense
    player.get_dodge.return_value = dodge
    player.get_health_max.return_value = health_max
    player.health = health
    player.health_max = health_max
    player.inventory = MagicMock()
    player.inventory.all.return_value = ()
    # Make isinstance(player, Player) return True
    player.__class__ = Player
    return player


class TestOnSpawn:
    def test_imitates_random_player(self):
        doppel = Doppelganger()
        player = _make_player("Caels")
        game = MagicMock()
        game.player_manager.players.values.return_value = [player]

        msg = doppel.on_spawn(game)

        assert doppel.name == "Caels"
        assert "likeness" in msg

    def test_no_players_returns_empty(self):
        doppel = Doppelganger()
        game = MagicMock()
        game.player_manager.players.values.return_value = []

        msg = doppel.on_spawn(game)

        assert msg == ""
        assert doppel.name == "???"


class TestImitate:
    def test_copies_name(self):
        doppel = Doppelganger()
        player = _make_player("Foxglove")

        doppel.imitate(player)

        assert doppel.name == "Foxglove"

    def test_takes_max_of_stats(self):
        doppel = Doppelganger()
        original_defense = doppel.defense
        original_dodge = doppel.dodge
        player = _make_player(defense=999, dodge=999)

        doppel.imitate(player)

        assert doppel.defense == 999
        assert doppel.dodge == 999

    def test_does_not_downgrade_stats(self):
        doppel = Doppelganger()
        original_defense = doppel.defense
        player = _make_player(defense=1, dodge=1, health_max=1)

        doppel.imitate(player)

        assert doppel.defense == original_defense

    def test_does_not_heal_on_imitate(self):
        doppel = Doppelganger()
        doppel.health = 5
        doppel.health_max = 50
        player = _make_player(health_max=100)

        doppel.imitate(player)

        assert doppel.health == 5
        assert doppel.health_max == 100

    def test_hp_capped_at_new_max(self):
        doppel = Doppelganger()
        doppel.health = 80
        doppel.health_max = 100
        player = _make_player(health_max=30)

        doppel.imitate(player)

        # health_max stays at 100 (max of 100, 30), health stays at 80
        assert doppel.health == 80

    def test_adds_inventory_to_loot(self):
        doppel = Doppelganger()
        item = MagicMock()
        item.plugin = "magic_sword"
        player = _make_player()
        player.inventory.all.return_value = (item,)

        doppel.imitate(player)

        assert "magic_sword" in doppel.loot

    def test_loot_accumulates_across_imitations(self):
        doppel = Doppelganger()
        item1 = MagicMock()
        item1.plugin = "sword"
        item2 = MagicMock()
        item2.plugin = "shield"

        player1 = _make_player("Alice")
        player1.inventory.all.return_value = (item1,)
        player2 = _make_player("Bob")
        player2.inventory.all.return_value = (item2,)

        doppel.imitate(player1)
        doppel.imitate(player2)

        assert "sword" in doppel.loot
        assert "shield" in doppel.loot

    def test_non_player_returns_empty(self):
        doppel = Doppelganger()
        creature = MagicMock(spec=Creature)

        result = doppel.imitate(creature)

        assert result == ""
        assert doppel.name == "???"


class TestOnCombatRound:
    def test_imitates_hardest_hitter(self):
        doppel = Doppelganger()
        weak = _make_player("Weak")
        strong = _make_player("Strong")

        msg = doppel.on_combat_round([(weak, 5), (strong, 15)])

        assert doppel.name == "Strong"
        assert "likeness" in msg

    def test_empty_list_no_change(self):
        doppel = Doppelganger()
        original_name = doppel.name

        msg = doppel.on_combat_round([])

        assert doppel.name == original_name
        assert msg == ""

    def test_ignores_non_player(self):
        doppel = Doppelganger()
        creature = MagicMock(spec=Creature)

        msg = doppel.on_combat_round([(creature, 99)])

        assert msg == ""
        assert doppel.name == "???"


class TestOnHugged:
    def test_returns_string(self):
        doppel = Doppelganger()
        actor = MagicMock()

        result = doppel.on_hugged(actor, "hug")

        assert isinstance(result, str)
        assert len(result) > 0

    def test_no_steal_call(self):
        doppel = Doppelganger()
        actor = MagicMock()

        assert not hasattr(doppel, "steal")
