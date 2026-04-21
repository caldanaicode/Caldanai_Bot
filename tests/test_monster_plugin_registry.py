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


class TestAliasRegistrations:
    """Q.6.3-followup: plugins with ``ALIASES`` declared have each
    alias registered alongside the filename stem, so both the API
    stem and the in-fiction display name resolve via exact lookup."""

    def test_math_teacher_display_name_alias(self):
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        assert MonsterPlugin.get_plugin_class("flying math teacher") is MathTeacher
        # Stem still works.
        assert MonsterPlugin.get_plugin_class("math_teacher") is MathTeacher

    def test_hydra_variant_names_all_resolve(self):
        from caldanai.lib.rpg.creatures.monsters.hydra import Hydra
        for alias in ("hydra", "swamp hydra", "hexed hydra", "elemental hydra"):
            assert MonsterPlugin.get_plugin_class(alias) is Hydra, (
                f"alias {alias!r} did not resolve"
            )

    def test_alias_is_case_insensitive(self):
        from caldanai.lib.rpg.creatures.monsters.hydra import Hydra
        assert MonsterPlugin.get_plugin_class("SWAMP HYDRA") is Hydra
        assert MonsterPlugin.get_plugin_class("Swamp Hydra") is Hydra


class TestFindPluginClasses:
    """Fuzzy lookup used by ``Game.do_spawn`` when the exact-stem +
    alias lookup misses. Two-pass design mirrors
    ``Creature.find_parts``: prefix, then substring fallback."""

    def test_empty_query_returns_empty(self):
        assert MonsterPlugin.find_plugin_classes("") == []
        assert MonsterPlugin.find_plugin_classes("   ") == []

    def test_exact_match_returns_single_class(self):
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        result = MonsterPlugin.find_plugin_classes("goblin")
        assert result == [Goblin]

    def test_prefix_partial_resolves_unique(self):
        """``gobl`` → Goblin (no other plugin starts with "gobl")."""
        from caldanai.lib.rpg.creatures.monsters.goblin import Goblin
        result = MonsterPlugin.find_plugin_classes("gobl")
        assert result == [Goblin]

    def test_hydra_query_dedupes_across_aliases(self):
        """"hydra" prefix-matches the stem AND every variant alias
        (all registered). Dedupe must collapse to one class."""
        from caldanai.lib.rpg.creatures.monsters.hydra import Hydra
        result = MonsterPlugin.find_plugin_classes("hydra")
        assert result == [Hydra]

    def test_two_token_query_resolves_display_name(self):
        """``math teacher`` should resolve to MathTeacher via prefix
        across both tokens."""
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        result = MonsterPlugin.find_plugin_classes("math teacher")
        assert MathTeacher in result

    def test_substring_fallback_when_prefix_empty(self):
        """No plugin starts with ``eacher`` so prefix returns empty;
        substring fallback catches "math_teacher" / "flying math
        teacher" via the second token."""
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        result = MonsterPlugin.find_plugin_classes("flying eacher")
        assert MathTeacher in result

    def test_dot_separator_normalized_to_whitespace(self):
        """``math.teacher`` (as a body-part-style reach) still
        resolves — dots tokenize the same as spaces."""
        from caldanai.lib.rpg.creatures.monsters.math_teacher import MathTeacher
        result = MonsterPlugin.find_plugin_classes("math.teacher")
        assert MathTeacher in result

    def test_unknown_query_returns_empty(self):
        assert MonsterPlugin.find_plugin_classes("not_a_monster_xyz") == []

    def test_query_with_only_unresolvable_token_returns_empty(self):
        """``xyzzy`` matches nothing in any pass."""
        assert MonsterPlugin.find_plugin_classes("xyzzy") == []
