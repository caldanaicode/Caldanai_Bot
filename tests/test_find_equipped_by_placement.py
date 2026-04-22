"""Tests for ``Player.find_equipped_by_placement`` — the resolver
behind ``$stow`` / ``$unequip``'s placement-query input.

Three input shapes must all work:

- Full ``part.key`` (``head.helm``, ``arm.left.held``,
  ``torso.cape``) — canonical form.
- Bare key (``helm``, ``cape``, ``held``) — quality-of-life
  shortcut so players don't have to type the part name.
- Key-with-dots (``ear.left``, matches ``head.ear.left``) — a
  bare-key match that happens to contain a dot.

Ambiguous bare keys (``held`` with both arms occupied) resolve
to the first :data:`PLACEMENT_DISPLAY_ORDER` match — left arm.
Two-handed weapons share the same ``Item`` instance across both
arms, so the returned object is the same regardless of which arm
the resolver picks first.
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.player import Player
from caldanai.lib.rpg.inventory import Inventory


BodyPartPlugin.load_plugins()
Inventory.discover_items()


def _fresh_player() -> Player:
    return Player(uid=1, gid=2, cid=3)


def _equip(player: Player, plugin_name: str):
    item = Inventory.load_item(name=plugin_name)
    assert item is not None, f"unknown plugin {plugin_name!r}"
    player.inventory.add(item)
    ok, _ = player.equip(item)
    assert ok, f"could not equip {plugin_name!r}"
    return item


class TestFullPartKey:
    def test_head_helm(self):
        p = _fresh_player()
        hat = _equip(p, "mushroom_hat")
        assert p.find_equipped_by_placement("head.helm") is hat

    def test_arm_left_held(self):
        p = _fresh_player()
        sword = _equip(p, "shortsword")
        assert p.find_equipped_by_placement("arm.left.held") is sword

    def test_torso_cape(self):
        p = _fresh_player()
        cape = _equip(p, "cape")
        assert p.find_equipped_by_placement("torso.cape") is cape

    def test_empty_placement_returns_none(self):
        p = _fresh_player()
        assert p.find_equipped_by_placement("head.helm") is None


class TestBareKey:
    def test_helm_finds_hat(self):
        p = _fresh_player()
        hat = _equip(p, "mushroom_hat")
        assert p.find_equipped_by_placement("helm") is hat

    def test_cape_finds_cape(self):
        p = _fresh_player()
        cape = _equip(p, "cape")
        assert p.find_equipped_by_placement("cape") is cape

    def test_held_single_weapon_finds_it(self):
        p = _fresh_player()
        sword = _equip(p, "shortsword")
        assert p.find_equipped_by_placement("held") is sword

    def test_held_ambiguous_picks_left_first(self):
        """Both hands occupied: the display-order tie-break says
        arm.left wins. Caller can make a second call (and the
        first was presumably already un-equipped) to get right."""
        p = _fresh_player()
        left = _equip(p, "shortsword")
        # second shortsword — distinct Item instance
        right_item = Inventory.load_item(name="mace")
        p.inventory.add(right_item)
        p.equip(right_item)
        found = p.find_equipped_by_placement("held")
        # Left arm's item resolves first.
        assert found is left

    def test_empty_bare_key_returns_none(self):
        p = _fresh_player()
        assert p.find_equipped_by_placement("helm") is None


class TestTwoHandedWeapon:
    def test_two_handed_bare_key_resolves_to_shared_instance(self):
        """Two-handers share their ``Item`` ref at both arms.
        Looking up ``held`` (anatomy-first match) returns the
        same instance as ``arm.right.held`` because it IS the
        same instance."""
        p = _fresh_player()
        spear = _equip(p, "spear")
        assert p.find_equipped_by_placement("held") is spear
        assert p.find_equipped_by_placement("arm.left.held") is spear
        assert p.find_equipped_by_placement("arm.right.held") is spear


class TestKeyWithDots:
    """Keys that contain dots (``ear.left``, ``ear.right``) must
    still resolve via the bare-key scan even though the query
    splits into multiple tokens."""

    def test_ear_left_matches_head_ear_left(self):
        """No item shipped for ears yet — verify the resolver at
        least doesn't crash and returns None gracefully for empty
        slots."""
        p = _fresh_player()
        # No ear items exist; bare-key scan should find the
        # placement key exists but be empty → None.
        assert p.find_equipped_by_placement("ear.left") is None


class TestEdgeCases:
    def test_empty_string_returns_none(self):
        assert _fresh_player().find_equipped_by_placement("") is None

    def test_whitespace_only_returns_none(self):
        assert _fresh_player().find_equipped_by_placement("   ") is None

    def test_unknown_placement_returns_none(self):
        p = _fresh_player()
        _equip(p, "mushroom_hat")
        assert p.find_equipped_by_placement("nonsense.bogus") is None

    def test_case_insensitive_bare_key(self):
        p = _fresh_player()
        hat = _equip(p, "mushroom_hat")
        assert p.find_equipped_by_placement("HELM") is hat
        assert p.find_equipped_by_placement("Helm") is hat

    def test_case_insensitive_full_placement(self):
        p = _fresh_player()
        sword = _equip(p, "shortsword")
        assert p.find_equipped_by_placement("ARM.LEFT.HELD") is sword
