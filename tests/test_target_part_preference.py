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
