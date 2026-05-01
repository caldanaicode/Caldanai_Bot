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

    def test_loot_resets_to_baseline_across_imitations(self):
        """Each imitation resets ``self.loot`` to the doppy's
        baseline (the five entries seeded in ``__init__``) before
        re-seeding from the new target's inventory. Pre-fix, every
        imitation layered the new target's plugins onto the
        existing loot table without clearing prior targets' adds —
        a doppy that imitated three players ended up rolling drops
        from all three at once. 2026-04-29 fix."""
        doppel = Doppelganger()
        item1 = MagicMock()
        item1.plugin = "unique_to_alice"
        item2 = MagicMock()
        item2.plugin = "unique_to_bob"

        player1 = _make_player("Alice")
        player1.inventory.all.return_value = (item1,)
        player2 = _make_player("Bob")
        player2.inventory.all.return_value = (item2,)

        doppel.imitate(player1)
        assert "unique_to_alice" in doppel.loot

        doppel.imitate(player2)
        # Alice's plugin must NOT carry over; Bob's must be present.
        assert "unique_to_alice" not in doppel.loot
        assert "unique_to_bob" in doppel.loot
        # Doppy's baseline stays across resets.
        assert "shortsword" in doppel.loot
        assert "bandanna" in doppel.loot

    def test_non_player_returns_empty(self):
        doppel = Doppelganger()
        creature = MagicMock(spec=Creature)

        result = doppel.imitate(creature)

        assert result == ""
        assert doppel.name == "???"

    def test_imitate_clears_object_ids_on_mimicked_gear(self):
        """When the doppy deep-copies a target's body tree, the
        resulting body parts carry deep-copied equipment placements
        — and ``copy.deepcopy`` preserves each Item's ``ObjectId``
        verbatim (immutable, no fresh-id semantics). Without
        intervention, the doppy's mimicked bandanna shares the
        SAME ``_id`` as the player's worn bandanna, and when a
        salvage / corpse-scavenge roll lands and the clone enters
        the player's bag, the dup-id silently collides with the
        original at every ``inventory[item.id]`` lookup.

        The fix nulls ``item.id`` on every deep-copied placement
        at imitation time. ``Inventory.add`` already promotes
        ``id is None`` to a fresh ``ObjectId`` at insertion time,
        so the clone gets its real id only if and when it actually
        reaches a bag via the (now much-rarer) salvage path. Until
        then the placement-borne clone is anonymous and harmless.
        This regression guards the source-of-corruption fix and
        the symptom chain Caels caught live 2026-04-29 — a player
        with 3 bandannas all sharing one ``_id`` because of an
        earlier doppy kill that mimicked them."""
        from bson.objectid import ObjectId
        from caldanai.lib.rpg.creatures.player import Player as RealPlayer
        from caldanai.lib.rpg.helpers.enums import EquipmentSlots
        from caldanai.lib.rpg.inventory.equipment import Equipment

        # Real player with a real body tree (MagicMock skips the
        # imitate body-deepcopy branch; we need actual placements).
        target = RealPlayer(
            pid=ObjectId(), gid=1, uid=2, health=20, health_max=20,
            defense=6, dodge=6, gender="male",
            pronouns="he,him,his,his", weight_limit=100, clarks=0,
        )
        target.member = MagicMock()
        target.name = "TargetPlayer"

        bandanna = Equipment(
            iid=ObjectId(), name="bandanna",
            slots=EquipmentSlots.FACE,
            unit_weight=0.2, unit_value=1, quality=Qualities.QUALITY,
            plugin="bandanna",
        )
        target.inventory.add(bandanna)
        target.equip(bandanna)

        doppel = Doppelganger()
        doppel.imitate(target)

        # Every deep-copied placement should have its ``id``
        # nulled. Inventory.add will mint a fresh id only if the
        # clone ever actually enters a bag.
        cloned_ids = []
        for part in doppel.body_parts:
            placements = getattr(part, "placements", None) or {}
            for worn in placements.values():
                if worn is not None:
                    cloned_ids.append(worn.id)

        assert cloned_ids, "Expected at least one mimicked placement"
        assert all(cid is None for cid in cloned_ids), (
            f"Mimicked placements should have id=None after "
            f"imitation; got {cloned_ids!r}. A non-None id here "
            f"means a salvage roll could deposit a dup-id clone "
            f"into the player's bag."
        )

    def test_doppy_salvage_chances_lower_than_base(self):
        """Doppy mimicked equipment is organic flesh shaped to look
        like gear, not actual gear — so most of it dissolves with
        the body. Salvage still happens occasionally (preserving
        the player's rolled rarity when it does), but at an order-
        of-magnitude lower rate than normal monsters. Smoke test
        guards the override against future accidental removal."""
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin

        assert (
            Doppelganger.SALVAGE_SURVIVAL_CHANCE
            < MonsterPlugin.SALVAGE_SURVIVAL_CHANCE / 5
        ), "Doppy salvage rate should be substantially lower than base"
        assert (
            Doppelganger.CORPSE_SCAVENGE_CHANCE
            < MonsterPlugin.CORPSE_SCAVENGE_CHANCE / 5
        ), "Doppy corpse-scavenge rate should be substantially lower than base"


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
