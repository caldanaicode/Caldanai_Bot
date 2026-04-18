"""Tests for the ``Creature.get_target_part_preference`` targeting hook.

Most creatures return ``None`` — "no preference" — and fall back to
exposure-weighted random targeting (the baseline "dumb" striking
behavior). Predatory / tactical monsters can override to bias their
targeting toward vulnerable parts; an honored preference pays the
exposure tax on dodge the same way a player's explicit target does.
"""

from unittest.mock import patch

import pytest

from caldanai.lib.rpg.combat.attack_source import NaturalAttackSource
from caldanai.lib.rpg.creatures import Creature, EXPOSURE_FLOOR
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import Reach


def _make_creature(name="mob", atk="1d4", defense=0, dodge=8,
                   health_max=100, body_parts=None):
    c = Creature(name=name, atk=atk, defense=defense, dodge=dodge,
                 health_max=health_max)
    if body_parts:
        c.body_parts = body_parts
    return c


def _full_exposure():
    return {
        Reach.MELEE:  1.0,
        Reach.REACH:  1.0,
        Reach.THROWN: 1.0,
        Reach.RANGED: 1.0,
    }


def _make_part(name="torso", health_max=50, is_critical=False, exposure=None):
    return BodyPart(
        name=name,
        health_max=health_max,
        is_critical=is_critical,
        exposure=exposure,
    )


class TestDefaultHook:
    def test_default_preference_is_none(self):
        attacker = _make_creature("wolf")
        target = _make_creature("prey", body_parts=[_make_part("torso")])
        sources = attacker.get_attack_sources()
        assert attacker.get_target_part_preference(target, sources[0]) is None


class TestPreferenceIsHonored:
    def test_preferred_part_becomes_target(self):
        """When a preference names a valid, non-destroyed part, that
        part becomes the attack's target_part."""
        head = _make_part("head", exposure=_full_exposure())
        torso = _make_part("torso", exposure=_full_exposure())
        target = _make_creature("prey", body_parts=[head, torso])

        attacker = _make_creature("predator")
        with patch.object(
            Creature, "get_target_part_preference", return_value="head"
        ):
            seq = attacker.do_attack(target)
        assert seq.results[0].target_part is head

    def test_preferred_part_scales_dodge_like_explicit_target(self):
        """An honored preference against a low-exposure part scales
        dodge the same way a player's explicit target would."""
        hard_head = _make_part("head", health_max=20)
        hard_head.exposure = _full_exposure()
        hard_head.exposure[Reach.MELEE] = 0.5  # half-exposed to melee
        target = _make_creature("prey", dodge=8, body_parts=[hard_head])
        target.get_dodge = lambda: 8

        attacker = _make_creature("predator")
        with patch.object(
            Creature, "get_target_part_preference", return_value="head"
        ):
            seq = attacker.do_attack(target)
        # effective_dodge = 8 / 0.5 = 16, vs base 8
        assert seq.results[0].dodge == 16


class TestPreferenceFallback:
    def test_unknown_preference_falls_back_to_random(self):
        """If the preference names a part the target doesn't have, the
        attack should still land somewhere (random targeting kicks in
        rather than no-op or crash)."""
        torso = _make_part("torso", exposure=_full_exposure())
        target = _make_creature("prey", body_parts=[torso])

        attacker = _make_creature("predator")
        with patch.object(
            Creature, "get_target_part_preference", return_value="wing.left"
        ):
            seq = attacker.do_attack(target)
        # Should have resolved SOMETHING (the only targetable part).
        assert seq.results[0].target_part is torso

    def test_destroyed_preferred_part_falls_back_to_random(self):
        """If the preferred part exists but is already destroyed, we
        fall back to exposure-weighted random selection among the
        remaining parts. The preference isn't a hard lock — predators
        adapt."""
        head = _make_part("head", health_max=10, exposure=_full_exposure())
        head.health = 0  # destroyed
        torso = _make_part("torso", health_max=50, exposure=_full_exposure())
        target = _make_creature("prey", body_parts=[head, torso])
        target.get_dodge = lambda: 8

        attacker = _make_creature("predator")
        with patch.object(
            Creature, "get_target_part_preference", return_value="head"
        ):
            seq = attacker.do_attack(target)
        # Head is destroyed → random fallback → torso is the only
        # non-destroyed target.
        assert seq.results[0].target_part is torso
        # Random-fallback path does NOT apply dodge scaling.
        assert seq.results[0].dodge == 8


class TestBasePrefixMatch:
    def test_base_name_prefix_resolves(self):
        """A preference of ``"leg"`` resolves to a random non-destroyed
        instance name like ``"leg.left"`` / ``"leg.right"``."""
        left = _make_part("leg.left", exposure=_full_exposure())
        right = _make_part("leg.right", exposure=_full_exposure())
        target = _make_creature("prey", body_parts=[left, right])

        attacker = _make_creature("predator")
        with patch.object(
            Creature, "get_target_part_preference", return_value="leg"
        ):
            seq = attacker.do_attack(target)
        assert seq.results[0].target_part in (left, right)


class TestMonsterPluginTargetPreferences:
    """Tests for the declarative ``TARGET_PREFERENCES`` dict on
    :class:`MonsterPlugin`. Subclasses populate the dict with
    ``{part_name: probability}`` and inherit the base
    ``get_target_part_preference`` loop. Single-entry dicts are
    RNG-count-identical to the hand-written ``if random() < p:``
    pattern; multi-entry dicts roll ``random()`` once per entry in
    insertion order, short-circuiting on first success."""

    def _make_monster(self, preferences):
        """Fabricate a throwaway MonsterPlugin subclass with the
        supplied TARGET_PREFERENCES. Avoids touching the real registry
        and avoids depending on any shipped monster's declared dict."""
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin

        class _FakeMob(MonsterPlugin):
            TARGET_PREFERENCES = preferences

            def __init__(self):
                super().__init__(
                    name="fake", atk="1d4", defense=0, dodge=0,
                    health_max=10,
                )

        return _FakeMob()

    def test_empty_dict_returns_none(self):
        """Default ``TARGET_PREFERENCES = {}`` means "no bias"; the hook
        should report ``None`` regardless of RNG."""
        m = self._make_monster({})
        # No random() calls should happen, but guard against surprises.
        with patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=0.0,
        ):
            assert m.get_target_part_preference(None, None) is None

    def test_single_entry_below_threshold_returns_part(self):
        """Single ``{"head": 0.4}`` entry with ``random()`` forced below
        0.4 returns ``"head"``."""
        m = self._make_monster({"head": 0.4})
        with patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=0.1,
        ):
            assert m.get_target_part_preference(None, None) == "head"

    def test_single_entry_above_threshold_returns_none(self):
        """Single ``{"head": 0.4}`` entry with ``random()`` forced above
        0.4 returns ``None`` (fall through to random targeting)."""
        m = self._make_monster({"head": 0.4})
        with patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=0.9,
        ):
            assert m.get_target_part_preference(None, None) is None

    def test_multi_entry_first_fires_returns_first(self):
        """Multi-entry dict: first entry's roll succeeds → returns the
        first part name, short-circuiting before later entries are even
        rolled."""
        m = self._make_monster({"head": 0.5, "leg": 0.5})
        # side_effect feeds successive values on each random() call.
        with patch(
            "caldanai.lib.rpg.creatures.random",
            side_effect=[0.1, 0.1],
        ) as fake_random:
            assert m.get_target_part_preference(None, None) == "head"
        # Short-circuited: only one random() call consumed.
        assert fake_random.call_count == 1

    def test_multi_entry_first_fails_second_fires_returns_second(self):
        """Multi-entry dict: first entry fails, second succeeds →
        returns the second part name. Iteration order follows dict
        insertion order (Py3.7+)."""
        m = self._make_monster({"head": 0.5, "leg": 0.5})
        with patch(
            "caldanai.lib.rpg.creatures.random",
            side_effect=[0.9, 0.1],
        ) as fake_random:
            assert m.get_target_part_preference(None, None) == "leg"
        assert fake_random.call_count == 2

    def test_multi_entry_all_fail_returns_none(self):
        """Multi-entry dict: every roll fails → returns ``None`` and
        every entry was consulted."""
        m = self._make_monster({"head": 0.5, "leg": 0.5})
        with patch(
            "caldanai.lib.rpg.creatures.random",
            side_effect=[0.9, 0.9],
        ) as fake_random:
            assert m.get_target_part_preference(None, None) is None
        assert fake_random.call_count == 2

    def test_iteration_follows_insertion_order(self):
        """Py3.7+ dict insertion order is part of the contract. When
        the first entry always fires (``prob=1.0``) the declared-first
        part wins regardless of alphabetical order."""
        m = self._make_monster({"zebra": 1.0, "antelope": 1.0})
        # Both rolls would succeed; the first-inserted "zebra" wins.
        with patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=0.0,
        ):
            assert m.get_target_part_preference(None, None) == "zebra"

        m2 = self._make_monster({"antelope": 1.0, "zebra": 1.0})
        with patch(
            "caldanai.lib.rpg.creatures.random",
            return_value=0.0,
        ):
            assert m2.get_target_part_preference(None, None) == "antelope"

    def test_base_monsterplugin_default_has_empty_preferences(self):
        """Base ``MonsterPlugin`` ships an empty dict so monsters that
        don't declare a bias opt into the "no preference" fallback
        automatically."""
        from caldanai.lib.rpg.creatures.monsters import MonsterPlugin
        assert MonsterPlugin.TARGET_PREFERENCES == {}
