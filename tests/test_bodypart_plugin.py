"""Tests for the Phase 1 BodyPartPlugin base class and discovery (item 1.4).

Covers:
- `BodyPartPlugin` is importable and subclasses `BodyPart`.
- A trivial in-test subclass can be defined, instantiated, and its class-level
  defaults propagate to instance attributes.
- Per-instance override kwargs (passed to ``__init__``) override class-level
  defaults.
- ``BodyPartPlugin.load_plugins()`` runs without error when no concrete plugin
  files exist under ``body_parts/`` (mirrors ``MonsterPlugin.load_plugins``
  which delegates to ``PluginManager.load``).
- ``BodyPartPlugin.get_plugin_class(name)`` returns ``None`` for unknown names.
- The base class is not registered as a loadable plugin (mirrors how
  ``PluginManager.load`` skips the base class itself).
"""

from caldanai.lib.rpg.creatures.body_parts import BodyPartPlugin
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import DamageTypes, InjuryLevels, Reach, Stat


class _TestPartPlugin(BodyPartPlugin):
    """A trivial test-only subclass used to verify class-level defaults
    propagate to instance attributes. Not registered via ``load_plugins``
    (it lives in the tests module, not the ``body_parts`` package)."""

    name = "testpart"
    health_max = 7
    is_critical = True
    traits = {DamageTypes.BLUDGEONING: 1.5}
    exposure = {Reach.MELEE: 0.5, Reach.RANGED: 0.1}
    debuffs = {InjuryLevels.MINOR: {Stat.DODGE: -1}}


class TestBodyPartPluginBase:
    def test_is_importable(self):
        assert BodyPartPlugin is not None

    def test_is_subclass_of_bodypart(self):
        assert issubclass(BodyPartPlugin, BodyPart)


class TestClassDefaultsPropagate:
    def test_name_default_propagates(self):
        part = _TestPartPlugin()
        assert part.name == "testpart"

    def test_health_max_default_propagates(self):
        part = _TestPartPlugin()
        assert part.health_max == 7
        # health is initialized to health_max by BodyPart.__init__
        assert part.health == 7

    def test_is_critical_default_propagates(self):
        part = _TestPartPlugin()
        assert part.is_critical is True

    def test_traits_default_propagates(self):
        part = _TestPartPlugin()
        assert part.traits == {DamageTypes.BLUDGEONING: 1.5}

    def test_exposure_default_propagates(self):
        part = _TestPartPlugin()
        assert part.exposure == {Reach.MELEE: 0.5, Reach.RANGED: 0.1}

    def test_debuffs_default_propagates(self):
        part = _TestPartPlugin()
        assert part.debuffs == {InjuryLevels.MINOR: {Stat.DODGE: -1}}


class TestPerInstanceOverrides:
    def test_name_override_kwarg_wins(self):
        part = _TestPartPlugin(name="custom")
        assert part.name == "custom"

    def test_health_max_override_kwarg_wins(self):
        part = _TestPartPlugin(health_max=42)
        assert part.health_max == 42
        assert part.health == 42

    def test_is_critical_override_kwarg_wins(self):
        part = _TestPartPlugin(is_critical=False)
        assert part.is_critical is False

    def test_exposure_override_kwarg_wins(self):
        override = {Reach.MELEE: 1.0}
        part = _TestPartPlugin(exposure=override)
        assert part.exposure == override

    def test_debuffs_override_kwarg_wins(self):
        override = {InjuryLevels.SEVERE: {Stat.ATTACK: -5}}
        part = _TestPartPlugin(debuffs=override)
        assert part.debuffs == override

    def test_traits_override_kwarg_wins(self):
        override = {DamageTypes.SLASHING: 2.0}
        part = _TestPartPlugin(traits=override)
        assert part.traits == override

    def test_other_defaults_still_apply_when_only_one_kwarg_overridden(self):
        part = _TestPartPlugin(name="custom")
        # name got overridden ...
        assert part.name == "custom"
        # ... but the other class-level defaults are still applied.
        assert part.health_max == 7
        assert part.is_critical is True


class TestLoadPlugins:
    def test_load_plugins_runs_without_error_when_no_plugin_files(self):
        """There are no concrete plugin files under ``body_parts/`` yet
        (items 2.1-2.9 haven't been implemented). ``load_plugins`` should
        still complete cleanly."""
        BodyPartPlugin.load_plugins()  # must not raise

    def test_load_plugins_does_not_register_base_class(self):
        """The base class itself must not appear in the registry -- mirrors
        how ``PluginManager.load`` skips the base type."""
        BodyPartPlugin.load_plugins()
        assert BodyPartPlugin.get_plugin_class("bodypartplugin") is None


class TestGetPluginClass:
    def test_unknown_name_returns_none(self):
        BodyPartPlugin.load_plugins()
        assert BodyPartPlugin.get_plugin_class("not_a_real_part") is None

    def test_returns_none_before_load(self):
        """Even before ``load_plugins`` runs, an unknown lookup returns
        ``None`` rather than raising."""
        assert BodyPartPlugin.get_plugin_class("definitely_not_there") is None
