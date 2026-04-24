"""The ``$item`` embed's ``Slots`` field must display the
``part.key`` placement labels players see in ``$gear`` /
``$unequip`` rather than the pre-migration enum names
(``HEAD`` / ``LEFT_HELD`` / etc.). Multi-slot items (two-handed
weapons, paired gear) occupy every placement simultaneously and
are rendered with ``+`` so the reader knows it IS both; single-
slot items with multiple compatible placements render with ``|``
to signal EITHER.

Phase D updated placements to generic-key vocabulary
(worn/held/outer/accent) with segmented hand/foot anatomy.
"""

from caldanai.lib.rpg.inventory import Inventory


Inventory.discover_items()


def _slots_field(name: str) -> str:
    item = Inventory.load_item(name=name)
    assert item is not None, f"item plugin {name!r} not found"
    embed, _ = item.get_embed()
    field = next((f for f in embed.fields if f.name == "Slots"), None)
    assert field is not None, f"{name!r} embed has no Slots field"
    return field.value


class TestSingleSlotItems:
    def test_cape_shows_torso_outer(self):
        assert _slots_field("cape") == "torso.outer"

    def test_mushroom_hat_shows_head_worn(self):
        assert _slots_field("mushroom_hat") == "head.worn"

    def test_tee_shirt_shows_torso_worn(self):
        assert _slots_field("tee_shirt") == "torso.worn"

    def test_bandanna_shows_head_outer(self):
        assert _slots_field("bandanna") == "head.outer"

    def test_high_collared_cape_is_single_slot_torso_outer(self):
        """Post-migration, high-collared cape lost its NECK flag —
        it's a single-slot CAPE item. Embed must reflect that."""
        assert _slots_field("high-collared_cape") == "torso.outer"


class TestEitherSlotItems:
    def test_shortsword_uses_or_separator(self):
        """A one-handed weapon goes in EITHER hand — the reader
        should see the OR distinction, not the AND ``+``.
        Phase D: weapons live on hand.*.held, not arm.*.held."""
        value = _slots_field("shortsword")
        assert "hand.left.held" in value
        assert "hand.right.held" in value
        assert " | " in value
        assert "+" not in value


class TestMultiSlotItems:
    def test_spear_uses_plus_separator(self):
        """Two-handed weapons occupy BOTH hand.held placements — the
        ``+`` separator signals simultaneous occupation."""
        value = _slots_field("spear")
        assert value == "hand.left.held + hand.right.held"

    def test_bow_uses_plus_separator(self):
        value = _slots_field("bow")
        assert value == "hand.left.held + hand.right.held"
