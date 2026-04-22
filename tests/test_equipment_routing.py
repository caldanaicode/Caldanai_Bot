"""Regression tests for the equipment-on-parts routing module.

``caldanai.lib.rpg.creatures.equipment_routing`` is the single
source of truth for translating an :class:`EquipmentSlots` mask
into one or more ``(part, key)`` placements. These tests pin:

- Every slot that items currently declare resolves to at least
  one placement (no dead slot-references in the shipped items).
- Every placement's part name matches a real player anatomy
  part, so ``part_equipment`` never grows orphan keys.
- Multi-slot expansion is idempotent / dedupe-safe.
- Two-handed weapons fan out to both arms.
- Sister tables ``SLOT_PAIR`` and ``SLOT_TO_PART_KEY`` are
  disjoint — no slot can be in both or the migration would
  double-count.
"""

from caldanai.lib.rpg.creatures.equipment_routing import (
    ALL_PLACEMENTS,
    PLACEMENT_DISPLAY_ORDER,
    SLOT_PAIR,
    SLOT_TO_PART_KEY,
    keys_on_part,
    resolve_placements,
)
from caldanai.lib.rpg.creatures.player import Player, _DEFAULT_PARTS
from caldanai.lib.rpg.helpers.enums import EquipmentSlots


class TestSlotTables:
    def test_single_and_pair_tables_are_disjoint(self):
        """A slot can be in at most ONE of the two tables.
        Otherwise ``resolve_placements`` double-counts and the
        migration would place an item in too many places."""
        single_keys = set(SLOT_TO_PART_KEY.keys())
        pair_keys = set(SLOT_PAIR.keys())
        assert single_keys.isdisjoint(pair_keys), (
            f"Slots in both tables: {single_keys & pair_keys}"
        )

    def test_every_placement_part_is_in_player_anatomy(self):
        """Every ``(part, key)`` placement in the mapping tables
        must name a body part the default player actually has —
        otherwise the placement can never be filled."""
        valid_parts = set(_DEFAULT_PARTS.keys())
        for (part, key) in ALL_PLACEMENTS:
            assert part in valid_parts, (
                f"Placement ({part!r}, {key!r}) references "
                f"non-existent body part"
            )

    def test_display_order_covers_every_placement(self):
        """Nothing should be silently dropped from ``$gear`` output.
        Every placement must appear in ``PLACEMENT_DISPLAY_ORDER``."""
        display = set(PLACEMENT_DISPLAY_ORDER)
        missing = set(ALL_PLACEMENTS) - display
        assert not missing, f"Not rendered in $gear: {missing}"


class TestResolvePlacements:
    def test_head_resolves_to_head_helm(self):
        assert resolve_placements(EquipmentSlots.HEAD) == [("head", "helm")]

    def test_two_handed_resolves_to_both_arms(self):
        """``TWO_HANDED`` is ``MULTI_SLOT | LEFT_HELD | RIGHT_HELD``.
        Expand must produce both arm placements."""
        placements = resolve_placements(EquipmentSlots.TWO_HANDED)
        assert ("arm.left", "held") in placements
        assert ("arm.right", "held") in placements
        assert len(placements) == 2

    def test_gloves_compound_expands_to_both_sides(self):
        """``GLOVES`` is a compound alias (``LEFT_GLOVE | RIGHT_GLOVE``).
        The bit-test loop in ``resolve_placements`` expands it to
        both sided placements automatically. Equip treats this as
        "either side" unless ``MULTI_SLOT`` is also set (forcing
        both)."""
        placements = resolve_placements(EquipmentSlots.GLOVES)
        assert set(placements) == {("arm.left", "glove"), ("arm.right", "glove")}

    def test_single_sided_glove_resolves_only_one_side(self):
        """An item declaring just ``LEFT_GLOVE`` must NOT drag in
        the right side. The sided split is how limb-loss composes
        cleanly — a destroyed right arm drops only the right-side
        gear."""
        placements = resolve_placements(EquipmentSlots.LEFT_GLOVE)
        assert placements == [("arm.left", "glove")]

    def test_multi_slot_pair_of_gloves(self):
        """A pair of gloves that must span both sides declares
        ``GLOVES | MULTI_SLOT``. Routing resolution is the same as
        the compound alone; ``MULTI_SLOT`` changes the equip
        behavior (fill all placements vs. pick the first empty)."""
        placements = resolve_placements(
            EquipmentSlots.GLOVES | EquipmentSlots.MULTI_SLOT
        )
        assert set(placements) == {("arm.left", "glove"), ("arm.right", "glove")}

    def test_arms_compound_expands_to_both_bracer_slots(self):
        """Bracers are sided now — the ``ARMS`` compound fits
        either bracer slot, same shape as ``EITHER_HELD`` for
        weapons. One-handed "either side" semantics."""
        placements = resolve_placements(EquipmentSlots.ARMS)
        assert set(placements) == {("arm.left", "bracer"), ("arm.right", "bracer")}

    def test_multi_part_item_spans_distinct_parts(self):
        """An item declaring ``CAPE | NECK | MULTI_SLOT`` (the old
        high-collared-cape shape) occupies torso.cape AND
        neck.amulet — ``MULTI_SLOT`` stays available for this
        multi-anatomy pattern."""
        placements = resolve_placements(
            EquipmentSlots.CAPE | EquipmentSlots.NECK | EquipmentSlots.MULTI_SLOT
        )
        assert set(placements) == {("torso", "cape"), ("neck", "amulet")}

    def test_amulet_and_neck_collapse_to_same_placement(self):
        """Both AMULET and NECK route to ``(neck, amulet)``. An
        item declaring both shouldn't double-place."""
        placements = resolve_placements(
            EquipmentSlots.AMULET | EquipmentSlots.NECK
        )
        assert placements == [("neck", "amulet")]

    def test_unknown_slot_returns_empty(self):
        """MULTI_SLOT alone (no real slot in the mask) resolves
        to nothing — the flag only has meaning when OR'd with
        real slots."""
        assert resolve_placements(EquipmentSlots.MULTI_SLOT) == []


class TestSlotPairTableKeptButEmpty:
    """``SLOT_PAIR`` started as the routing shortcut for unsplit
    pair-slots (the old ``GLOVES`` / ``ARMS`` / ``FEET`` entries).
    The 2026-04-22 sided split removed those entries — compound
    aliases handle the same cases now. The table is kept as a
    mechanism for future content that truly needs a single-slot
    flag spanning multiple placements (manacles, magical sets
    that refuse to function alone). Currently empty."""

    def test_slot_pair_is_currently_empty(self):
        assert SLOT_PAIR == {}


class TestKeysOnPart:
    def test_head_part_keys(self):
        keys = set(keys_on_part("head"))
        assert keys == {"helm", "face", "ear.left", "ear.right"}

    def test_arm_left_part_keys(self):
        """Arm keys: held (weapon), bracer, vambrace, glove, ring."""
        keys = set(keys_on_part("arm.left"))
        assert keys == {"held", "bracer", "glove", "vambrace", "ring"}

    def test_leg_left_part_keys(self):
        """Leg keys: greave, shin, boot. Matches the sided split."""
        keys = set(keys_on_part("leg.left"))
        assert keys == {"greave", "shin", "boot"}

    def test_nonexistent_part_returns_empty(self):
        assert keys_on_part("tail") == []


class TestAllShippedItemsResolve:
    """Every item currently in the game must resolve to at least
    one placement. Catches a dead slot reference slipping into
    an item file."""

    def _all_item_plugins(self):
        from caldanai.lib.rpg.inventory import Inventory
        Inventory.discover_items()
        return Inventory.ITEMS

    def test_every_equippable_item_resolves(self):
        from caldanai.lib.rpg.inventory import Inventory
        from caldanai.lib.rpg.inventory.equipment import Equipment
        items = self._all_item_plugins()
        for name, cls in items.items():
            if not issubclass(cls, Equipment):
                continue
            # Instantiate cheaply via Inventory.load_item.
            instance = Inventory.load_item(name=name)
            if instance is None:
                continue
            placements = resolve_placements(instance.slots)
            assert placements, (
                f"Item {name!r} (slots={int(instance.slots)}) "
                "resolves to no placements — did a slot get "
                "deleted without updating the item?"
            )


class TestPlayerPartEquipmentInvariants:
    def test_every_placement_key_is_pre_seeded_at_init(self):
        """A fresh Player must have every valid ``(part, key)``
        pre-seeded to None so handlers can ``.get(part, {}).get(key)``
        without worrying about KeyError."""
        p = Player(uid=1, gid=2, cid=3)
        for (part_name, key) in ALL_PLACEMENTS:
            assert part_name in p.part_equipment
            assert key in p.part_equipment[part_name]
            assert p.part_equipment[part_name][key] is None

    def test_neck_part_only_has_amulet_key(self):
        """The neck is vestigial — only ``amulet`` for future
        jewelry. No other keys have been added yet."""
        p = Player(uid=1, gid=2, cid=3)
        assert set(p.part_equipment["neck"].keys()) == {"amulet"}

    def test_to_dict_omits_empty_placements(self):
        """Serialized shape must only contain non-None
        placements — we don't write a dict with every anatomy
        key at None for fresh players (would noisily bloat every
        doc)."""
        p = Player(uid=1, gid=2, cid=3)
        d = p.to_dict()
        assert d["part_equipment"] == {}
