"""Tests for ``MonsterPlugin.SALVAGE_DROPS`` and
``MonsterPlugin.get_salvage`` — the dismemberment-yields-armor
gameplay loop.

Salvage drops have two independent rolls:

1. Drop chance — does an entry fire at all? (per-entry float in
   ``SALVAGE_DROPS``, e.g. ``0.6``).
2. Quality roll — when it fires, what tier? (per-entry
   ``(lo, hi)`` randint range fed through
   ``Qualities.from_scale``).

These tests pin both — the contract on the helper, the per-entry
shape, and the Bandit/Goblin scrap-set wiring.
"""

from collections import Counter
from unittest.mock import patch

from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory import Inventory


class TestSalvageHelper:
    def test_default_returns_empty_for_unmapped_part(self):
        """Monsters that don't override SALVAGE_DROPS yield nothing
        for any part. Drop-in default; opt-in via class attribute."""
        b = Bandit()
        # Bandit has entries for arm/foot/hand/torso — try a part it
        # doesn't have a salvage entry for.
        assert b.get_salvage("eye") == []

    def test_drop_chance_zero_never_fires(self):
        """An entry with ``drop_chance = 0.0`` never produces an
        item, regardless of the quality range."""
        class ZeroChanceMonster(MonsterPlugin):
            SALVAGE_DROPS = {
                "arm": [("patchwork_bracer", 0.0, (50, 95))],
            }

        m = ZeroChanceMonster.__new__(ZeroChanceMonster)
        # No __init__ — we only need the class-level dict.
        for _ in range(50):
            assert m.get_salvage("arm") == []

    def test_drop_chance_one_always_fires(self):
        """An entry with ``drop_chance = 1.0`` always produces an
        item. Coverage flag for the per-entry roll boundary."""
        class GuaranteedMonster(MonsterPlugin):
            SALVAGE_DROPS = {
                "arm": [("patchwork_bracer", 1.0, (50, 95))],
            }

        m = GuaranteedMonster.__new__(GuaranteedMonster)
        Inventory.discover_items()
        for _ in range(20):
            items = m.get_salvage("arm")
            assert len(items) == 1
            assert items[0].name == "patchwork bracer"

    def test_quality_range_drives_distribution(self):
        """Repeated rolls within a JUNK-heavy band yield mostly
        JUNK with rare ORDINARY. Pins the
        ``Qualities.from_scale(randint(*range))`` mapping —
        ``(50, 95)`` covers JUNK + ORDINARY only (per the inverted
        from_scale: lower randint → better quality)."""
        class TestMonster(MonsterPlugin):
            SALVAGE_DROPS = {
                "arm": [("patchwork_bracer", 1.0, (50, 95))],
            }

        m = TestMonster.__new__(TestMonster)
        Inventory.discover_items()
        qualities = Counter()
        for _ in range(500):
            for item in m.get_salvage("arm"):
                qualities[item.quality] += 1

        # Strict assertions: this band shouldn't roll FINE-or-better.
        assert Qualities.JUNK in qualities
        assert Qualities.ORDINARY in qualities
        assert Qualities.FINE not in qualities
        assert Qualities.QUALITY not in qualities
        # JUNK should dominate (band is JUNK-heavy by design).
        total = sum(qualities.values())
        assert qualities[Qualities.JUNK] > qualities[Qualities.ORDINARY]
        assert qualities[Qualities.JUNK] / total > 0.5


class TestBanditScrapDrops:
    """Bandit's scrap-set wiring — the seed monster for the new
    salvage gameplay loop."""

    def test_foot_drops_worn_boot(self):
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("foot")
        assert len(items) == 1
        assert items[0].name == "worn boot"

    def test_hand_drops_ratty_glove(self):
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("hand")
        assert len(items) == 1
        assert items[0].name == "ratty glove"

    def test_torso_drops_jerkin_and_sash(self):
        """Bandit torso has TWO salvage entries — a jerkin
        (torso.worn slot) and a sash (torso.accent slot). Different
        slots, both can drop from one part destruction."""
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("torso")
        names = sorted(i.name for i in items)
        assert names == ["bandit's sash", "rough jerkin"]

    def test_head_drops_cap_and_hood(self):
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("head")
        names = sorted(i.name for i in items)
        assert names == ["rag hood", "rough cap"]

    def test_neck_drops_collar(self):
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("neck")
        assert len(items) == 1
        assert items[0].name == "scrap collar"

    def test_arm_drops_bracer_and_rerebrace(self):
        """Arm has the lower-bracer (forearm) AND upper-rerebrace
        slots; both drop from a destroyed arm."""
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("arm")
        names = sorted(i.name for i in items)
        assert names == ["patchwork bracer", "rough rerebrace"]

    def test_leg_drops_greave_and_shin(self):
        b = Bandit()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("leg")
        names = sorted(i.name for i in items)
        assert names == ["rough greave", "scrap shin"]


class TestGoblinScrapDrops:
    """Goblins share the scrap set with bandits at lower drop
    rates — they're scrappier and the gear is in worse shape."""

    def test_goblin_arm_yields_bracer(self):
        g = Goblin()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = g.get_salvage("arm")
        assert len(items) == 1
        assert items[0].name == "patchwork bracer"

    def test_goblin_skips_neck(self):
        """Goblins don't carry collars — neck isn't in their
        salvage table. Differentiates the goblin scrap profile
        from the bandit's (bandits get sashes + collars; goblins
        skip both ornamental layers)."""
        g = Goblin()
        assert g.get_salvage("neck") == []


class TestBearowlLeatherDrops:
    """Bearowl is the first source-creature for the leather
    crafting chain (per the source-creature-shape split locked
    2026-04-26: quadrupeds drop materials, not finished armor).
    Each entry produces a single ``leather`` stackable; multiple
    entries roll independently so a torso can yield 0-3 pieces.

    Keys must match ``_part_base_name(part)`` — for ``LegPlugin``
    that's ``"leg"`` for ALL four leg parts (foreleg + hindleg)."""

    def test_torso_yields_up_to_three_leathers(self):
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        b = Bearowl()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("torso")
        assert len(items) == 3
        assert all(i.plugin == "leather" for i in items)

    def test_leg_yields_up_to_two_leathers(self):
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        b = Bearowl()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = b.get_salvage("leg")
        assert len(items) == 2
        assert all(i.plugin == "leather" for i in items)

    def test_real_part_lookup_path_works(self):
        """The actual lookup in ``Game._run_player_block`` calls
        ``monster.get_salvage(_part_base_name(part))``. This pin-
        tests that the keys in SALVAGE_DROPS match what
        ``_part_base_name`` returns for each leg-part instance —
        catches the original 2026-04-26 bug where keys were
        ``"foreleg"``/``"hindleg"`` and never matched."""
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        from caldanai.lib.rpg.creatures import _part_base_name
        b = Bearowl()
        Inventory.discover_items()
        # All four leg instances should resolve through the real
        # base-name path to a non-empty drop list.
        leg_parts = [
            p for p in b.body_parts
            if p.name in (
                "foreleg.left", "foreleg.right",
                "hindleg.left", "hindleg.right",
            )
        ]
        assert len(leg_parts) == 4, "bearowl should have 4 leg parts"
        for leg in leg_parts:
            base = _part_base_name(leg)
            assert base in b.SALVAGE_DROPS, (
                f"Leg {leg.name} resolves to base '{base}' which "
                f"isn't in SALVAGE_DROPS. Keys: {sorted(b.SALVAGE_DROPS)}"
            )

    def test_unmapped_part_yields_nothing(self):
        """No leather from wings, head, eyes, paws, neck, tail —
        only the bulk torso and the legs."""
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        b = Bearowl()
        for part in ("head", "wing", "eye", "neck", "tail", "foot"):
            assert b.get_salvage(part) == []

    def test_quality_band_skews_ordinary(self):
        """Quality range ``(45, 60)`` skews ORDINARY-mode with a
        FINE upper tail and a thin JUNK tail — well above the
        bandit scrap-tier band, suitable input for crafting."""
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        b = Bearowl()
        Inventory.discover_items()
        qualities = Counter()
        for _ in range(500):
            with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
                for item in b.get_salvage("torso"):
                    qualities[item.quality] += 1
        # ORDINARY should be the modal quality.
        assert qualities[Qualities.ORDINARY] > qualities[Qualities.FINE]
        assert qualities[Qualities.ORDINARY] > qualities[Qualities.JUNK]
        # No SUPERIOR or higher — leather isn't legendary.
        assert qualities[Qualities.SUPERIOR] == 0
        assert qualities[Qualities.MASTERWORK] == 0

    def test_aggression_is_survive(self):
        """Bearowl was VENGEFUL (flees after one hit), which made
        the leather salvage loop unviable in playtest. SURVIVE
        keeps it engaged until ~10% HP — same fix the bandits got
        when scrap salvage shipped."""
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        from caldanai.lib.rpg.helpers.enums import AggressionLevels
        b = Bearowl()
        assert b.aggression == AggressionLevels.SURVIVE


class TestWerewolfLeatherDrops:
    """Werewolf is the second source-creature for the leather chain
    — same quadrupedal mammal shape as bearowl, slightly leaner
    yields per the matted-pelt description. Same single ``"leg"``
    key covers all four leg parts."""

    def test_torso_yields_up_to_three_leathers(self):
        from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
        w = Werewolf()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = w.get_salvage("torso")
        assert len(items) == 3
        assert all(i.plugin == "leather" for i in items)

    def test_leg_yields_up_to_two_leathers(self):
        from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
        w = Werewolf()
        Inventory.discover_items()
        with patch("caldanai.lib.rpg.creatures.monsters.random", return_value=0.0):
            items = w.get_salvage("leg")
        assert len(items) == 2
        assert all(i.plugin == "leather" for i in items)

    def test_real_part_lookup_path_works(self):
        """Same regression-pin as bearowl — catches the
        ``"foreleg"``/``"hindleg"`` keying bug."""
        from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
        from caldanai.lib.rpg.creatures import _part_base_name
        w = Werewolf()
        Inventory.discover_items()
        leg_parts = [
            p for p in w.body_parts
            if p.name in (
                "foreleg.left", "foreleg.right",
                "hindleg.left", "hindleg.right",
            )
        ]
        assert len(leg_parts) == 4
        for leg in leg_parts:
            base = _part_base_name(leg)
            assert base in w.SALVAGE_DROPS, (
                f"Leg {leg.name} resolves to base '{base}' which "
                f"isn't in SALVAGE_DROPS. Keys: {sorted(w.SALVAGE_DROPS)}"
            )

    def test_unmapped_part_yields_nothing(self):
        from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
        w = Werewolf()
        for part in ("head", "eye", "neck", "tail", "foot"):
            assert w.get_salvage(part) == []
