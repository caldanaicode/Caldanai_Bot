"""Tests for bare-part-name broadening in the
``find_all_equipped_matching_placement`` resolver.

Gap captured 2026-04-22 in live TEST: ``$item torso`` /
``$item head`` returned "nothing matching" because the resolver
only matched bare *keys* (``helm``, ``cape``, ``held``), never
bare *part names*. Players naturally typed both forms. This
patch makes bare part names broaden to every occupied placement
on the matched part(s), with fuzzy-prefix part matching.

Pin here that:
- Bare part name returns every occupied placement on that part.
- Fuzzy-prefix part names (``arm`` matching ``arm.left`` +
  ``arm.right``) collect across both sides.
- Bare keys still win when they'd match (``held`` → both hands,
  not every part).
- Empty/unequipped part returns empty.
- Deduplicates two-handed weapons shared across arm placements.
"""

from unittest import TestCase
from unittest.mock import MagicMock

from caldanai.lib.rpg.creatures.player import Player


def _fresh_player() -> Player:
    p = Player(
        pid=1, gid=1, uid=1,
        health=20, health_max=20,
        defense=3, dodge=5,
    )
    p.member = MagicMock()
    p.member.id = 1
    return p


def _fake_item(name: str):
    item = MagicMock()
    item.name = name
    item.id = id(item)
    return item


class BarePartBroadeningTests(TestCase):
    def test_bare_torso_returns_all_occupied_torso_placements(self):
        p = _fresh_player()
        cape = _fake_item("cape")
        chest = _fake_item("chest_armor")
        p.place("torso", "cape", cape)
        p.place("torso", "chest", chest)

        results = p.find_all_equipped_matching_placement("torso")
        items = [r[0] for r in results]
        placements = [r[1] for r in results]
        self.assertEqual(len(results), 2)
        self.assertIn(cape, items)
        self.assertIn(chest, items)
        self.assertIn(("torso", "cape"), placements)
        self.assertIn(("torso", "chest"), placements)

    def test_bare_head_returns_helm_and_face(self):
        p = _fresh_player()
        helm = _fake_item("helm")
        bandanna = _fake_item("bandanna")
        p.place("head", "helm", helm)
        p.place("head", "face", bandanna)

        results = p.find_all_equipped_matching_placement("head")
        self.assertEqual(len(results), 2)
        placement_keys = {r[1][1] for r in results}
        self.assertEqual(placement_keys, {"helm", "face"})

    def test_fuzzy_prefix_arm_matches_both_sides(self):
        """``arm`` is a base name — ``find_parts`` fuzzy-
        matches it to both ``arm.left`` and ``arm.right``. A
        bare part query should collect placements across all
        matched parts."""
        p = _fresh_player()
        wand_left = _fake_item("wand_left")
        wand_right = _fake_item("wand_right")
        p.place("arm.left", "held", wand_left)
        p.place("arm.right", "held", wand_right)

        results = p.find_all_equipped_matching_placement("arm")
        self.assertEqual(len(results), 2)
        self.assertEqual(
            {r[1] for r in results},
            {("arm.left", "held"), ("arm.right", "held")},
        )

    def test_bare_key_still_wins_over_bare_part(self):
        """Key names (``held``) take precedence — the bare-key
        branch runs first and returns non-empty. If a part
        happened to be named ``held`` (it isn't today), the key
        interpretation would still win, matching today's docs."""
        p = _fresh_player()
        wand = _fake_item("wand")
        p.place("arm.left", "held", wand)

        results = p.find_all_equipped_matching_placement("held")
        # Single match via bare-key path; part-name path doesn't
        # contribute because "held" isn't a part name.
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], ("arm.left", "held"))

    def test_unoccupied_part_returns_empty(self):
        p = _fresh_player()
        # Nothing equipped on torso.
        results = p.find_all_equipped_matching_placement("torso")
        self.assertEqual(results, [])

    def test_unknown_part_returns_empty(self):
        p = _fresh_player()
        # No fuzzy-prefix match against any real part.
        results = p.find_all_equipped_matching_placement("xyzzy")
        self.assertEqual(results, [])

    def test_two_handed_weapon_deduplicated_on_bare_arm(self):
        """A two-handed weapon shares its Item reference across
        both arm placements. ``$item arm`` should report it
        once, not twice."""
        p = _fresh_player()
        staff = _fake_item("staff")
        p.place("arm.left", "held", staff)
        p.place("arm.right", "held", staff)

        results = p.find_all_equipped_matching_placement("arm")
        self.assertEqual(len(results), 1)
        self.assertIs(results[0][0], staff)

    def test_full_part_dot_key_still_wins_over_broadening(self):
        """A specific ``part.key`` query selects exactly that
        placement even if the same key is used elsewhere."""
        p = _fresh_player()
        wand_left = _fake_item("wand_left")
        wand_right = _fake_item("wand_right")
        p.place("arm.left", "held", wand_left)
        p.place("arm.right", "held", wand_right)

        results = p.find_all_equipped_matching_placement("arm.left.held")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], ("arm.left", "held"))
        self.assertIs(results[0][0], wand_left)


class ItemModeAmbiguitySurfacingTests(TestCase):
    """The user-facing change: ``$item <bare_part>`` should now
    return matches. When there are multiple items on the part,
    the cog surfaces ambiguity (same path as bare-key ambiguous
    queries) rather than claiming nothing matched."""

    def test_item_mode_single_match_returns_item(self):
        p = _fresh_player()
        cape = _fake_item("cape")
        p.place("torso", "cape", cape)

        res = p.resolve_item_query("torso", mode="item")
        self.assertEqual(len(res.items), 1)
        self.assertIs(res.items[0], cape)

    def test_item_mode_multi_match_surfaces_ambiguity(self):
        p = _fresh_player()
        cape = _fake_item("cape")
        chest = _fake_item("chest_armor")
        p.place("torso", "cape", cape)
        p.place("torso", "chest", chest)

        res = p.resolve_item_query("torso", mode="item")
        # No single item chosen — ambiguity surfaced.
        self.assertEqual(res.items, [])
        self.assertEqual(
            set(res.ambiguity_candidates),
            {"torso.cape", "torso.chest"},
        )

    def test_stow_mode_bare_part_clears_all_on_that_part(self):
        """``$stow torso`` should collect every occupied torso
        placement — the cog will un-equip them all, mirroring
        ``$stow held`` clearing both hands."""
        p = _fresh_player()
        cape = _fake_item("cape")
        chest = _fake_item("chest_armor")
        p.place("torso", "cape", cape)
        p.place("torso", "chest", chest)

        res = p.resolve_item_query("torso", mode="stow")
        self.assertEqual(len(res.items), 2)
        self.assertIn(cape, res.items)
        self.assertIn(chest, res.items)
