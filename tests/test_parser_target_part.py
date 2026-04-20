"""Tests for the Phase 3 target-part parser tokens.

Covers:

- ``@Np_target`` — dynamic token resolving to
  ``result.target_part.display_name`` supplied via ``parse(..., result=)``.
- ``@Np.<part_name>`` — explicit fuzzy lookup via ``find_parts`` on
  the corresponding actor.
- Graceful degradation when the result / target_part / actor is
  missing or has no matching part.
- Capitalization via uppercase ``P``.
"""

from types import SimpleNamespace

import pytest

from caldanai.lib.rpg.creatures import Creature
from caldanai.lib.rpg.creatures.body_part import BodyPart
from caldanai.lib.rpg.helpers.enums import Pronouns
from caldanai.lib.rpg.helpers.parser import parse


def _actor(
    name: str,
    *,
    subjective: str = "she",
    objective: str = "her",
    possessive: str = "hers",
    adjective: str = "her",
    reflexive: str = "herself",
    uses_article: bool = True,
    plural_verbs: bool = False,
):
    return SimpleNamespace(
        name=name,
        pronouns={
            Pronouns.SUBJECTIVE: subjective,
            Pronouns.OBJECTIVE:  objective,
            Pronouns.POSSESSIVE: possessive,
            Pronouns.ADJECTIVE:  adjective,
            Pronouns.REFLEXIVE:  reflexive,
        },
        uses_article=uses_article,
        indefinite_article=None,
        plural_verbs=plural_verbs,
    )


def _make_victim_with_parts():
    """Creature with a couple of parts so ``find_parts`` resolves."""
    victim = Creature(
        name="caels", atk="1d4", defense=0, dodge=0,
        health_max=40, health=40, pronouns="he, him, his, his",
    )
    victim.uses_article = False
    arm_left = BodyPart.make("arm", name="arm.left")
    arm_right = BodyPart.make("arm", name="arm.right")
    head = BodyPart.make("head", name="head")
    victim.body_parts = [head, arm_left, arm_right]
    return victim


class TestTargetPartDynamic:
    """``@Np_target`` reads ``result.target_part.display_name``."""

    def test_resolves_display_name_when_result_supplied(self):
        caels = _actor("Caels", uses_article=False)
        bandit = _actor("bandit")
        arm = SimpleNamespace(display_name="left arm")
        result = SimpleNamespace(target_part=arm)
        out = parse(
            "@1D bites @2 on the @2p_target.",
            bandit, caels, result=result,
        )
        assert out == "The bandit bites Caels on the left arm."

    def test_empty_string_when_result_is_none(self):
        caels = _actor("Caels", uses_article=False)
        bandit = _actor("bandit")
        out = parse(
            "@1D bites @2 on the @2p_target.",
            bandit, caels,
        )
        # No result passed — token collapses to empty string.
        assert out == "The bandit bites Caels on the ."

    def test_empty_string_when_target_part_is_none(self):
        caels = _actor("Caels", uses_article=False)
        bandit = _actor("bandit")
        result = SimpleNamespace(target_part=None)
        out = parse(
            "@1D bites @2 on the @2p_target.",
            bandit, caels, result=result,
        )
        assert out == "The bandit bites Caels on the ."

    def test_uppercase_p_capitalizes(self):
        caels = _actor("Caels", uses_article=False)
        bandit = _actor("bandit")
        arm = SimpleNamespace(display_name="left arm")
        result = SimpleNamespace(target_part=arm)
        out = parse(
            "@2P_target is bleeding.",
            bandit, caels, result=result,
        )
        assert out == "Left arm is bleeding."

    def test_lowercase_p_does_not_capitalize(self):
        caels = _actor("Caels", uses_article=False)
        bandit = _actor("bandit")
        arm = SimpleNamespace(display_name="left arm")
        result = SimpleNamespace(target_part=arm)
        out = parse(
            "hits @1p_target",
            caels, bandit, result=result,
        )
        assert out == "hits left arm"


class TestExplicitPartLookup:
    """``@Np.<name>`` fuzzy-matches via ``Creature.find_parts``."""

    def test_exact_dotted_name_matches(self):
        victim = _make_victim_with_parts()
        out = parse("the @1p.arm.left is bruised", victim)
        assert out == "the left arm is bruised"

    def test_fuzzy_prefix_match(self):
        victim = _make_victim_with_parts()
        # ``leg.r`` in the docstring example; here "arm.l" matches
        # arm.left via segment-prefix.
        out = parse("the @1p.arm.l is bruised", victim)
        assert out == "the left arm is bruised"

    def test_missing_part_renders_empty(self):
        victim = _make_victim_with_parts()
        out = parse("the @1p.wing is gone", victim)
        assert out == "the  is gone"

    def test_actor_without_find_parts_renders_empty(self):
        bandit = _actor("bandit")  # SimpleNamespace, no find_parts
        out = parse("the @1p.arm is bruised", bandit)
        assert out == "the  is bruised"

    def test_uppercase_p_capitalizes(self):
        victim = _make_victim_with_parts()
        out = parse("@1P.arm.left is bleeding.", victim)
        assert out == "Left arm is bleeding."

    def test_coexists_with_possessive_pronoun(self):
        """``@1p`` (pronoun) vs ``@1p.<name>`` (lookup) — the dot is
        the disambiguator."""
        victim = _make_victim_with_parts()
        # @1p should still be the possessive pronoun "his"; @1p.arm
        # should resolve to a part.
        out = parse("@1p arm? no, @1p.arm.left", victim)
        assert out == "his arm? no, left arm"

    def test_trailing_period_stays_with_sentence(self):
        """Regex must not greedily capture a sentence-ending period
        after ``@Np.<name>``. Authors should be able to write
        ``@1p.arm.`` and see the rendered part name followed by the
        literal period."""
        victim = _make_victim_with_parts()
        out = parse("she grabs @1p.arm.", victim)
        assert out == "she grabs left arm."

    def test_numeric_dotted_segment(self):
        """Parts like ``head.1`` / ``head.2`` use numeric segments —
        the lookup regex must include them."""
        victim = Creature(
            name="hydra", atk="1d4", defense=0, dodge=0,
            health_max=40, health=40, pronouns="she, her, hers, her",
        )
        head1 = BodyPart.make("head", name="head.1")
        head2 = BodyPart.make("head", name="head.2")
        victim.body_parts = [head1, head2]
        out = parse("@1p.head.2 snaps", victim)
        assert out == "head 2 snaps"


class TestTokenInteraction:
    """Sanity checks that the new tokens don't break existing shapes."""

    def test_mixed_with_bare_possessive(self):
        victim = _make_victim_with_parts()
        # Bare ``@1p`` → pronoun; ``@1p_target`` → part name from
        # result context. Both in the same template.
        arm = SimpleNamespace(display_name="left arm")
        result = SimpleNamespace(target_part=arm)
        out = parse("@1p blood runs from @1p_target.", victim, result=result)
        assert out == "his blood runs from left arm."

    def test_nested_phase3_template_shape(self):
        """Full phase-3 template using @1D / @1a / @2np / @2p_target."""
        bandit = _actor("bandit")
        caels = _actor(
            "Caels", uses_article=False,
            subjective="he", objective="him",
            possessive="his", adjective="his", reflexive="himself",
        )
        arm = SimpleNamespace(display_name="left arm")
        result = SimpleNamespace(target_part=arm)
        out = parse(
            "@1D bites @2np @2p_target.",
            bandit, caels, result=result,
        )
        assert out == "The bandit bites Caels's left arm."
