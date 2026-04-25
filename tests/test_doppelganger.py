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

    def test_adopts_target_stats(self):
        """Q.6.3-followup: ``imitate`` adopts the target's stats
        freshly on every switch. Pre-fix behavior took ``max()``
        across switches, which let a doppy accumulate best-of
        defense / dodge across every player it had ever copied —
        in-fiction "become this creature" should mean exactly that,
        not "become an aggregate of everyone you've copied."
        """
        doppel = Doppelganger()
        player = _make_player(defense=999, dodge=999)

        doppel.imitate(player)

        assert doppel.defense == 999
        assert doppel.dodge == 999

    def test_adopts_lower_stats_on_switch(self):
        """Switching to a weaker target drops the doppy's stats to
        match (no max-of preservation). Regression guard for the
        fix: a doppy that copies a tank then shifts to a squishy
        player should now have the squishy player's stats."""
        doppel = Doppelganger()
        strong = _make_player(name="Tank", defense=50, dodge=40, health_max=200)
        weak = _make_player(name="Squishy", defense=1, dodge=1, health_max=10)

        doppel.imitate(strong)
        assert doppel.defense == 50
        assert doppel.dodge == 40

        doppel.imitate(weak)
        assert doppel.defense == 1
        assert doppel.dodge == 1

    def test_preserves_own_hp_pool_on_imitate(self):
        """HP is NOT adopted from the imitated target — the doppy's
        body is its own (20d10 at spawn). Copying ``health_max``
        trivializes the fight because a 20HP player shift would cap
        the creature at 20HP. Pre-fix behavior did adopt it; this
        pins the new contract."""
        doppel = Doppelganger()
        doppel.health = 80
        doppel.health_max = 100
        player = _make_player(health_max=30)

        doppel.imitate(player)

        # Doppy keeps its own HP pool regardless of target.
        assert doppel.health == 80
        assert doppel.health_max == 100

    def test_same_form_re_imitate_is_noop(self):
        """Imitating the player whose face is already worn should
        short-circuit. Prevents per-round narration spam and stat
        thrashing when the same player keeps landing the hardest
        hit in ``on_pre_retaliation``."""
        doppel = Doppelganger()
        player = _make_player(name="Serena", defense=5, dodge=5)

        first = doppel.imitate(player)
        assert first  # the transformation narration
        assert doppel.name == "Serena"

        # Change a stat to detect re-run side-effects.
        doppel.defense = 999
        second = doppel.imitate(player)
        assert second == ""
        assert doppel.defense == 999  # not re-overwritten to 5

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


class TestOnPreRetaliation:
    def test_imitates_hardest_hitter(self):
        doppel = Doppelganger()
        weak = _make_player("Weak")
        strong = _make_player("Strong")

        msg = doppel.on_pre_retaliation([(weak, 5), (strong, 15)])

        assert doppel.name == "Strong"
        assert "likeness" in msg

    def test_empty_list_no_change(self):
        doppel = Doppelganger()
        original_name = doppel.name

        msg = doppel.on_pre_retaliation([])

        assert doppel.name == original_name
        assert msg == ""

    def test_ignores_non_player(self):
        doppel = Doppelganger()
        creature = MagicMock(spec=Creature)

        msg = doppel.on_pre_retaliation([(creature, 99)])

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
