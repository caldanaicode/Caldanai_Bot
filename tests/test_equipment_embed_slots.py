"""The ``$item`` embed's ``Slots`` field must display the
``part.key`` placement labels players see in ``$gear`` /
``$unequip`` rather than the pre-migration enum names
(``HEAD`` / ``LEFT_HELD`` / etc.). Multi-slot items (two-handed
weapons, paired gear) occupy every placement simultaneously and
are rendered with ``+`` so the reader knows it IS both; single-
slot items with multiple compatible placements render with ``|``
to signal EITHER.
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
    def test_cape_shows_torso_cape(self):
        assert _slots_field("cape") == "torso.cape"

    def test_mushroom_hat_shows_head_helm(self):
        assert _slots_field("mushroom_hat") == "head.helm"

    def test_tee_shirt_shows_torso_chest(self):
        assert _slots_field("tee_shirt") == "torso.chest"

    def test_bandanna_shows_head_face(self):
        assert _slots_field("bandanna") == "head.face"

    def test_high_collared_cape_is_single_slot_torso_cape(self):
        """Post-migration, high-collared cape lost its NECK flag —
        it's a single-slot CAPE item. Embed must reflect that."""
        assert _slots_field("high-collared_cape") == "torso.cape"


class TestEitherSlotItems:
    def test_shortsword_uses_or_separator(self):
        """A one-handed weapon goes in EITHER arm — the reader
        should see the OR distinction, not the AND ``+``."""
        value = _slots_field("shortsword")
        assert "arm.left.held" in value
        assert "arm.right.held" in value
        assert " | " in value
        assert "+" not in value


class TestMultiSlotItems:
    def test_spear_uses_plus_separator(self):
        """Two-handed weapons occupy BOTH arm.held placements — the
        ``+`` separator signals simultaneous occupation."""
        value = _slots_field("spear")
        assert value == "arm.left.held + arm.right.held"

    def test_bow_uses_plus_separator(self):
        value = _slots_field("bow")
        assert value == "arm.left.held + arm.right.held"
