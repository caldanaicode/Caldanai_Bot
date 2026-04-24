"""Tests for tools/migrate_to_segmented_anatomy.py.

Pins the per-(part, key) remap table and the transformation
semantics. No DB access — purely testing the ``_remap_part_equipment``
function that takes a legacy dict and produces the new shape.
"""

from unittest import TestCase

from tools.migrate_to_segmented_anatomy import _remap_part_equipment


class SingleSlotRemapTests(TestCase):
    def test_head_helm_moves_to_head_worn(self):
        legacy = {"head": {"helm": "item1"}}
        new, warnings = _remap_part_equipment(legacy)
        self.assertEqual(new, {"head": {"worn": "item1"}})
        self.assertEqual(warnings, [])

    def test_head_face_moves_to_head_outer(self):
        legacy = {"head": {"face": "bandanna_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"head": {"outer": "bandanna_id"}})

    def test_head_ear_left_moves_to_earring_left(self):
        legacy = {"head": {"ear.left": "earring_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"head": {"earring.left": "earring_id"}})

    def test_torso_chest_moves_to_torso_worn(self):
        legacy = {"torso": {"chest": "shirt_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"torso": {"worn": "shirt_id"}})

    def test_torso_cape_moves_to_torso_outer(self):
        legacy = {"torso": {"cape": "cape_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"torso": {"outer": "cape_id"}})

    def test_torso_belt_moves_to_torso_accent(self):
        legacy = {"torso": {"belt": "belt_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"torso": {"accent": "belt_id"}})

    def test_neck_amulet_moves_to_neck_accent(self):
        legacy = {"neck": {"amulet": "amulet_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"neck": {"accent": "amulet_id"}})


class ArmRemapTests(TestCase):
    def test_weapon_moves_from_arm_to_hand(self):
        legacy = {"arm.left": {"held": "sword_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"hand.left": {"held": "sword_id"}})

    def test_bracer_stays_on_arm_as_worn_upper(self):
        legacy = {"arm.left": {"bracer": "bracer_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"arm.left": {"worn.upper": "bracer_id"}})

    def test_vambrace_stays_on_arm_as_worn_lower(self):
        legacy = {"arm.right": {"vambrace": "vambrace_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"arm.right": {"worn.lower": "vambrace_id"}})

    def test_glove_moves_from_arm_to_hand_as_worn(self):
        legacy = {"arm.left": {"glove": "glove_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"hand.left": {"worn": "glove_id"}})

    def test_ring_moves_from_arm_to_hand_ring_1(self):
        legacy = {"arm.right": {"ring": "ring_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"hand.right": {"ring.1": "ring_id"}})


class LegRemapTests(TestCase):
    def test_greave_stays_on_leg_as_worn_upper(self):
        legacy = {"leg.left": {"greave": "greave_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"leg.left": {"worn.upper": "greave_id"}})

    def test_shin_stays_on_leg_as_worn_lower(self):
        legacy = {"leg.right": {"shin": "shin_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"leg.right": {"worn.lower": "shin_id"}})

    def test_boot_moves_from_leg_to_foot_as_worn(self):
        legacy = {"leg.left": {"boot": "boot_id"}}
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"foot.left": {"worn": "boot_id"}})


class FullPlayerShapeTests(TestCase):
    def test_fully_dressed_humanoid_migrates(self):
        """A player in full pre-D gear should land entirely in
        the new anatomy — helm + face + chest + cape + belt +
        amulet + two weapons + two gloves + two rings + bracers
        + greaves + boots."""
        legacy = {
            "head": {
                "helm": "helm_id",
                "face": "bandanna_id",
                "ear.left": "earring_l_id",
                "ear.right": "earring_r_id",
            },
            "neck": {"amulet": "amulet_id"},
            "torso": {
                "chest": "chest_id",
                "cape": "cape_id",
                "belt": "belt_id",
            },
            "arm.left": {
                "held": "sword_id",
                "bracer": "lbracer_id",
                "vambrace": "lvambrace_id",
                "glove": "lglove_id",
                "ring": "lring_id",
            },
            "arm.right": {
                "held": "wand_id",
                "bracer": "rbracer_id",
                "vambrace": "rvambrace_id",
                "glove": "rglove_id",
                "ring": "rring_id",
            },
            "leg.left": {
                "greave": "lgreave_id",
                "shin": "lshin_id",
                "boot": "lboot_id",
            },
            "leg.right": {
                "greave": "rgreave_id",
                "shin": "rshin_id",
                "boot": "rboot_id",
            },
        }
        new, warnings = _remap_part_equipment(legacy)
        self.assertEqual(warnings, [])
        self.assertEqual(new, {
            "head": {
                "worn": "helm_id",
                "outer": "bandanna_id",
                "earring.left": "earring_l_id",
                "earring.right": "earring_r_id",
            },
            "neck": {"accent": "amulet_id"},
            "torso": {
                "worn": "chest_id",
                "outer": "cape_id",
                "accent": "belt_id",
            },
            "arm.left": {
                "worn.upper": "lbracer_id",
                "worn.lower": "lvambrace_id",
            },
            "arm.right": {
                "worn.upper": "rbracer_id",
                "worn.lower": "rvambrace_id",
            },
            "hand.left": {
                "held": "sword_id",
                "worn": "lglove_id",
                "ring.1": "lring_id",
            },
            "hand.right": {
                "held": "wand_id",
                "worn": "rglove_id",
                "ring.1": "rring_id",
            },
            "leg.left": {
                "worn.upper": "lgreave_id",
                "worn.lower": "lshin_id",
            },
            "leg.right": {
                "worn.upper": "rgreave_id",
                "worn.lower": "rshin_id",
            },
            "foot.left": {"worn": "lboot_id"},
            "foot.right": {"worn": "rboot_id"},
        })


class IdempotencyTests(TestCase):
    def test_already_migrated_doc_passes_through(self):
        """Running the migration on a Phase D doc should produce
        the same Phase D doc — unknown key pairs are carried
        forward."""
        already_migrated = {
            "head": {"worn": "helm_id", "outer": "bandanna_id"},
            "hand.left": {"held": "sword_id"},
            "foot.right": {"worn": "boot_id"},
        }
        new, warnings = _remap_part_equipment(already_migrated)
        self.assertEqual(new, already_migrated)
        self.assertEqual(warnings, [])

    def test_empty_dict_returns_empty(self):
        new, warnings = _remap_part_equipment({})
        self.assertEqual(new, {})
        self.assertEqual(warnings, [])

    def test_none_entries_stripped(self):
        """Empty placements (value None) are dropped — Phase D
        stores only occupied slots."""
        legacy = {
            "head": {"helm": None, "face": "bandanna_id"},
            "torso": {"chest": None},
        }
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {"head": {"outer": "bandanna_id"}})


class EdgeCaseTests(TestCase):
    def test_non_dict_input_returns_empty(self):
        new, _ = _remap_part_equipment(None)
        self.assertEqual(new, {})

    def test_unknown_part_key_pair_preserved(self):
        """Future-compat: anything not in the remap table falls
        through verbatim (allows pre-migration of docs that
        already use Phase D keys)."""
        legacy = {"tail": {"worn": "tail_armor_id"}}
        new, warnings = _remap_part_equipment(legacy)
        self.assertEqual(new, {"tail": {"worn": "tail_armor_id"}})
        self.assertEqual(warnings, [])

    def test_two_handed_weapon_migrates_to_both_hands(self):
        """Two-handed weapons appear in both arm slots with the
        same id under pre-D. They should land at both hand slots
        under the new shape, same id."""
        legacy = {
            "arm.left": {"held": "spear_id"},
            "arm.right": {"held": "spear_id"},
        }
        new, _ = _remap_part_equipment(legacy)
        self.assertEqual(new, {
            "hand.left": {"held": "spear_id"},
            "hand.right": {"held": "spear_id"},
        })

    def test_mixed_old_and_new_keys_collision_warns(self):
        """A half-migrated doc (``head.helm`` AND ``head.worn`` in
        the same sub-dict) should preserve the first occupant at
        ``head.worn`` and emit a collision warning for the second.
        Operator-facing signal that something's off with the doc."""
        legacy = {
            "head": {
                "worn": "already_migrated_id",
                "helm": "legacy_id",
            },
        }
        new, warnings = _remap_part_equipment(legacy)
        # The pre-existing ``worn`` is preserved; the remap of
        # ``helm`` into ``worn`` collides and is dropped.
        self.assertEqual(new, {"head": {"worn": "already_migrated_id"}})
        self.assertEqual(len(warnings), 1)
        self.assertIn("Collision", warnings[0])
        self.assertIn("legacy_id", warnings[0])

    def test_all_none_placements_produce_empty_dict(self):
        """A player with every pre-D slot recorded but none
        occupied (all values ``None``) should migrate to an empty
        dict, not a dict of empty sub-dicts. Represents a player
        who held gear once, stripped it, and whose doc never got
        compacted."""
        legacy = {
            "head": {"helm": None, "face": None},
            "torso": {"chest": None, "cape": None, "belt": None},
            "arm.left": {"held": None, "ring": None},
        }
        new, warnings = _remap_part_equipment(legacy)
        self.assertEqual(new, {})
        self.assertEqual(warnings, [])
