"""Tests for ``MonsterPlugin`` salvage paths — the
dismemberment-yields-armor-or-materials gameplay loop.

Two independent sources feed ``get_salvage(part)``:

1. **Worn-armor branch** — ``SPAWN_LOADOUT`` populates spawn-time
   placements at ``__init__``; ``get_salvage`` then rolls
   ``SALVAGE_SURVIVAL_CHANCE`` on each worn piece. The actual
   worn item drops with its rolled-at-spawn quality preserved.
   Bandits + goblins ride this path: they walk up wearing a
   subset of the scrap set, and only what they were wearing can
   drop. Defense from worn pieces flows automatically through
   :func:`effective_defense_for_part`.
2. **Generic SALVAGE_DROPS** — legacy ``(item_name, drop_chance,
   quality_range)`` table for NON-EQUIPMENT harvest (rags,
   leather, scale). Bearowl + werewolf ride this path: their
   bodies feed the crafting chain, not finished armor.
"""

from collections import Counter
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

from caldanai.lib.rpg.creatures.monsters.bandit import Bandit
from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
from caldanai.lib.rpg.helpers.enums import Qualities
from caldanai.lib.rpg.inventory import Inventory


@contextmanager
def _patch_random(return_value):
    """Patch ``random()`` at BOTH modules monster code reaches for
    it. The :class:`Creature`-level ``_apply_loadout`` calls
    ``random()`` from :mod:`caldanai.lib.rpg.creatures`, while
    monster-only paths (``get_salvage``, ``get_corpse_scavenge``,
    ``get_loot``) still call from :mod:`caldanai.lib.rpg.creatures.monsters`.
    Tests want a single uniform return value across construction +
    salvage / scavenge calls — patch both so the controlled value
    sticks regardless of which path runs first."""
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


class TestSalvageHelperGenericPath:
    """Generic ``SALVAGE_DROPS`` path — string-arg form, no
    placements involved. Pins the per-entry contract used by
    non-equipment drops (leather, scale, future fang/ichor)."""

    def test_default_returns_empty_for_unmapped_part(self):
        """Monsters with no SALVAGE_DROPS entry for a part yield
        nothing for it."""
        b = Bandit()
        # Bandit's SALVAGE_DROPS is empty — armor moved to
        # SPAWN_LOADOUT — so any base-name string returns [].
        assert b.get_salvage("eye") == []

    def test_drop_chance_zero_never_fires(self):
        """An entry with ``drop_chance = 0.0`` never produces an
        item, regardless of the quality range."""
        class ZeroChanceMonster(MonsterPlugin):
            SALVAGE_DROPS = {
                "arm": [("patchwork_bracer", 0.0, (50, 95))],
            }

        m = ZeroChanceMonster.__new__(ZeroChanceMonster)
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

        assert Qualities.JUNK in qualities
        assert Qualities.ORDINARY in qualities
        assert Qualities.FINE not in qualities
        assert Qualities.QUALITY not in qualities
        total = sum(qualities.values())
        assert qualities[Qualities.JUNK] > qualities[Qualities.ORDINARY]
        assert qualities[Qualities.JUNK] / total > 0.5


class TestBanditArmorLoadout:
    """Bandit scrap-armor loadout — bandits spawn wearing a
    random subset of the scrap set, and what they were wearing
    is what can drop on dismemberment."""

    def test_at_least_one_bracer_seen_across_many_spawns(self):
        """Stochastic smoke test: with a 30% bracer rate per arm,
        50 spawns × 2 arms = ~100 trials — exceedingly unlikely to
        produce zero. Confirms ``_apply_loadout`` runs at
        ``__init__`` against real SPAWN_LOADOUT entries."""
        Inventory.discover_items()
        seen = False
        for _ in range(50):
            b = Bandit()
            for part in b.body_parts:
                if part.name in ("arm.left", "arm.right"):
                    if part.placements.get("worn.lower") is not None:
                        seen = True
                        break
            if seen:
                break
        assert seen

    def test_random_zero_equips_full_loadout(self):
        """``random() = 0.0`` forces every entry to fire — both
        arms get a bracer AND a rerebrace (independent rolls per
        part instance produce paired sets when forced)."""
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
        for arm_name in ("arm.left", "arm.right"):
            arm = next(p for p in b.body_parts if p.name == arm_name)
            lower = arm.placements.get("worn.lower")
            upper = arm.placements.get("worn.upper")
            assert lower is not None and lower.name == "patchwork bracer"
            assert upper is not None and upper.name == "rough rerebrace"

    def test_random_one_skips_full_loadout(self):
        """``random() = 1.0`` causes every roll to fail. Every
        placement on every Equippable part stays empty."""
        Inventory.discover_items()
        with _patch_random(1.0):
            b = Bandit()
        for part in b.body_parts:
            placements = getattr(part, "placements", None) or {}
            for slot, item in placements.items():
                assert item is None, (
                    f"unexpected piece on {part.name}.{slot} at random=1.0"
                )

    def test_worn_armor_boosts_part_defense(self):
        """A bandit's arm defends better with a bracer placed than
        without. Proves loadout pieces flow through
        ``effective_defense_for_part``.

        Compares a single bandit before-and-after manual placement
        (rather than two separately-constructed bandits) so that
        un-patched ``randint`` / ``choice`` calls during ``__init__``
        don't introduce stat-noise between the two comparisons.
        """
        from caldanai.lib.rpg.creatures import effective_defense_for_part
        Inventory.discover_items()
        # random=1.0 → all spawn rolls fail; arm starts bare.
        with _patch_random(1.0):
            b = Bandit()
        arm = next(p for p in b.body_parts if p.name == "arm.left")
        assert arm.placements.get("worn.lower") is None

        bare_def = effective_defense_for_part(b, arm)

        bracer = Inventory.ITEMS["patchwork_bracer"].from_plugin(
            "patchwork_bracer", {"quality": "ORDINARY"},
        )
        arm.placements["worn.lower"] = bracer
        armored_def = effective_defense_for_part(b, arm)

        assert armored_def > bare_def

    def test_destroyed_part_drops_worn_piece(self):
        """A part wearing armor drops that EXACT instance on
        successful survival roll. Quality is preserved from the
        spawn-time roll (no fresh re-roll)."""
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
        arm = next(p for p in b.body_parts if p.name == "arm.left")
        bracer = arm.placements["worn.lower"]
        original_quality = bracer.quality
        assert bracer is not None

        with _patch_random(0.0):
            items = b.get_salvage(arm)

        assert bracer in items
        # Same instance, same quality — preserved through the drop.
        dropped = items[items.index(bracer)]
        assert dropped is bracer
        assert dropped.quality == original_quality

    def test_bare_part_drops_nothing(self):
        """A part wearing nothing yields no salvage. Bandits have
        no SALVAGE_DROPS entries (armor moved to SPAWN_LOADOUT),
        so no items at all."""
        Inventory.discover_items()
        with _patch_random(1.0):
            b = Bandit()
        arm = next(p for p in b.body_parts if p.name == "arm.left")
        items = b.get_salvage(arm)
        assert items == []

    def test_survival_roll_filters_drops(self):
        """When the survival roll exceeds SALVAGE_SURVIVAL_CHANCE
        (2/3), the piece is consumed by the destruction without
        dropping. Placements zero out either way."""
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
        arm = next(p for p in b.body_parts if p.name == "arm.left")
        assert arm.placements["worn.lower"] is not None

        # 0.99 > 2/3 → survival fails on every slot.
        with _patch_random(0.99):
            items = b.get_salvage(arm)
        assert items == []
        # Placements consumed regardless of survival outcome.
        for v in arm.placements.values():
            assert v is None

    def test_no_double_drop_on_repeat_call(self):
        """A second call on the same already-stripped part yields
        nothing. Placements clear on first call so re-invocation is
        idempotent.

        Patches ``random`` across BOTH ``Bandit()`` (loadout rolls)
        AND the ``get_salvage`` calls (survival rolls) so the test
        is robust against test-order RNG state — without this, the
        survival roll uses real random and can fail in suite-mode
        when prior tests leak state.
        """
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
            arm = next(p for p in b.body_parts if p.name == "arm.left")
            first = b.get_salvage(arm)
            second = b.get_salvage(arm)
        assert first
        assert second == []

    def test_worn_armor_bypasses_empty_salvage_drops(self):
        """Sanity: bandit's SALVAGE_DROPS is empty after the
        SPAWN_LOADOUT migration. Pin so a future regression
        re-adding scrap entries to SALVAGE_DROPS surfaces here."""
        b = Bandit()
        assert b.SALVAGE_DROPS == {}


class TestBanditHeldWeaponLoadout:
    """Phase 1 of project_held_weapons_via_loadout — held weapons
    ride the same SPAWN_LOADOUT plumbing as worn armor. Bandits
    spawn with a shortsword in the ``held`` slot on either hand
    (independent rolls), it surfaces in the body-parts ``Worn``
    field through the existing iterate-all-placements path, and
    it drops via the survival roll on hand destruction.

    Phase 2 (monsters actually USING the weapon, plus per-spawn
    weapon-skill randomization) is intentionally out of scope —
    these tests only pin the carried-and-droppable invariants.
    """

    def test_held_weapon_entry_present_on_hand(self):
        """``SPAWN_LOADOUT["hand"]`` carries a held-slot entry —
        regression pin so a future cleanup doesn't accidentally
        drop the shortsword (or move the slot back to ``worn``,
        which would clash with ``ratty_glove``)."""
        hand_entries = Bandit.SPAWN_LOADOUT["hand"]
        held_entries = [e for e in hand_entries if e[2] == "held"]
        assert len(held_entries) == 1, (
            f"Expected exactly one held-slot entry on hand; "
            f"got {hand_entries}"
        )
        name, freq, slot, q_range = held_entries[0]
        assert name == "shortsword"
        assert slot == "held"
        assert 0.0 < freq < 1.0
        assert q_range == (50, 95)

    def test_random_zero_equips_held_weapon(self):
        """``random() = 0.0`` forces every entry to fire — both
        hands get a shortsword in the ``held`` slot. Confirms the
        existing ``_apply_loadout`` walks the ``"held"`` key
        agnostically (no armor-specific code path needed)."""
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
        for hand_name in ("hand.left", "hand.right"):
            hand = next(p for p in b.body_parts if p.name == hand_name)
            held = hand.placements.get("held")
            assert held is not None and held.plugin == "shortsword", (
                f"Expected shortsword on {hand_name}.held at random=0.0; "
                f"got {held!r}"
            )

    def test_random_one_skips_held_weapon(self):
        """``random() = 1.0`` causes every roll to fail — held slot
        stays empty, same as worn slots."""
        Inventory.discover_items()
        with _patch_random(1.0):
            b = Bandit()
        for hand_name in ("hand.left", "hand.right"):
            hand = next(p for p in b.body_parts if p.name == hand_name)
            assert hand.placements.get("held") is None

    def test_destroyed_hand_drops_held_weapon(self):
        """A hand holding a shortsword drops that EXACT instance
        on a successful survival roll — same path the worn-armor
        branch uses, just keyed off the ``held`` placement."""
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
        hand = next(p for p in b.body_parts if p.name == "hand.left")
        sword = hand.placements["held"]
        assert sword is not None and sword.plugin == "shortsword"
        original_quality = sword.quality

        with _patch_random(0.0):
            items = b.get_salvage(hand)

        assert sword in items
        # Same instance, same quality — preserved through the drop,
        # so a high-quality spawn-rolled weapon stays high-quality
        # when looted.
        dropped = items[items.index(sword)]
        assert dropped is sword
        assert dropped.quality == original_quality

    def test_held_survival_roll_filters(self):
        """When the survival roll exceeds SALVAGE_SURVIVAL_CHANCE,
        the held weapon is consumed by the destruction without
        dropping. Held slot zeroes either way, mirroring the worn
        invariant."""
        Inventory.discover_items()
        with _patch_random(0.0):
            b = Bandit()
        hand = next(p for p in b.body_parts if p.name == "hand.left")
        assert hand.placements["held"] is not None

        # 0.99 > 2/3 → survival fails on every slot.
        with _patch_random(0.99):
            items = b.get_salvage(hand)
        assert items == []
        assert hand.placements["held"] is None

    def test_shortsword_no_longer_in_loot_dict(self):
        """Phase 1 of held-weapons moves shortsword out of the
        legacy ``self.loot`` dict so we don't double-roll. Bow is
        deliberately left in ``loot`` until Phase 2 figures out
        ranged weapons."""
        b = Bandit()
        assert "shortsword" not in b.loot, (
            "shortsword should be sourced via SPAWN_LOADOUT held "
            "slot now, not the legacy loot dict"
        )
        # Bow is still loot-only until ranged held is designed.
        assert "bow" in b.loot

    def test_held_weapon_does_not_boost_part_defense(self):
        """A held shortsword has no ``bonuses`` dict (it's a Weapon,
        not an Armor), so ``effective_defense_for_part`` reads None
        and contributes 0 — a sword in your hand doesn't make your
        hand harder to hit. Pin so a future weapon-bonuses field
        doesn't silently leak into hand defense without a deliberate
        design pass."""
        from caldanai.lib.rpg.creatures import effective_defense_for_part
        Inventory.discover_items()
        # All-fail loadout → bare hand baseline.
        with _patch_random(1.0):
            b = Bandit()
        hand = next(p for p in b.body_parts if p.name == "hand.left")
        bare_def = effective_defense_for_part(b, hand)

        sword = Inventory.ITEMS["shortsword"].from_plugin(
            "shortsword", {"quality": "ORDINARY"},
        )
        # Sanity: weapon has no bonuses dict to leak.
        assert getattr(sword, "bonuses", None) is None
        hand.placements["held"] = sword
        held_def = effective_defense_for_part(b, hand)

        assert held_def == bare_def, (
            f"Holding a shortsword changed hand defense "
            f"({bare_def} -> {held_def}); weapons should not "
            f"contribute to defense via the placements iteration."
        )


class TestGoblinArmorLoadout:
    """Goblins share the scrap palette but spawn fewer pieces and
    skip the bandit-flair touches (collars, sashes)."""

    def test_random_zero_equips_loadout(self):
        Inventory.discover_items()
        with _patch_random(0.0):
            g = Goblin()
        arm = next(p for p in g.body_parts if p.name == "arm.left")
        lower = arm.placements.get("worn.lower")
        assert lower is not None and lower.name == "patchwork bracer"
        # Goblin arms get no upper rerebrace (not in their loadout).
        assert arm.placements.get("worn.upper") is None

    def test_no_neck_armor(self):
        """Goblins don't carry collars — neck isn't in their
        SPAWN_LOADOUT. Differentiates from bandits."""
        Inventory.discover_items()
        with _patch_random(0.0):
            g = Goblin()
        neck = next(
            p for p in g.body_parts if p.name == "neck"
        )
        for v in neck.placements.values():
            assert v is None

    def test_destroyed_part_drops_worn_piece(self):
        Inventory.discover_items()
        with _patch_random(0.0):
            g = Goblin()
        arm = next(p for p in g.body_parts if p.name == "arm.left")
        bracer = arm.placements["worn.lower"]
        with _patch_random(0.0):
            items = g.get_salvage(arm)
        assert bracer in items

    def test_salvage_drops_empty(self):
        g = Goblin()
        assert g.SALVAGE_DROPS == {}


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
        with _patch_random(0.0):
            items = b.get_salvage("torso")
        assert len(items) == 3
        assert all(i.plugin == "leather" for i in items)

    def test_leg_yields_up_to_two_leathers(self):
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        b = Bearowl()
        Inventory.discover_items()
        with _patch_random(0.0):
            items = b.get_salvage("leg")
        assert len(items) == 2
        assert all(i.plugin == "leather" for i in items)

    def test_real_part_lookup_path_works(self):
        """The actual lookup in ``Game._run_player_block`` calls
        ``monster.get_salvage(part)``, with the helper deriving
        the base name internally. Pin-tests that the keys in
        SALVAGE_DROPS match what ``_part_base_name`` returns for
        each leg-part instance — catches the original 2026-04-26
        bug where keys were ``"foreleg"``/``"hindleg"`` and never
        matched."""
        from caldanai.lib.rpg.creatures.monsters.bearowl import Bearowl
        from caldanai.lib.rpg.creatures import _part_base_name
        b = Bearowl()
        Inventory.discover_items()
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
            with _patch_random(0.0):
                for item in b.get_salvage("torso"):
                    qualities[item.quality] += 1
        assert qualities[Qualities.ORDINARY] > qualities[Qualities.FINE]
        assert qualities[Qualities.ORDINARY] > qualities[Qualities.JUNK]
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
        with _patch_random(0.0):
            items = w.get_salvage("torso")
        assert len(items) == 3
        assert all(i.plugin == "leather" for i in items)

    def test_leg_yields_up_to_two_leathers(self):
        from caldanai.lib.rpg.creatures.monsters.werewolf import Werewolf
        w = Werewolf()
        Inventory.discover_items()
        with _patch_random(0.0):
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


class TestSalvageNarrationCollapse:
    """``_render_salvage_lines`` coalesces same-render salvage drops
    into one line per ``(article, name)`` group. Two leathers off
    the same destroyed part read as ``"Two leathers slip free ..."``;
    a single drop keeps the today-shape ``"Some leather slips
    free ..."``. Mixed drops (leather + bracer) keep separate lines."""

    def _make_item(self, article, name, plural=None):
        """Tiny stand-in that satisfies the ``article`` / ``name``
        contract :func:`_render_salvage_lines` reads. Avoids
        ``Inventory.discover_items()`` overhead and keeps tests
        focused on the narration shape. ``plural`` is left unset
        (no attribute) when ``None`` so ``getattr(..., "plural",
        None)`` returns ``None`` and the helper falls back to
        :func:`_pluralize_salvage_name`."""
        class _StubItem:
            pass
        it = _StubItem()
        it.article = article
        it.name = name
        if plural is not None:
            it.plural = plural
        return it

    def test_single_drop_keeps_today_format(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [self._make_item("some", "leather")]
        lines = _render_salvage_lines(
            items, "the bearowl's", "left foreleg",
        )
        assert lines == [
            "   Some leather slips free of the bearowl's left foreleg.",
        ]

    def test_two_same_collapses_to_count_word_plural_verb(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [
            self._make_item("some", "leather"),
            self._make_item("some", "leather"),
        ]
        lines = _render_salvage_lines(
            items, "the bearowl's", "left foreleg",
        )
        assert lines == [
            "   Two leathers slip free of the bearowl's left foreleg.",
        ]

    def test_three_same_uses_three(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [self._make_item("some", "leather") for _ in range(3)]
        lines = _render_salvage_lines(
            items, "the bearowl's", "torso",
        )
        assert lines == [
            "   Three leathers slip free of the bearowl's torso.",
        ]

    def test_eleven_falls_through_to_digit_form(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [self._make_item("some", "leather") for _ in range(11)]
        lines = _render_salvage_lines(
            items, "the bearowl's", "torso",
        )
        assert lines == [
            "   11 leathers slip free of the bearowl's torso.",
        ]

    def test_mixed_drops_keep_distinct_lines_singular_each(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [
            self._make_item("a", "patchwork bracer"),
            self._make_item("a", "rough rerebrace"),
        ]
        lines = _render_salvage_lines(
            items, "the bandit's", "right arm",
        )
        assert lines == [
            "   A patchwork bracer slips free of the bandit's right arm.",
            "   A rough rerebrace slips free of the bandit's right arm.",
        ]

    def test_mixed_with_collapse_two_leathers_one_bracer(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [
            self._make_item("some", "leather"),
            self._make_item("some", "leather"),
            self._make_item("a", "patchwork bracer"),
        ]
        lines = _render_salvage_lines(
            items, "the bandit's", "torso",
        )
        assert lines == [
            "   Two leathers slip free of the bandit's torso.",
            "   A patchwork bracer slips free of the bandit's torso.",
        ]

    def test_three_leathers_plus_one_rerebrace(self):
        from caldanai.lib.rpg import _render_salvage_lines
        items = [
            self._make_item("some", "leather"),
            self._make_item("some", "leather"),
            self._make_item("some", "leather"),
            self._make_item("a", "rough rerebrace"),
        ]
        lines = _render_salvage_lines(
            items, "the bandit's", "torso",
        )
        assert lines == [
            "   Three leathers slip free of the bandit's torso.",
            "   A rough rerebrace slips free of the bandit's torso.",
        ]

    def test_empty_input_yields_empty_list(self):
        from caldanai.lib.rpg import _render_salvage_lines
        assert _render_salvage_lines(
            [], "the bandit's", "torso",
        ) == []

    def test_pluralize_appends_s_to_last_word(self):
        """Every salvage name we ship today pluralizes via
        last-word + ``"s"``. Pin the rule so a future bone/scale
        item that needs a different shape surfaces here."""
        from caldanai.lib.rpg import _pluralize_salvage_name
        assert _pluralize_salvage_name("leather") == "leathers"
        assert _pluralize_salvage_name("patchwork bracer") == "patchwork bracers"
        assert _pluralize_salvage_name("rough rerebrace") == "rough rerebraces"
        assert _pluralize_salvage_name("iron scrap") == "iron scraps"

    def test_explicit_plural_attribute_overrides_default_rule(self):
        """``Stackable`` items carry an explicit ``plural`` attr.
        A future ``wool`` drop ("tufts of wool") would silently
        mis-render under the simple last-word + ``s`` rule
        (``"wools"``); the helper now prefers ``getattr(item,
        "plural", None)`` when present."""
        from caldanai.lib.rpg import _render_salvage_lines
        items = [
            self._make_item("some", "wool", plural="tufts of wool"),
            self._make_item("some", "wool", plural="tufts of wool"),
        ]
        lines = _render_salvage_lines(
            items, "the sheep's", "torso",
        )
        assert lines == [
            "   Two tufts of wool slip free of the sheep's torso.",
        ]

    def test_missing_plural_attribute_falls_back_to_default_rule(self):
        """Items without a ``plural`` attribute (the SALVAGE_DROPS
        path today — leather is materialized via ``Inventory`` so
        only the in-place stub here lacks one) still pluralize via
        last-word + ``s``. Pins the fallback so the explicit-plural
        branch doesn't regress non-Stackable callers."""
        from caldanai.lib.rpg import _render_salvage_lines
        items = [
            self._make_item("some", "leather"),
            self._make_item("some", "leather"),
        ]
        lines = _render_salvage_lines(
            items, "the bearowl's", "torso",
        )
        assert lines == [
            "   Two leathers slip free of the bearowl's torso.",
        ]
