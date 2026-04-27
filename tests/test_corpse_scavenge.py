"""Tests for the corpse-scavenge end-of-combat sweep — the
death-time companion to the per-part dismemberment salvage path.

When a monster dies via critical-part-kill (e.g. neck destroyed
in one good crit), worn pieces on parts that were NEVER destroyed
in combat get one final ``CORPSE_SCAVENGE_CHANCE`` roll each.
Without this, the cleanest, most efficient kill silently eats the
visible "Wearing" gear from ``$look`` — punishes good play.

Unit-level coverage targets ``MonsterPlugin.get_corpse_scavenge``:
empty-body return, success/fail roll bounds, idempotency on
re-call, and quality preservation of surviving instances.

Integration coverage targets ``Game.on_monster_death``: a Bandit
that dies without dismembered parts yields its worn pieces to
``self.loot`` via the round-robin distribution path documented in
``project_armor_drop_on_clean_kill.md``.
"""

from collections import defaultdict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
from caldanai.lib.rpg.inventory import Inventory


class TestGetCorpseScavengeUnit:
    """Direct ``MonsterPlugin.get_corpse_scavenge`` coverage. No
    Game / Discord surface — just the per-monster sweep contract."""

    def test_empty_when_no_parts_equipped(self):
        """A monster with bare placements (every spawn roll
        failed) yields nothing on the death sweep — no false
        drops from the empty-slot path."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=1.0,
        ):
            b = Bandit()
        # Confirm the loadout ran-and-failed — every placement
        # is None, but the placement KEYS still exist on each
        # Equippable part. The sweep must walk past these.
        for part in b.body_parts:
            placements = getattr(part, "placements", None) or {}
            for v in placements.values():
                assert v is None
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            assert b.get_corpse_scavenge() == []

    def test_random_zero_returns_all_worn_items(self):
        """``random() = 0.0`` is a guaranteed-success roll —
        every worn piece survives and lands in the result, paired
        with the part it came off."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
            # Snapshot the pre-sweep worn pieces so we can verify
            # all of them survived the 0.0 roll.
            expected: list = []
            for part in b.body_parts:
                placements = getattr(part, "placements", None) or {}
                for slot, item in placements.items():
                    if item is not None:
                        expected.append((part, item))
            survivors = b.get_corpse_scavenge()
        assert len(survivors) == len(expected)
        # Each surviving (part, item) maps back to one of the
        # original placements — same instances, no duplication.
        for part, item in survivors:
            assert (part, item) in expected

    def test_random_one_returns_empty_list(self):
        """``random() = 1.0`` always exceeds the 1/3 threshold —
        no piece survives. Every placement still clears (the
        idempotency invariant)."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        # Confirm pre-sweep state has worn pieces.
        had_worn = False
        for part in b.body_parts:
            placements = getattr(part, "placements", None) or {}
            if any(v is not None for v in placements.values()):
                had_worn = True
                break
        assert had_worn, "test setup failed: bandit has no worn pieces"

        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=1.0,
        ):
            survivors = b.get_corpse_scavenge()
        assert survivors == []
        # Placements still cleared — death consumes the gear
        # whether or not it survives the scavenge roll.
        for part in b.body_parts:
            placements = getattr(part, "placements", None) or {}
            for v in placements.values():
                assert v is None

    def test_idempotent_on_repeat_call(self):
        """A second call on the same body returns nothing. The
        first call clears every placement; the second walks past
        the now-empty slots."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
            first = b.get_corpse_scavenge()
            second = b.get_corpse_scavenge()
        assert first  # first call yielded something
        assert second == []

    def test_preserves_spawn_quality(self):
        """The exact worn instance (with its rolled-at-spawn
        quality) drops on success — no fresh quality reroll."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
            # Snapshot the exact items + their qualities.
            originals = []
            for part in b.body_parts:
                placements = getattr(part, "placements", None) or {}
                for slot, item in placements.items():
                    if item is not None:
                        originals.append((item, item.quality))
            survivors = b.get_corpse_scavenge()
        survivor_items = [item for _, item in survivors]
        for original, original_quality in originals:
            assert original in survivor_items
            # Same instance — quality is the same object.
            dropped = survivor_items[survivor_items.index(original)]
            assert dropped is original
            assert dropped.quality == original_quality

    def test_chance_threshold_pins_one_third(self):
        """``CORPSE_SCAVENGE_CHANCE`` is 1/3 — verify a roll just
        below the boundary succeeds and one just above fails. The
        complement of ``SALVAGE_SURVIVAL_CHANCE`` (2/3) is the
        whole point of the rate split."""
        assert MonsterPlugin.CORPSE_SCAVENGE_CHANCE == pytest.approx(1.0 / 3.0)
        assert (
            MonsterPlugin.CORPSE_SCAVENGE_CHANCE
            < MonsterPlugin.SALVAGE_SURVIVAL_CHANCE
        )

        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        # 0.30 < 1/3 → success; 0.40 > 1/3 → fail.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.30,
        ):
            survivors = b.get_corpse_scavenge()
        assert survivors  # at least one piece survived

        # Re-spawn for the failing-roll case (sweep is
        # destructive — placements cleared above).
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b2 = Bandit()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.40,
        ):
            survivors2 = b2.get_corpse_scavenge()
        assert survivors2 == []

    def test_default_monster_returns_empty(self):
        """A bare ``MonsterPlugin`` subclass (no body_parts) walks
        the empty list and returns nothing — no AttributeError on
        creatures that haven't materialized a body."""
        class BarestMonster(MonsterPlugin):
            pass

        m = BarestMonster.__new__(BarestMonster)
        m.body_parts = []
        assert m.get_corpse_scavenge() == []


@pytest.fixture
def _patch_discord_db():
    """Stub the Discord / DB / player_manager surface so
    ``Game(...)`` doesn't try to reach Mongo at construction. Same
    shape as ``test_game_do_combat_parity._patch_discord``."""
    with (
        patch("caldanai.lib.rpg.Dispatcher") as mock_dispatch,
        patch("caldanai.lib.rpg.DB") as mock_db,
        patch("caldanai.lib.rpg.player_manager"),
    ):
        mock_db.get_server_by_guild_id.return_value = {"prefix": "$"}
        mock_dispatch.split_message = lambda msg, sep=None, keep=False: [msg]
        yield mock_dispatch


@pytest.mark.usefixtures("_patch_discord_db")
class TestOnMonsterDeathScavengeIntegration:
    """End-to-end: ``Game.on_monster_death`` calls
    ``get_corpse_scavenge`` and routes surviving instances into
    ``self.loot`` via round-robin across ``self.looters``."""

    def _make_game_with_monster(self, monster):
        """Mirror the harness in ``test_game_do_combat_parity`` —
        minimal Game wrapped around ``monster`` with mocked
        Discord surface + no clock side-effects."""
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

        game.cancel_combat = AsyncMock(return_value="")
        game.end_combat = AsyncMock()
        game.set_spawn_timer = AsyncMock()

        game.game_clock.add_routine = MagicMock()
        game.game_clock.remove_routine = MagicMock()
        # ``on_monster_death`` reads ``roles[Roles.COMBAT_MAIN].mention``
        # for the prompt text — give it a stub role so the prompt
        # rendering doesn't KeyError.
        from caldanai.lib.rpg.helpers.enums import Roles
        combat_role = MagicMock()
        combat_role.mention = "@combat"
        game.player_manager.roles = {Roles.COMBAT_MAIN: combat_role}

        return game

    def _make_player(self, name, uid):
        from caldanai.lib.rpg.creatures.player import Player

        p = Player(
            pid=uid,
            gid=111,
            uid=uid,
            health=40,
            health_max=40,
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

    @pytest.mark.asyncio
    async def test_clean_kill_yields_worn_pieces_to_loot(self):
        """A bandit dying with no dismembered parts (clean
        crit-kill) yields worn pieces via the death sweep.
        Pre-fix, ``self.loot[user_id]`` only got
        ``monster.get_loot()`` (the bandanna table), so visible
        gear silently vanished."""
        Inventory.discover_items()
        # Spawn fully-loaded bandit (random=0.0 fires every loadout
        # entry); kill cleanly without pre-clearing placements.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        # Force ``get_loot`` to be empty so we can isolate the
        # corpse-scavenge contribution to ``self.loot``.
        b.loot = {}

        game = self._make_game_with_monster(b)
        alice = self._make_player("alice", 1)
        game.looters = [alice]
        game.loot = {1: []}

        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            msg = await game.on_monster_death()

        # Alice received at least one worn piece. Every Bandit
        # body_part that had ARMOR_LOADOUT entries fired at
        # random=0.0, so her loot is non-empty.
        assert game.loot[1], (
            "expected corpse-scavenge pieces in alice's loot, got empty"
        )
        # Narration mentions "slips free" (matches inline-salvage
        # narration shape, so the player sees what they got).
        assert "slips free of" in msg

    @pytest.mark.asyncio
    async def test_failed_scavenge_no_loot_no_narration(self):
        """When every scavenge roll fails (random=1.0), no items
        land in loot and no narration appears. Sanity check that
        the narration path is gated on actual drops."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        b.loot = {}

        game = self._make_game_with_monster(b)
        alice = self._make_player("alice", 1)
        game.looters = [alice]
        game.loot = {1: []}

        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=1.0,
        ):
            msg = await game.on_monster_death()

        assert game.loot[1] == []
        # No "slips free of" line in the message.
        assert "slips free of" not in msg

    @pytest.mark.asyncio
    async def test_round_robin_distribution_across_looters(self):
        """Multi-looter case: surviving worn pieces round-robin
        across ``self.looters`` so each instance lands with
        exactly ONE recipient (no duplication of specific
        item instances). Pin the round-robin choice so a future
        switch to killer-takes-all is a deliberate, test-failing
        decision."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        b.loot = {}

        game = self._make_game_with_monster(b)
        alice = self._make_player("alice", 1)
        bob = self._make_player("bob", 2)
        carol = self._make_player("carol", 3)
        game.looters = [alice, bob, carol]
        game.loot = {1: [], 2: [], 3: []}

        # Snapshot the surviving items pre-call so we know how many
        # to expect across the three buckets — same RNG state
        # under random=0.0 makes this deterministic.
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            await game.on_monster_death()

        all_loot = game.loot[1] + game.loot[2] + game.loot[3]
        # No duplicates — every surviving instance lands once.
        assert len(set(id(i) for i in all_loot)) == len(all_loot)
        # Round-robin keeps buckets balanced — sizes differ by at
        # most one.
        sizes = [len(game.loot[1]), len(game.loot[2]), len(game.loot[3])]
        assert max(sizes) - min(sizes) <= 1, (
            f"round-robin bucket imbalance: {sizes}"
        )
        # Total dropped is the sum across recipients (sanity:
        # round-robin doesn't double-count).
        assert sum(sizes) == len(all_loot)

    @pytest.mark.asyncio
    async def test_no_looters_does_not_crash(self):
        """Edge case: monster dies with no looters tracked (every
        engaged player got KO'd but the death-blow still landed
        somehow). The sweep skips silently — no
        IndexError on ``self.looters[0]``."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        b.loot = {}

        game = self._make_game_with_monster(b)
        game.looters = []
        game.loot = {}

        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            msg = await game.on_monster_death()

        # No crash; nothing scavenged because there's nobody to
        # receive it. Narration path stays clean.
        assert "slips free of" not in msg

    @pytest.mark.asyncio
    async def test_scavenge_narration_collapses_same_item_on_part(self):
        """Two identical worn pieces on the SAME part collapse to
        one ``"Two ... slip free"`` line rather than two singular
        ``"... slips free"`` lines. Mirrors the inline-salvage
        collapse so the narration shape is consistent between the
        per-round and end-of-combat sweeps. See
        ``project_salvage_narration_collapse_dupes.md``."""
        Inventory.discover_items()
        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            b = Bandit()
        b.loot = {}

        # Force a same-render duplicate on a single part: two
        # patchwork bracers on arm.left's lower + upper slots. Real
        # bandit loadouts use a bracer + rerebrace there, so this is
        # a deliberate same-item override to surface the collapse.
        arm = next(p for p in b.body_parts if p.name == "arm.left")
        bracer1 = Inventory.ITEMS["patchwork_bracer"].from_plugin(
            "patchwork_bracer", {"quality": "ORDINARY"},
        )
        bracer2 = Inventory.ITEMS["patchwork_bracer"].from_plugin(
            "patchwork_bracer", {"quality": "JUNK"},
        )
        # Clear every other placement so only this one part
        # contributes to scavenge.
        for part in b.body_parts:
            placements = getattr(part, "placements", None) or {}
            for slot in placements:
                placements[slot] = None
        arm.placements["worn.lower"] = bracer1
        arm.placements["worn.upper"] = bracer2

        game = self._make_game_with_monster(b)
        alice = self._make_player("alice", 1)
        game.looters = [alice]
        game.loot = {1: []}

        with patch(
            "caldanai.lib.rpg.creatures.monsters.random",
            return_value=0.0,
        ):
            msg = await game.on_monster_death()

        # Both instances landed in alice's loot bucket (round-robin
        # routes item-by-item, narration-collapse doesn't lose
        # items).
        assert bracer1 in game.loot[1]
        assert bracer2 in game.loot[1]
        # Narration collapsed to one "Two patchwork bracers slip
        # free of the bandit's left arm." line.
        assert "Two patchwork bracers slip free of" in msg
        # No singular line for the same part lurking under the
        # collapsed line.
        assert "A patchwork bracer slips free of" not in msg
