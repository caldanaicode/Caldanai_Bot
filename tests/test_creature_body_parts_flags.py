"""Tests for Creature.body_parts and Creature.flags per-instance attributes.

Item 1.7: Creature gains two new per-instance attributes in ``__init__``:
- ``body_parts: List[BodyPart]`` — empty by default; subclasses populate in
  their own ``__init__`` after calling ``super().__init__(...)``.
- ``flags: Set[str]`` — empty by default; discrete state flags such as
  ``"flying"`` that downstream code (e.g. dragon toes) inspects.

The load-bearing property tested here is **per-instance independence**:
mutating one creature's ``body_parts`` or ``flags`` must NOT leak to any
other creature. Shared mutable state would mean injuring one goblin's leg
injures every goblin.
"""

from typing import List, Set, get_type_hints

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_creature(**kwargs) -> Creature:
    """Create a Creature with sensible defaults; kwargs override."""
    defaults = dict(
        name="goblin",
        atk="1d4",
        defense=2,
        dodge=5,
        health_max=20,
        health=20,
        gender="male",
    )
    defaults.update(kwargs)
    return Creature(**defaults)


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

class TestBodyPartsDefault:
    def test_body_parts_defaults_to_empty_list(self):
        c = _make_creature()
        assert c.body_parts == []

    def test_body_parts_is_a_list(self):
        c = _make_creature()
        assert isinstance(c.body_parts, list)


class TestFlagsDefault:
    def test_flags_defaults_to_empty_set(self):
        c = _make_creature()
        assert c.flags == set()

    def test_flags_is_a_set(self):
        c = _make_creature()
        assert isinstance(c.flags, set)


# ---------------------------------------------------------------------------
# Per-instance independence (load-bearing)
# ---------------------------------------------------------------------------

class TestPerInstanceIndependence:
    def test_body_parts_are_independent_between_instances(self):
        a = _make_creature(name="goblin a")
        b = _make_creature(name="goblin b")

        # Distinct list objects.
        assert a.body_parts is not b.body_parts

        # Mutating one must not affect the other.
        part = BodyPart(name="leg.left", health_max=8)
        a.body_parts.append(part)

        assert len(a.body_parts) == 1
        assert b.body_parts == []
        assert len(b.body_parts) == 0

    def test_flags_are_independent_between_instances(self):
        a = _make_creature(name="dragon a")
        b = _make_creature(name="dragon b")

        # Distinct set objects.
        assert a.flags is not b.flags

        # Mutating one must not affect the other.
        a.flags.add("flying")

        assert "flying" in a.flags
        assert "flying" not in b.flags
        assert b.flags == set()

    def test_body_parts_not_shared_via_class_attribute(self):
        """Regression guard: appending to an instance must not mutate any
        hypothetical class-level default."""
        a = _make_creature()
        a.body_parts.append(BodyPart(name="head", health_max=10))

        # A fresh instance must still start empty.
        c = _make_creature()
        assert c.body_parts == []

    def test_flags_not_shared_via_class_attribute(self):
        a = _make_creature()
        a.flags.add("burning")

        c = _make_creature()
        assert c.flags == set()


# ---------------------------------------------------------------------------
# Type / usage smoke tests
# ---------------------------------------------------------------------------

class TestBodyPartAcceptance:
    def test_body_parts_accepts_a_bodypart_instance(self):
        """Smoke test: a subclass constructor can append a BodyPart."""
        c = _make_creature()
        part = BodyPart(name="arm.right", health_max=6)
        c.body_parts.append(part)

        assert c.body_parts == [part]
        assert isinstance(c.body_parts[0], BodyPart)


class TestFlagsMembership:
    def test_flags_supports_string_membership_check(self):
        c = _make_creature()
        assert "flying" not in c.flags

        c.flags.add("flying")
        assert "flying" in c.flags

    def test_flags_supports_discard(self):
        c = _make_creature()
        c.flags.add("flying")
        c.flags.discard("flying")
        assert "flying" not in c.flags


# ---------------------------------------------------------------------------
# Backwards compatibility
# ---------------------------------------------------------------------------

class TestBackwardsCompat:
    def test_existing_constructor_args_still_work(self):
        """Constructing a Creature with only the pre-1.7 args should still
        succeed, and the two new attributes should default empty."""
        c = Creature(
            name="goblin",
            atk="1d4",
            defense=2,
            dodge=5,
            health_max=20,
            health=20,
            gender="male",
        )
        assert c.body_parts == []
        assert c.flags == set()

    def test_minimal_construction_still_works(self):
        """Only the required positional args — verify the new attributes
        default cleanly without any extra kwargs."""
        c = Creature(
            name="x",
            atk="1d4",
            defense=1,
            dodge=1,
            health_max=1,
        )
        assert c.body_parts == []
        assert c.flags == set()
