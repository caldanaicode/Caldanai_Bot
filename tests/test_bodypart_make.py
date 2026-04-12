"""Tests for the Phase 1 ``BodyPart.make`` factory (item 1.5).

Covers:
- Happy-path lookup returns an instance of the registered plugin class
  with class-level defaults propagated.
- Per-instance kwarg overrides are applied to the constructed instance.
- Unknown plugin names raise ``ValueError`` with a helpful message.
- Lazy loading: an empty registry triggers a single ``load_plugins`` call
  before the lookup is retried.
- Dice-notation ``health_max`` strings (e.g. ``"1d8"``) are resolved to
  integers at construction time, matching Creature's behavior.
- Per-instance isolation: two factory calls return distinct instances
  with independent ``traits`` / ``exposure`` / ``debuffs`` dicts.
"""

from unittest.mock import patch

import pytest

from Caldanai.lib.rpg.creatures.bodypart import BodyPart
from Caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from Caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach, Stat


class _FactoryTestPart(BodyPartPlugin):
    """A trivial test-only plugin subclass. It is *not* auto-discovered
    via ``load_plugins`` (it lives in the tests module, not under
    ``body_parts/``); the tests register it manually on the registry."""

    name = "test_part"
    health_max = 5
    is_critical = False
    traits = {DamageTypes.SLASHING: 1.25}
    exposure = {Reach.MELEE: 0.8, Reach.RANGED: 0.2}
    debuffs = {InjuryLevels.MINOR: {Stat.DODGE: -1}}


class _DiceHealthPart(BodyPartPlugin):
    """Plugin whose ``health_max`` is an ndn string, as the design doc
    examples write (``health_max = "1d10"``)."""

    name = "dice_part"
    health_max = "1d8"


@pytest.fixture
def registered_test_parts():
    """Snapshot/restore the plugin registry so tests can poke at it
    without leaking state into other test modules."""
    original = dict(BodyPartPlugin._PLUGIN_REGISTRY)
    BodyPartPlugin._PLUGIN_REGISTRY = {
        "test_part": _FactoryTestPart,
        "dice_part": _DiceHealthPart,
    }
    try:
        yield
    finally:
        BodyPartPlugin._PLUGIN_REGISTRY = original


@pytest.fixture
def empty_registry():
    """Snapshot/restore the plugin registry, wiping it before the test."""
    original = dict(BodyPartPlugin._PLUGIN_REGISTRY)
    BodyPartPlugin._PLUGIN_REGISTRY = {}
    try:
        yield
    finally:
        BodyPartPlugin._PLUGIN_REGISTRY = original


class TestHappyPath:
    def test_make_returns_instance_of_plugin_class(self, registered_test_parts):
        part = BodyPart.make("test_part")
        assert isinstance(part, _FactoryTestPart)
        assert isinstance(part, BodyPart)

    def test_make_propagates_class_defaults(self, registered_test_parts):
        part = BodyPart.make("test_part")
        assert part.name == "test_part"
        assert part.health_max == 5
        assert part.health == 5
        assert part.is_critical is False
        assert part.traits == {DamageTypes.SLASHING: 1.25}
        assert part.exposure == {Reach.MELEE: 0.8, Reach.RANGED: 0.2}
        assert part.debuffs == {InjuryLevels.MINOR: {Stat.DODGE: -1}}


class TestOverrides:
    def test_name_override(self, registered_test_parts):
        part = BodyPart.make("test_part", name="custom")
        assert part.name == "custom"

    def test_is_critical_override(self, registered_test_parts):
        part = BodyPart.make("test_part", is_critical=True)
        assert part.is_critical is True

    def test_multiple_overrides_together(self, registered_test_parts):
        part = BodyPart.make(
            "test_part",
            name="custom",
            is_critical=True,
            exposure={Reach.MELEE: 0.05, Reach.RANGED: 1.0},
        )
        assert part.name == "custom"
        assert part.is_critical is True
        assert part.exposure == {Reach.MELEE: 0.05, Reach.RANGED: 1.0}

    def test_unoverridden_fields_still_use_class_defaults(
        self, registered_test_parts
    ):
        part = BodyPart.make("test_part", name="custom")
        # name overridden ...
        assert part.name == "custom"
        # ... but health_max (etc.) still comes from the class default.
        assert part.health_max == 5
        assert part.traits == {DamageTypes.SLASHING: 1.25}

    def test_plugin_name_positional_does_not_collide_with_name_override(
        self, registered_test_parts
    ):
        """Regression test for a parameter-collision bug in ``make``.

        The factory's positional argument is the plugin registry key, but
        ``name`` is also a valid per-instance override forwarded to the
        plugin's ``__init__`` (the design doc's dragon example literally
        does ``BodyPart.make("head", name="head", ...)``).

        Early versions of the factory named the positional ``name``,
        which caused ``TypeError: got multiple values for argument
        'name'`` the moment a caller tried to override the instance
        name. The positional must therefore be called something else
        (currently ``plugin_name``). This test pins that contract so
        nobody accidentally renames it back.
        """
        part = BodyPart.make("test_part", name="custom")
        assert part.name == "custom"
        # And it must still be an instance of the plugin class resolved
        # from the positional registry key.
        assert isinstance(part, _FactoryTestPart)


class TestUnknownName:
    def test_unknown_name_raises_value_error(self, registered_test_parts):
        with pytest.raises(ValueError):
            BodyPart.make("no_such_part")

    def test_value_error_message_mentions_the_name(self, registered_test_parts):
        with pytest.raises(ValueError, match="no_such_part"):
            BodyPart.make("no_such_part")

    def test_value_error_message_mentions_known_plugins(
        self, registered_test_parts
    ):
        with pytest.raises(ValueError, match="test_part"):
            BodyPart.make("no_such_part")


class TestLazyLoading:
    def test_empty_registry_triggers_load_plugins(self, empty_registry):
        """If the registry is empty when ``make`` is called, the factory
        should invoke ``load_plugins`` exactly once before giving up."""
        call_count = {"n": 0}
        real_load = BodyPartPlugin.load_plugins

        def fake_load():
            call_count["n"] += 1
            # Simulate discovery populating the registry.
            BodyPartPlugin._PLUGIN_REGISTRY["test_part"] = _FactoryTestPart

        with patch.object(BodyPartPlugin, "load_plugins", side_effect=fake_load):
            part = BodyPart.make("test_part")

        assert call_count["n"] == 1
        assert isinstance(part, _FactoryTestPart)
        # Restore real method (patch already handles this, but be explicit
        # about not leaking state).
        BodyPartPlugin.load_plugins = real_load  # type: ignore[method-assign]

    def test_populated_registry_does_not_reload(self, registered_test_parts):
        """If the registry already contains plugins, ``make`` must not
        call ``load_plugins`` at all -- otherwise tests that pre-seed the
        registry would have it clobbered."""
        with patch.object(BodyPartPlugin, "load_plugins") as mock_load:
            BodyPart.make("test_part")
            mock_load.assert_not_called()

    def test_lazy_load_still_raises_if_name_missing_after_load(
        self, empty_registry
    ):
        """If ``load_plugins`` runs but the requested name is still not
        registered, the factory raises ``ValueError`` as usual."""
        with patch.object(BodyPartPlugin, "load_plugins"):
            with pytest.raises(ValueError, match="ghost_part"):
                BodyPart.make("ghost_part")


class TestDiceHealthMax:
    def test_dice_string_health_max_resolves_to_int(self, registered_test_parts):
        part = BodyPart.make("dice_part")
        assert isinstance(part.health_max, int)
        # 1d8 -> [1, 8]
        assert 1 <= part.health_max <= 8
        # health is initialized to the resolved integer health_max
        assert part.health == part.health_max

    def test_dice_string_health_max_multiple_instances_independent(
        self, registered_test_parts
    ):
        """Each call to ``make`` should roll its own ``health_max``
        (i.e. the roll happens per-instance, not once at class level)."""
        # 20 rolls of 1d8 is overwhelmingly likely to produce at least
        # two distinct values if the roll is actually per-instance. A
        # false positive here is ~8 * (1/8)**19, i.e. effectively zero.
        values = {BodyPart.make("dice_part").health_max for _ in range(20)}
        assert len(values) > 1


class TestPerInstanceIsolation:
    def test_two_instances_are_distinct_objects(self, registered_test_parts):
        a = BodyPart.make("test_part")
        b = BodyPart.make("test_part")
        assert a is not b

    def test_traits_dict_is_not_shared_between_instances(
        self, registered_test_parts
    ):
        a = BodyPart.make("test_part")
        b = BodyPart.make("test_part")
        assert a.traits is not b.traits
        a.traits[DamageTypes.FIRE] = 0.5
        assert DamageTypes.FIRE not in b.traits

    def test_exposure_dict_is_not_shared_between_instances(
        self, registered_test_parts
    ):
        a = BodyPart.make("test_part")
        b = BodyPart.make("test_part")
        assert a.exposure is not b.exposure
        a.exposure[Reach.THROWN] = 0.0
        assert Reach.THROWN not in b.exposure

    def test_debuffs_dict_is_not_shared_between_instances(
        self, registered_test_parts
    ):
        a = BodyPart.make("test_part")
        b = BodyPart.make("test_part")
        assert a.debuffs is not b.debuffs
        a.debuffs[InjuryLevels.SEVERE] = {Stat.ATTACK: -99}
        assert InjuryLevels.SEVERE not in b.debuffs

    def test_health_damage_does_not_leak_between_instances(
        self, registered_test_parts
    ):
        a = BodyPart.make("test_part")
        b = BodyPart.make("test_part")
        a.health = 0
        assert b.health == b.health_max
