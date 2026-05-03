"""Tests for passerby render-layer helpers in
``caldanai.lib.rpg.creatures.passersby.rendering``.

Covers:
- ``PasserbyPlugin.__init__`` converts the class-level pronoun
  string to a per-instance Dict that the parser can square-
  bracket-access.
- ``StrangerActor`` wraps a player so ``.name`` reads as
  "traveler" while pronouns / user_id / other attrs proxy
  through unchanged.
- ``_maybe_unwrap`` honors acquaintance + NAMING_BIAS:
  not-acquainted always wraps, acquainted rolls once.
- ``render_npc_only`` / ``render_combat_witness`` /
  ``render_actor_npc`` produce the expected substituted strings.

The parser itself is exercised end-to-end via real
:func:`parse` calls — these tests rely on an integration check
that pronouns route through correctly, not just unit-isolation.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from caldanai.lib.rpg.creatures.passersby import PasserbyPlugin
from caldanai.lib.rpg.creatures.passersby.rendering import (
    StrangerActor,
    _maybe_unwrap,
    force_stranger,
    render_actor_npc,
    render_combat_witness,
    render_npc_only,
)
from caldanai.lib.rpg.creatures.passersby.wagoneer import Wagoneer
from caldanai.lib.rpg.creatures.passersby.wren import Wren
from caldanai.lib.rpg.helpers.enums import Pronouns


# ---------------------------------------------------------------------------
# Fixtures — minimal Player-like objects for parser interop
# ---------------------------------------------------------------------------


def _make_player(name="Caels", gender="male", uid=12345):
    """Player stand-in with the surface ``parser.parse`` reads:
    ``.name``, ``.uses_article``, ``.pronouns`` (Dict-keyed),
    ``.user_id``, ``.plural_verbs``."""
    if gender == "male":
        prn = {
            Pronouns.SUBJECTIVE: "he",
            Pronouns.OBJECTIVE: "him",
            Pronouns.POSSESSIVE: "his",
            Pronouns.ADJECTIVE: "his",
            Pronouns.REFLEXIVE: "himself",
        }
    elif gender == "female":
        prn = {
            Pronouns.SUBJECTIVE: "she",
            Pronouns.OBJECTIVE: "her",
            Pronouns.POSSESSIVE: "hers",
            Pronouns.ADJECTIVE: "her",
            Pronouns.REFLEXIVE: "herself",
        }
    else:  # they/them
        prn = {
            Pronouns.SUBJECTIVE: "they",
            Pronouns.OBJECTIVE: "them",
            Pronouns.POSSESSIVE: "theirs",
            Pronouns.ADJECTIVE: "their",
            Pronouns.REFLEXIVE: "themself",
        }
    return SimpleNamespace(
        name=name,
        uses_article=False,
        pronouns=prn,
        user_id=uid,
        plural_verbs=(gender == "neutral"),
    )


# ---------------------------------------------------------------------------
# PasserbyPlugin.__init__ — pronouns dict conversion
# ---------------------------------------------------------------------------


class TestPasserbyPluginPronounsDict:
    def test_wagoneer_pronouns_dict_at_instance(self):
        w = Wagoneer()
        assert isinstance(w.pronouns, dict)
        assert w.pronouns[Pronouns.SUBJECTIVE] == "he"
        assert w.pronouns[Pronouns.OBJECTIVE] == "him"
        assert w.pronouns[Pronouns.POSSESSIVE] == "his"
        assert w.pronouns[Pronouns.ADJECTIVE] == "his"
        assert w.pronouns[Pronouns.REFLEXIVE] == "himself"

    def test_wren_pronouns_dict_at_instance(self):
        wren = Wren()
        assert wren.pronouns[Pronouns.SUBJECTIVE] == "she"
        assert wren.pronouns[Pronouns.OBJECTIVE] == "her"
        # POSSESSIVE = standalone "hers"; ADJECTIVE = modifier "her"
        # — matches Creature's convention exactly.
        assert wren.pronouns[Pronouns.POSSESSIVE] == "hers"
        assert wren.pronouns[Pronouns.ADJECTIVE] == "her"
        assert wren.pronouns[Pronouns.REFLEXIVE] == "herself"

    def test_default_passerby_is_neutral(self):
        """A bare ``PasserbyPlugin()`` (no subclass overrides) gets
        the GenderMixin neutral default."""
        p = PasserbyPlugin()
        assert p.pronouns[Pronouns.SUBJECTIVE] == "they"
        assert p.pronouns[Pronouns.OBJECTIVE] == "them"
        assert p.pronouns[Pronouns.POSSESSIVE] == "theirs"
        assert p.pronouns[Pronouns.ADJECTIVE] == "their"
        assert p.pronouns[Pronouns.REFLEXIVE] == "themself"


# ---------------------------------------------------------------------------
# StrangerActor — wrap behavior
# ---------------------------------------------------------------------------


class TestStrangerActor:
    def test_name_reads_as_traveler(self):
        p = _make_player(name="Caels")
        s = StrangerActor(p)
        assert s.name == "traveler"

    def test_uses_article_is_true(self):
        # Players have uses_article=False; stranger flips so
        # "the traveler" reads as a role.
        p = _make_player(name="Caels")
        s = StrangerActor(p)
        assert s.uses_article is True

    def test_pronouns_proxy_through(self):
        p = _make_player(name="Vael", gender="neutral")
        s = StrangerActor(p)
        assert s.pronouns[Pronouns.SUBJECTIVE] == "they"
        assert s.pronouns[Pronouns.OBJECTIVE] == "them"

    def test_user_id_proxy_through(self):
        p = _make_player(name="Caels", uid=99999)
        s = StrangerActor(p)
        assert s.user_id == 99999

    def test_arbitrary_attr_proxy_through(self):
        p = SimpleNamespace(name="X", custom_field="hello")
        s = StrangerActor(p)
        assert s.custom_field == "hello"


# ---------------------------------------------------------------------------
# _maybe_unwrap — acquaintance + bias logic
# ---------------------------------------------------------------------------


class TestMaybeUnwrap:
    def test_not_acquainted_always_wraps(self):
        p = _make_player()
        # Even with bias 1.0, not-acquainted never uses the real name.
        result = _maybe_unwrap(p, acquainted=False, naming_bias=1.0)
        assert isinstance(result, StrangerActor)

    def test_acquainted_with_bias_1_always_uses_real(self):
        p = _make_player()
        # bias=1.0 means random() >= 1.0 is impossible → always real.
        result = _maybe_unwrap(p, acquainted=True, naming_bias=1.0)
        assert result is p

    def test_acquainted_with_bias_0_always_wraps(self):
        p = _make_player()
        # bias=0.0 means random() >= 0.0 is always True → always wrap.
        result = _maybe_unwrap(p, acquainted=True, naming_bias=0.0)
        assert isinstance(result, StrangerActor)

    def test_acquainted_intermediate_bias_rolls(self):
        p = _make_player()
        # Patch random() to control the roll outcome deterministically.
        # roll < bias → real; roll >= bias → stranger.
        with patch(
            "caldanai.lib.rpg.creatures.passersby.rendering.random",
            return_value=0.3,
        ):
            assert _maybe_unwrap(
                p, acquainted=True, naming_bias=0.5,
            ) is p  # 0.3 < 0.5 → real
        with patch(
            "caldanai.lib.rpg.creatures.passersby.rendering.random",
            return_value=0.7,
        ):
            r = _maybe_unwrap(
                p, acquainted=True, naming_bias=0.5,
            )
            assert isinstance(r, StrangerActor)  # 0.7 >= 0.5 → wrap

    def test_force_stranger_helper(self):
        p = _make_player()
        s = force_stranger(p)
        assert isinstance(s, StrangerActor)
        assert s.name == "traveler"


# ---------------------------------------------------------------------------
# Render helpers — end-to-end through parser
# ---------------------------------------------------------------------------


class TestRenderNpcOnly:
    def test_uses_npc_name_with_article(self):
        """``@1d`` against a wagoneer renders ``"the wagoneer"``."""
        w = Wagoneer()
        out = render_npc_only("@1D rolls in.", w)
        assert out == "The wagoneer rolls in."

    def test_pronoun_substitution_male(self):
        w = Wagoneer()
        out = render_npc_only("@1D leans on @1a pole.", w)
        assert out == "The wagoneer leans on his pole."

    def test_pronoun_substitution_female(self):
        wren = Wren()
        # Wren's uses_article is False — name renders as "Wren".
        out = render_npc_only("@1D adjusts @1a satchel.", wren)
        assert out == "Wren adjusts her satchel."


class TestRenderCombatWitness:
    def test_acquainted_uses_real_name(self):
        w = Wagoneer()
        caels = _make_player(name="Caels")
        out = render_combat_witness(
            "@1D claps @2 on the shoulder.",
            w, caels,
            acquainted=True, naming_bias=1.0,
        )
        assert out == "The wagoneer claps Caels on the shoulder."

    def test_not_acquainted_uses_traveler(self):
        w = Wagoneer()
        caels = _make_player(name="Caels")
        out = render_combat_witness(
            "@1D claps @2d on the shoulder.",
            w, caels,
            acquainted=False, naming_bias=1.0,  # bias irrelevant
        )
        # @1D = sentence-start, capitalized. @2d = mid-sentence,
        # lowercase. Stranger surface flips uses_article → True so
        # @2d renders "the traveler" rather than just "traveler".
        assert out == "The wagoneer claps the traveler on the shoulder."

    def test_no_witness_renders_npc_only(self):
        """``witness=None`` falls through to npc-only render —
        defensive against missing witness data."""
        w = Wagoneer()
        out = render_combat_witness(
            "@1D nods, satisfied.",
            w, None,
            acquainted=True, naming_bias=1.0,
        )
        assert out == "The wagoneer nods, satisfied."


class TestRenderActorNpc:
    def test_acquainted_uses_actor_real_name(self):
        """Social-reaction shape: actor=@1, npc=@2. Acquainted +
        bias 1.0 means the real player name renders."""
        wren = Wren()
        caels = _make_player(name="Caels")
        out = render_actor_npc(
            "@1d waves at Wren.",
            caels, wren,
            acquainted=True, naming_bias=1.0,
        )
        # Caels.uses_article = False so @1d renders as "Caels"
        # (no article).
        assert out == "Caels waves at Wren."

    def test_not_acquainted_uses_traveler(self):
        wren = Wren()
        caels = _make_player(name="Caels")
        out = render_actor_npc(
            "@1D waves at Wren.",
            caels, wren,
            acquainted=False, naming_bias=1.0,
        )
        assert out == "The traveler waves at Wren."

    def test_pronoun_substitution_uses_real_pronouns_when_stranger(self):
        """Stranger surface masks NAME but pronouns proxy through —
        the NPC never mis-genders an unacquainted player."""
        wren = Wren()
        vael = _make_player(name="Vael", gender="neutral")
        # Use @1s (subjective) — should render with real pronoun
        # (they) regardless of stranger wrap, because the player's
        # actual gender shouldn't be hidden.
        out = render_actor_npc(
            "@1S waves.",
            vael, wren,
            acquainted=False, naming_bias=1.0,
        )
        assert out == "They waves."  # Verb agreement is the cog's job

    def test_named_passerby_no_article(self):
        """Wren has ``uses_article=False`` (proper name), so @2 alone
        renders just ``Wren`` without ``"the "``."""
        wren = Wren()
        caels = _make_player(name="Caels")
        out = render_actor_npc(
            "@1d says hello to @2.",
            caels, wren,
            acquainted=True, naming_bias=1.0,
        )
        assert "Wren" in out
        assert "the Wren" not in out

    def test_generic_passerby_uses_article(self):
        """Wagoneer has ``uses_article=True`` (generic-typed), so
        @2d renders ``"the wagoneer"``."""
        w = Wagoneer()
        caels = _make_player(name="Caels")
        out = render_actor_npc(
            "@1d says hello to @2d.",
            caels, w,
            acquainted=True, naming_bias=1.0,
        )
        assert "the wagoneer" in out
