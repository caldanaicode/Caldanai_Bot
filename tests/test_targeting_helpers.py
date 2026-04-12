"""Tests for targeting helpers (item 1.8).

Covers:
- ``Creature.get_part(name)`` — exact-match lookup by part name.
- ``Creature.get_targetable_parts()`` — filters out destroyed parts.
- ``pick_random_part(parts, reach)`` — module-level free function that
  picks a random part weighted by ``part.exposure.get(reach, 1.0)``.
"""

import random
from collections import Counter
from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures import Creature, pick_random_part
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import Reach


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_creature(**kwargs) -> Creature:
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


def _make_part(name: str, *, exposure=None, health_max: int = 10) -> BodyPart:
    return BodyPart(name=name, health_max=health_max, exposure=exposure)


# ---------------------------------------------------------------------------
# Creature.get_part
# ---------------------------------------------------------------------------

class TestGetPart:
    def test_finds_existing_part_by_name(self):
        c = _make_creature()
        head = _make_part("head")
        arm = _make_part("arm.left")
        c.body_parts = [head, arm]

        assert c.get_part("head") is head
        assert c.get_part("arm.left") is arm

    def test_returns_none_for_missing_name(self):
        c = _make_creature()
        c.body_parts = [_make_part("head"), _make_part("torso")]

        assert c.get_part("tail") is None

    def test_returns_none_when_body_parts_is_empty(self):
        c = _make_creature()
        assert c.body_parts == []
        assert c.get_part("head") is None

    def test_is_case_sensitive(self):
        c = _make_creature()
        c.body_parts = [_make_part("head")]

        assert c.get_part("head") is not None
        assert c.get_part("Head") is None
        assert c.get_part("HEAD") is None

    def test_returns_first_match_on_duplicate_names(self):
        c = _make_creature()
        first = _make_part("leg")
        second = _make_part("leg")
        c.body_parts = [first, second]

        assert c.get_part("leg") is first


# ---------------------------------------------------------------------------
# Creature.get_targetable_parts
# ---------------------------------------------------------------------------

class TestGetTargetableParts:
    def test_returns_all_parts_when_all_alive(self):
        c = _make_creature()
        head = _make_part("head")
        arm = _make_part("arm")
        c.body_parts = [head, arm]

        result = c.get_targetable_parts()

        assert result == [head, arm]

    def test_excludes_destroyed_parts(self):
        c = _make_creature()
        head = _make_part("head")
        arm = _make_part("arm")
        # Zero out arm's health so ``is_destroyed()`` returns True.
        arm.health = 0
        c.body_parts = [head, arm]

        result = c.get_targetable_parts()

        assert result == [head]
        assert arm.is_destroyed()
        assert arm not in result

    def test_returns_empty_list_when_body_parts_empty(self):
        c = _make_creature()
        assert c.body_parts == []
        assert c.get_targetable_parts() == []

    def test_returns_empty_list_when_all_parts_destroyed(self):
        c = _make_creature()
        head = _make_part("head")
        arm = _make_part("arm")
        head.health = 0
        arm.health = 0
        c.body_parts = [head, arm]

        assert c.get_targetable_parts() == []

    def test_returns_new_list_each_call(self):
        """Result should be a fresh list so callers can mutate freely."""
        c = _make_creature()
        c.body_parts = [_make_part("head")]
        a = c.get_targetable_parts()
        b = c.get_targetable_parts()
        assert a == b
        assert a is not b


# ---------------------------------------------------------------------------
# pick_random_part
# ---------------------------------------------------------------------------

class TestPickRandomPart:
    def test_returns_none_on_empty_list(self):
        assert pick_random_part([], Reach.MELEE) is None

    def test_picks_only_part_when_one_exists(self):
        head = _make_part("head", exposure={Reach.MELEE: 1.0})
        result = pick_random_part([head], Reach.MELEE)
        assert result is head

    def test_returns_none_when_all_parts_have_zero_exposure(self):
        a = _make_part("a", exposure={Reach.MELEE: 0.0})
        b = _make_part("b", exposure={Reach.MELEE: 0.0})
        assert pick_random_part([a, b], Reach.MELEE) is None

    def test_missing_reach_key_defaults_to_full_exposure(self):
        """A part with an empty ``exposure`` dict defaults to weight 1.0
        for any reach — i.e. 'fully exposed by default'."""
        part = _make_part("mystery", exposure={})
        # With only one part and a default weight of 1.0, it must be picked.
        assert pick_random_part([part], Reach.RANGED) is part

    def test_missing_reach_key_amid_others_still_targetable(self):
        exposed = _make_part("exposed", exposure={})  # defaults to 1.0
        hidden = _make_part("hidden", exposure={Reach.MELEE: 0.0})

        # Over many rolls, ``exposed`` is the only pickable part
        # (``hidden`` has zero weight).
        picks = Counter()
        for _ in range(200):
            picks[pick_random_part([exposed, hidden], Reach.MELEE)] += 1

        assert picks[exposed] == 200
        assert picks[hidden] == 0

    def test_weighted_distribution_biases_toward_high_exposure(self):
        """Seeded-random run actually exercises the weighting.

        With weights 9.0 vs 1.0, the high-exposure part must win the vast
        majority of picks. The exact counts are deterministic because
        ``random.seed`` is set before the loop.
        """
        big = _make_part("big", exposure={Reach.MELEE: 9.0})
        small = _make_part("small", exposure={Reach.MELEE: 1.0})

        random.seed(0)
        picks = Counter()
        for _ in range(1000):
            picks[pick_random_part([big, small], Reach.MELEE)] += 1

        # Expected ratio is 9:1 — allow generous slack but assert the bias.
        assert picks[big] > picks[small] * 3
        # And both should show up at least once given 1000 draws.
        assert picks[big] > 0
        assert picks[small] > 0
        # Every pick should be one of the two parts.
        assert picks[big] + picks[small] == 1000

    def test_passes_weights_to_random_choices(self):
        """Direct verification that the function forwards the right
        weights to ``random.choices`` — guards against someone silently
        dropping the weighting later."""
        a = _make_part("a", exposure={Reach.MELEE: 2.0})
        b = _make_part("b", exposure={Reach.MELEE: 5.0})

        with patch(
            "caldanai.lib.rpg.creatures.random.choices",
            return_value=[a],
        ) as mock_choices:
            result = pick_random_part([a, b], Reach.MELEE)

        assert result is a
        mock_choices.assert_called_once()
        _, kwargs = mock_choices.call_args
        # ``parts`` passed positionally, weights kwarg carries the exposures.
        assert kwargs["weights"] == [2.0, 5.0]
        assert kwargs["k"] == 1

    def test_uses_reach_specific_exposure(self):
        """A part's melee exposure should not affect ranged picks."""
        melee_only = _make_part(
            "melee_only",
            exposure={Reach.MELEE: 1.0, Reach.RANGED: 0.0},
        )
        ranged_only = _make_part(
            "ranged_only",
            exposure={Reach.MELEE: 0.0, Reach.RANGED: 1.0},
        )

        # Ranged attacks can only hit ``ranged_only``.
        for _ in range(50):
            assert pick_random_part(
                [melee_only, ranged_only], Reach.RANGED
            ) is ranged_only

        # Melee attacks can only hit ``melee_only``.
        for _ in range(50):
            assert pick_random_part(
                [melee_only, ranged_only], Reach.MELEE
            ) is melee_only
