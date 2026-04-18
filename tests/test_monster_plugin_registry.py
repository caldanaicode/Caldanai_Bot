"""Tests for the ``MonsterPlugin._PLUGIN_REGISTRY`` /
``MonsterPlugin.get_plugin_class`` lookup that replaced the
per-call filesystem glob in ``Game.get_monster``.

Covers:
- ``get_plugin_class`` returns the expected class for known filenames
  (including the underscore case ``math_teacher`` where filename and
  class ``__name__`` diverge).
- Case-insensitive matching — ``"goblin"``, ``"Goblin"``, and
  ``"GOBLIN"`` all resolve to the same class, matching the pre-refactor
  filesystem-scan semantics (which lowercased both sides).
- Unknown names return ``None`` (same external "miss" behavior that
  ``Game.get_monster`` translates into the user-facing error dispatch).
- Every discovered monster class can be round-tripped through the
  registry — parametrized over ``PluginManager.LOADED_PLUGINS``.
- The base class itself is not in the registry (``PluginManager`` skips
  the base type at load).
"""

import pytest

from caldanai import PluginManager
from caldanai.lib.rpg.creatures.monsters import MonsterPlugin


# Make sure the registry is populated for every test in this module,
# regardless of the order tests happen to run in.
MonsterPlugin.load_plugins()
ALL_MONSTERS = list(PluginManager.LOADED_PLUGINS.get(MonsterPlugin, []))
MONSTER_IDS = [cls.__name__ for cls in ALL_MONSTERS]


class TestGetPluginClassKnownNames:
    def test_goblin_lookup(self):
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        assert MonsterPlugin.get_plugin_class("goblin") is Goblin

    def test_dragon_lookup(self):
        from caldanai.lib.rpg.creatures.monsters.dragon import Dragon
        assert MonsterPlugin.get_plugin_class("dragon") is Dragon

    def test_underscored_filename_lookup(self):
        """``math_teacher.py`` defines class ``MathTeacher``; the key is
        the filename stem, so the lookup must accept ``math_teacher``
        (not ``mathteacher``). This is the exact token the pre-refactor
        filesystem scan accepted."""
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        assert MonsterPlugin.get_plugin_class("math_teacher") is MathTeacher


class TestGetPluginClassCaseInsensitive:
    """The pre-refactor filesystem scan lowercased both the available
    filenames and the input (``monster.lower() in available_monsters``),
    so it matched regardless of input casing. Preserve that."""

    def test_mixed_case_input_matches(self):
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        assert MonsterPlugin.get_plugin_class("Goblin") is Goblin

    def test_all_upper_input_matches(self):
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        assert MonsterPlugin.get_plugin_class("GOBLIN") is Goblin

    def test_mixed_case_on_underscored_filename(self):
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        assert MonsterPlugin.get_plugin_class("Math_Teacher") is MathTeacher


class TestGetPluginClassUnknownNames:
    def test_unknown_name_returns_none(self):
        assert MonsterPlugin.get_plugin_class("definitely_not_a_monster") is None

    def test_empty_string_returns_none(self):
        assert MonsterPlugin.get_plugin_class("") is None

    def test_class_name_of_base_is_not_in_registry(self):
        """``MonsterPlugin`` itself must not be addressable as a plugin
        — ``PluginManager.load`` skips the base type at load time."""
        assert MonsterPlugin.get_plugin_class("monsterplugin") is None
        assert MonsterPlugin.get_plugin_class("__init__") is None


@pytest.mark.parametrize("cls", ALL_MONSTERS, ids=MONSTER_IDS)
class TestEveryDiscoveredMonsterIsReachable:
    """For every class in the loaded-plugin list, the registry must
    accept the filename stem and hand back the same class. If a new
    monster file is added and this test fails, the registry and the
    loaded-plugin list are out of sync."""

    def test_filename_stem_resolves_to_class(self, cls):
        filename_stem = cls.__module__.rsplit(".", 1)[-1].lower()
        assert MonsterPlugin.get_plugin_class(filename_stem) is cls

    def test_filename_stem_resolves_case_insensitively(self, cls):
        filename_stem = cls.__module__.rsplit(".", 1)[-1]
        assert MonsterPlugin.get_plugin_class(filename_stem.upper()) is cls
