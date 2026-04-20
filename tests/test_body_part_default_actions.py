"""Tests for Phase 3 ``DEFAULT_ACTIONS`` on every active body-part
plugin. Locks in the action list (Q3), narrative pool size (Q5),
dialogue-free templates (Q6), and verifies every template renders
through :func:`parse` without warning.

Split into one class per plugin so a failing expectation reports
against the specific part, not a generic "some plugin's actions are
wrong."
"""

import re
from types import SimpleNamespace
from typing import Dict

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.creatures.body_parts.action_dice import (
    size_scaled_dice,
)
from caldanai.lib.rpg.creatures.body_parts.arm import ArmPlugin
from caldanai.lib.rpg.creatures.body_parts.eye import EyePlugin
from caldanai.lib.rpg.creatures.body_parts.head import HeadPlugin
from caldanai.lib.rpg.creatures.body_parts.leg import LegPlugin
from caldanai.lib.rpg.creatures.body_parts.tail import TailPlugin
from caldanai.lib.rpg.creatures.body_parts.toe import ToePlugin
from caldanai.lib.rpg.creatures.body_parts.torso import TorsoPlugin
from caldanai.lib.rpg.creatures.body_parts.wing import WingPlugin
from caldanai.lib.rpg.helpers.dice import Dice
from caldanai.lib.rpg.helpers.enums import (
    DamageTypes, Pronouns, Reach, Size,
)
from caldanai.lib.rpg.helpers.parser import lint_narrative, parse


_REQUIRED_FIELDS = {"cost", "weight", "dmg_type", "reach", "label", "narrative"}
_MIN_POOL = 6
_MAX_POOL = 10  # headroom above Q5's 6-8 target in case tweaks land

# Dialogue markers — Q6 forbids dialogue in part-default pools.
_DIALOGUE_MARKERS = ('"', "'", "said", "snarls", "growls", "howls", "roars")


def _actor(name: str, uses_article: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        pronouns={
            Pronouns.SUBJECTIVE: "she",
            Pronouns.OBJECTIVE:  "her",
            Pronouns.POSSESSIVE: "hers",
            Pronouns.ADJECTIVE:  "her",
            Pronouns.REFLEXIVE:  "herself",
        },
        uses_article=uses_article,
        indefinite_article=None,
        plural_verbs=False,
    )


def _synthetic_result(display: str) -> SimpleNamespace:
    return SimpleNamespace(
        target_part=SimpleNamespace(display_name=display),
    )


def _check_entry_shape(
    plugin_cls, action_name: str, entry: Dict, expected_dmg_type,
) -> None:
    missing = _REQUIRED_FIELDS - set(entry.keys())
    assert not missing, (
        f"{plugin_cls.__name__}.DEFAULT_ACTIONS['{action_name}'] "
        f"missing {missing}"
    )
    assert entry["dmg_type"] is expected_dmg_type
    assert isinstance(entry["reach"], Reach)
    assert isinstance(entry["cost"], int) and entry["cost"] > 0
    assert isinstance(entry["weight"], (int, float)) and entry["weight"] > 0
    assert isinstance(entry["label"], str) and entry["label"]
    pool = entry["narrative"]
    assert isinstance(pool, list)
    assert _MIN_POOL <= len(pool) <= _MAX_POOL, (
        f"{plugin_cls.__name__}.DEFAULT_ACTIONS['{action_name}'] "
        f"narrative pool size {len(pool)} not in [{_MIN_POOL}, {_MAX_POOL}]"
    )
    # Q6: no dialogue markers in any template.
    for template in pool:
        lowered = template.lower()
        for marker in _DIALOGUE_MARKERS:
            assert marker.lower() not in lowered, (
                f"dialogue marker {marker!r} found in "
                f"{plugin_cls.__name__}.DEFAULT_ACTIONS['{action_name}'] "
                f"template: {template!r}"
            )


def _check_renders(pool, *, include_result: bool = True):
    """Every template in ``pool`` must parse cleanly with synthetic
    actors. Catches @token typos before they ship."""
    bandit = _actor("bandit")
    caels = _actor("Caels", uses_article=False)
    caels.pronouns = {
        Pronouns.SUBJECTIVE: "he",
        Pronouns.OBJECTIVE:  "him",
        Pronouns.POSSESSIVE: "his",
        Pronouns.ADJECTIVE:  "his",
        Pronouns.REFLEXIVE:  "himself",
    }
    result = _synthetic_result("left arm") if include_result else None
    for template in pool:
        rendered = parse(template, bandit, caels, result=result)
        # Parser never returns None; must be a non-empty string and
        # must not contain any dangling @-tokens.
        assert isinstance(rendered, str) and rendered.strip()
        assert "@" not in rendered, (
            f"template leaked a literal @-token after parse: {template!r} -> "
            f"{rendered!r}"
        )


class TestHeadPluginDefaults:
    def test_exact_action_keys(self):
        assert set(HeadPlugin.DEFAULT_ACTIONS.keys()) == {"bite", "headbutt"}

    def test_bite_entry_shape(self):
        _check_entry_shape(
            HeadPlugin, "bite", HeadPlugin.DEFAULT_ACTIONS["bite"],
            DamageTypes.PIERCING,
        )

    def test_headbutt_entry_shape(self):
        _check_entry_shape(
            HeadPlugin, "headbutt", HeadPlugin.DEFAULT_ACTIONS["headbutt"],
            DamageTypes.BLUDGEONING,
        )

    def test_narrative_templates_render(self):
        for action in HeadPlugin.DEFAULT_ACTIONS.values():
            _check_renders(action["narrative"])


class TestArmPluginDefaults:
    def test_exact_action_keys(self):
        assert set(ArmPlugin.DEFAULT_ACTIONS.keys()) == {"punch", "grab"}

    def test_punch_entry_shape(self):
        _check_entry_shape(
            ArmPlugin, "punch", ArmPlugin.DEFAULT_ACTIONS["punch"],
            DamageTypes.BLUDGEONING,
        )

    def test_grab_entry_shape(self):
        _check_entry_shape(
            ArmPlugin, "grab", ArmPlugin.DEFAULT_ACTIONS["grab"],
            DamageTypes.BLUDGEONING,
        )

    def test_narrative_templates_render(self):
        for action in ArmPlugin.DEFAULT_ACTIONS.values():
            _check_renders(action["narrative"])


class TestLegPluginDefaults:
    def test_exact_action_keys(self):
        assert set(LegPlugin.DEFAULT_ACTIONS.keys()) == {"kick", "stomp"}

    def test_kick_entry_shape(self):
        _check_entry_shape(
            LegPlugin, "kick", LegPlugin.DEFAULT_ACTIONS["kick"],
            DamageTypes.BLUDGEONING,
        )

    def test_stomp_entry_shape(self):
        _check_entry_shape(
            LegPlugin, "stomp", LegPlugin.DEFAULT_ACTIONS["stomp"],
            DamageTypes.BLUDGEONING,
        )

    def test_narrative_templates_render(self):
        for action in LegPlugin.DEFAULT_ACTIONS.values():
            _check_renders(action["narrative"])


class TestTailPluginDefaults:
    def test_exact_action_keys(self):
        assert set(TailPlugin.DEFAULT_ACTIONS.keys()) == {
            "tail_swipe", "tail_slam",
        }

    def test_tail_swipe_entry_shape(self):
        _check_entry_shape(
            TailPlugin, "tail_swipe",
            TailPlugin.DEFAULT_ACTIONS["tail_swipe"],
            DamageTypes.BLUDGEONING,
        )

    def test_tail_slam_entry_shape(self):
        _check_entry_shape(
            TailPlugin, "tail_slam",
            TailPlugin.DEFAULT_ACTIONS["tail_slam"],
            DamageTypes.BLUDGEONING,
        )

    def test_narrative_templates_render(self):
        for action in TailPlugin.DEFAULT_ACTIONS.values():
            _check_renders(action["narrative"])


class TestWingPluginDefaults:
    def test_exact_action_keys(self):
        assert set(WingPlugin.DEFAULT_ACTIONS.keys()) == {"wing_buffet"}

    def test_wing_buffet_entry_shape(self):
        _check_entry_shape(
            WingPlugin, "wing_buffet",
            WingPlugin.DEFAULT_ACTIONS["wing_buffet"],
            DamageTypes.BLUDGEONING,
        )

    def test_narrative_templates_render(self):
        for action in WingPlugin.DEFAULT_ACTIONS.values():
            _check_renders(action["narrative"])


class TestTorsoPluginDefaults:
    def test_exact_action_keys(self):
        assert set(TorsoPlugin.DEFAULT_ACTIONS.keys()) == {"chestbutt"}

    def test_chestbutt_entry_shape(self):
        _check_entry_shape(
            TorsoPlugin, "chestbutt",
            TorsoPlugin.DEFAULT_ACTIONS["chestbutt"],
            DamageTypes.BLUDGEONING,
        )

    def test_narrative_templates_render(self):
        for action in TorsoPlugin.DEFAULT_ACTIONS.values():
            _check_renders(action["narrative"])


class TestTemplatesPassLint:
    """Every Phase 3 template must pass ``lint_narrative`` cleanly —
    no capitalization fixups, no stray literal pronouns, no
    duplicate-mention warnings. Guards against narrator-side grammar
    drift in the authored pools."""

    @pytest.mark.parametrize(
        "plugin_cls",
        [HeadPlugin, ArmPlugin, LegPlugin, TailPlugin, WingPlugin, TorsoPlugin],
        ids=lambda cls: cls.__name__,
    )
    def test_lint_is_clean(self, plugin_cls):
        for action_name, entry in plugin_cls.DEFAULT_ACTIONS.items():
            for template in entry["narrative"]:
                cleaned, warnings = lint_narrative(template)
                assert not warnings, (
                    f"{plugin_cls.__name__}.{action_name}: "
                    f"template {template!r} tripped lint: {warnings}"
                )
                # Lint should not mutate a clean template.
                assert cleaned == template


class TestPassiveOnlyPlugins:
    """Eye and Toe are passive-only — ``DEFAULT_ACTIONS`` must stay
    empty per Q3. Guards against accidental population."""

    def test_eye_has_no_default_actions(self):
        assert EyePlugin.DEFAULT_ACTIONS == {}

    def test_toe_has_no_default_actions(self):
        assert ToePlugin.DEFAULT_ACTIONS == {}


class TestSizeScaledDice:
    """``size_scaled_dice`` returns a valid dice string for every
    declared action at every Size."""

    _DICE_STRING_RE = re.compile(r"^\d+d\d+$")

    @pytest.mark.parametrize("action", [
        "bite", "headbutt", "punch", "grab", "kick", "stomp",
        "tail_swipe", "tail_slam", "wing_buffet", "chestbutt",
    ])
    def test_action_dice_parses_for_every_size(self, action):
        for size in Size:
            dice = size_scaled_dice(action, size)
            assert self._DICE_STRING_RE.match(dice), (
                f"size_scaled_dice({action!r}, {size}) returned {dice!r}"
            )
            # Also exercise Dice.quick_roll to make sure the shape is
            # one dice.py accepts.
            val = Dice.quick_roll(dice)
            assert val >= 1

    def test_unknown_action_falls_back_to_medium_scale(self):
        """Unknown actions shouldn't crash — fall through to a
        sensible default so future actions don't need the tier table
        pre-populated."""
        dice = size_scaled_dice("fictional_action", Size.MEDIUM)
        assert self._DICE_STRING_RE.match(dice)

    def test_larger_sizes_not_smaller_than_medium(self):
        """Sanity check on the tiers: LARGE / HUGE / COLOSSAL dice
        should not decrease max damage below MEDIUM for any action."""
        def _max_damage(dice_str: str) -> int:
            dice = Dice.from_ndn(dice_str)
            return dice.count * dice.sides

        for action in [
            "bite", "punch", "kick", "stomp", "wing_buffet", "chestbutt",
            "tail_swipe", "tail_slam", "headbutt", "grab",
        ]:
            medium_max = _max_damage(size_scaled_dice(action, Size.MEDIUM))
            for size in (Size.LARGE, Size.HUGE, Size.COLOSSAL):
                bigger_max = _max_damage(size_scaled_dice(action, size))
                assert bigger_max >= medium_max, (
                    f"{action} at {size.name} max {bigger_max} < "
                    f"MEDIUM max {medium_max}"
                )
