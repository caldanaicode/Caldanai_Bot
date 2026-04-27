"""Tests for ``caldanai.lib.rpg.helpers.parser``.

Covers:

- Core token substitution: name, articles, pronouns, casing.
- **Order-agnostic casing**: ``@1cs`` and ``@1sc`` both produce the
  capitalized pronoun (regression test for a footgun where casing
  written before a pronoun would be clobbered by the pronoun
  substitution).
- ``uses_article = False`` opt-out for named entities.
- ``indefinite_article`` override for phonetic exceptions.
- Unknown form letters produce a warning log (and are dropped, not
  silently warping output).
"""

import logging
from types import SimpleNamespace

import pytest

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
    indefinite_article: str = None,
    plural_verbs: bool = False,
):
    """Lightweight actor stand-in — the parser only reads ``name``,
    ``pronouns``, ``uses_article``, ``indefinite_article``, and
    ``plural_verbs`` via getattr, so a SimpleNamespace is enough."""
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
        indefinite_article=indefinite_article,
        plural_verbs=plural_verbs,
    )


class TestBasicSubstitution:
    def test_bare_name(self):
        assert parse("@1 roars.", _actor("cyclops")) == "cyclops roars."

    def test_definite_article(self):
        assert parse("@1d roars.", _actor("cyclops")) == "the cyclops roars."

    def test_indefinite_article_consonant(self):
        assert parse("@1i appears.", _actor("cyclops")) == "a cyclops appears."

    def test_indefinite_article_vowel(self):
        assert parse("@1i appears.", _actor("ogre")) == "an ogre appears."

    def test_subjective_pronoun(self):
        assert parse("@1s swings.", _actor("cyclops")) == "she swings."

    def test_objective_pronoun(self):
        assert parse("hits @1o.", _actor("cyclops")) == "hits her."

    def test_multiple_actors(self):
        a = _actor("cyclops")
        b = _actor("hero", subjective="he")
        assert parse("@1d attacks @2.", a, b) == "the cyclops attacks hero."


class TestCasing:
    def test_capitalize_name(self):
        assert parse("@1c", _actor("cyclops")) == "Cyclops"

    def test_capitalize_preserves_internal_caps(self):
        """Capitalize only touches the first character — multi-word
        names ("Caldanai Playtester"), Mc-/Mac-/O'-style names, and
        doppelgangers carrying a player name post-imitation must
        keep their internal capitals. Regression: ``str.capitalize``
        lowercases the tail and was producing
        "Caldanai playtester's" in damage-flavor renders."""
        assert parse("@1c", _actor("Caldanai Playtester")) == "Caldanai Playtester"
        assert parse("@1c", _actor("McDonald")) == "McDonald"
        # Implicit-capitalize via uppercase form letter must not lower
        # the tail either — ``@1Np`` is the most common damage-flavor
        # token shape for player @-actors at sentence start.
        actor = _actor("Caldanai Playtester", uses_article=False)
        assert (
            parse("@1Np head seems lightly battered.", actor)
            == "Caldanai Playtester's head seems lightly battered."
        )

    def test_capitalize_article(self):
        assert parse("@1dc swings.", _actor("cyclops")) == "The cyclops swings."

    def test_upper(self):
        assert parse("@1u", _actor("cyclops")) == "CYCLOPS"

    def test_lower(self):
        assert parse("@1l", _actor("Cyclops")) == "cyclops"

    def test_title(self):
        assert parse("@1dt", _actor("dread cyclops")) == "The Dread Cyclops"


class TestCasingOrderAgnostic:
    """Regression: casing letters must apply after content forms
    (pronouns, articles) regardless of their position in the token.
    Previously ``@1cs`` would ``capitalize()`` the name first and then
    ``s`` would clobber it with the raw pronoun."""

    def test_casing_before_pronoun_matches_casing_after_pronoun(self):
        actor = _actor("cyclops")
        assert parse("@1cs", actor) == parse("@1sc", actor) == "She"

    def test_casing_before_article(self):
        # @1cd and @1dc should both produce "The cyclops"
        actor = _actor("cyclops")
        assert parse("@1cd", actor) == parse("@1dc", actor) == "The cyclops"

    def test_casing_middle_of_token(self):
        # @1scu (or any permutation) should still apply upper to the
        # final pronoun.
        actor = _actor("cyclops")
        assert parse("@1sc", actor) == "She"
        assert parse("@1su", actor) == "SHE"
        assert parse("@1us", actor) == "SHE"

    def test_multiple_casing_letters_all_apply(self):
        # If someone writes both upper and lower, they apply in order
        # after content forms. Last one wins by virtue of being applied
        # last.
        actor = _actor("cyclops")
        # ul → upper then lower → "cyclops"
        assert parse("@1ul", actor) == "cyclops"
        # lu → lower then upper → "CYCLOPS"
        assert parse("@1lu", actor) == "CYCLOPS"


class TestNamedEntities:
    """Named entities (players, uniquely-named monsters) opt out of
    articles via ``uses_article = False``. Articles become no-ops but
    the rest of the form chain still works."""

    def test_named_entity_ignores_definite_article(self):
        caels = _actor("Caels", uses_article=False)
        assert parse("@1d swings.", caels) == "Caels swings."

    def test_named_entity_ignores_indefinite_article(self):
        caels = _actor("Caels", uses_article=False)
        assert parse("@1i arrives.", caels) == "Caels arrives."

    def test_named_entity_pronoun_still_works(self):
        caels = _actor("Caels", uses_article=False)
        assert parse("@1s swings.", caels) == "she swings."


class TestIndefiniteArticleOverride:
    """Phonetic exceptions (``a unicorn``, ``an hour``) via
    ``indefinite_article`` attribute."""

    def test_override_applies(self):
        unicorn = _actor("unicorn", indefinite_article="a")
        assert parse("@1i appears.", unicorn) == "a unicorn appears."

    def test_override_still_allows_casing(self):
        unicorn = _actor("unicorn", indefinite_article="a")
        assert parse("@1ic appears.", unicorn) == "A unicorn appears."


class TestUnknownFormLetter:
    """Unknown form letters log a warning and are otherwise dropped."""

    def test_unknown_letter_is_ignored_in_output(self):
        # ``z`` isn't a recognized form. Output should be as if it
        # wasn't there — pronoun+casing still apply.
        actor = _actor("cyclops")
        assert parse("@1zsc", actor) == "She"

    def test_unknown_letter_emits_warning(self, caplog):
        actor = _actor("cyclops")
        with caplog.at_level(logging.WARNING, logger="caldanai.lib.rpg.helpers.parser"):
            parse("@1z", actor)
        assert any(
            "Unknown form letter" in rec.message and "'z'" in rec.message
            for rec in caplog.records
        ), f"Expected unknown-form warning; got {[r.message for r in caplog.records]}"

    def test_known_letters_do_not_warn(self, caplog):
        actor = _actor("cyclops")
        with caplog.at_level(logging.WARNING, logger="caldanai.lib.rpg.helpers.parser"):
            parse("@1dc swings.", actor)
        unknown_warnings = [
            r for r in caplog.records if "Unknown form letter" in r.message
        ]
        assert unknown_warnings == []


class TestPronounsFormProperty:
    """The parser derives its pronoun-letter lookup from
    ``Pronouns.form``. Lock in the first-char convention so a rename
    or new member gets caught here rather than in a surprise parser
    regression."""

    def test_form_is_first_letter_lowered(self):
        from caldanai.lib.rpg.helpers.enums import Pronouns
        for member in Pronouns:
            assert member.form == member.name[0].lower()

    def test_all_forms_are_unique(self):
        """If two members ever collide on first-char, the inverse dict
        in the parser silently loses one — this test catches that."""
        from caldanai.lib.rpg.helpers.enums import Pronouns
        forms = [member.form for member in Pronouns]
        assert len(forms) == len(set(forms)), (
            f"Pronouns.form collision: {forms}. Override form on one of "
            f"the colliding members."
        )


class TestNounPossessive:
    """``@1np`` renders the actor's name in possessive form — modern
    AP style (``"Caels's"``, ``"the werewolf's"``). Covers the common
    case where narration had to use literal ``@1's``."""

    def test_player_name_possessive(self):
        caels = _actor("Caels", uses_article=False)
        assert parse("@1np shade cries out.", caels) == "Caels's shade cries out."

    def test_name_ending_in_s_still_gets_apostrophe_s(self):
        # "Caels" ends in 's'; AP style appends 's anyway. Consistency
        # over English-teacher debates.
        caels = _actor("Caels", uses_article=False)
        assert parse("@1np", caels) == "Caels's"

    def test_name_with_apostrophe_still_works(self):
        kra = _actor("Kra'tal", uses_article=False)
        assert parse("@1np", kra) == "Kra'tal's"

    def test_noun_possessive_auto_prepends_article_for_article_using_creatures(self):
        # Bare ``@1np`` on an article-using creature auto-prepends
        # "the" — the possessive of "the werewolf" is "the werewolf's",
        # not "werewolf's" (bare-name possessive reads as a grammar
        # error for article-using creatures).
        beast = _actor("werewolf")
        assert parse("@1np fangs glisten.", beast) == "the werewolf's fangs glisten."

    def test_noun_possessive_with_explicit_article_still_works(self):
        # ``@1dnp`` explicitly requests the article. The article path
        # sets ``result = "the werewolf"`` first; the possessive path
        # then sees the "the " prefix and doesn't double up.
        beast = _actor("werewolf")
        assert parse("@1dnp fangs glisten.", beast) == "the werewolf's fangs glisten."

    def test_noun_possessive_composes_with_casing(self):
        # Casing deferred; @1cnp and @1npc both capitalize the final
        # string. Works uniformly.
        caels = _actor("caels", uses_article=False)  # lowercased to prove casing
        assert parse("@1cnp", caels) == "Caels's"
        assert parse("@1npc", caels) == "Caels's"

    def test_noun_mode_non_possessive_is_noop(self):
        # @1ns, @1no, @1na, @1nr are all ``name + nonsense-morphology``
        # on a name, which has no distinct form. Resolve to bare name,
        # don't crash, don't warn (noun-mode eats the letter silently).
        caels = _actor("Caels", uses_article=False)
        assert parse("@1ns", caels) == "Caels"
        assert parse("@1no", caels) == "Caels"

    def test_noun_mode_before_casing_letter_resets_cleanly(self):
        # @1nc → noun-mode pending; 'c' is casing, so noun-mode resets
        # without effect and casing applies normally.
        caels = _actor("Caels", uses_article=False)
        assert parse("@1nc", caels) == "Caels"

    def test_pronoun_possessive_still_works(self):
        # Ensure @1p (pronoun possessive) isn't broken by noun-mode
        # changes — still returns "hers" / "theirs" / etc.
        caels = _actor("Caels", possessive="hers", uses_article=False)
        assert parse("@1p", caels) == "hers"

    def test_named_entity_possessive_skips_article_correctly(self):
        # Even without an article, noun-possessive works on a name.
        caels = _actor("Caels", uses_article=False)
        assert parse("@1np", caels) == "Caels's"


class TestVerbAgreement:
    """``@<n>v(singular|plural)`` picks based on ``actor.plural_verbs``."""

    def test_singular_actor_uses_singular_form(self):
        she = _actor("Caels", uses_article=False, plural_verbs=False)
        assert parse("@1s @1v(attacks|attack) the dummy.", she) == "she attacks the dummy."

    def test_plural_actor_uses_plural_form(self):
        they = _actor(
            "Caels", subjective="they", objective="them", possessive="theirs",
            adjective="their", reflexive="themself",
            uses_article=False, plural_verbs=True,
        )
        assert parse("@1s @1v(attacks|attack) the dummy.", they) == "they attack the dummy."

    def test_verb_token_alone_works(self):
        # No pronoun paired — just the verb. Still resolves based on actor.
        she = _actor("x", plural_verbs=False)
        assert parse("@1v(is|are)", she) == "is"
        they = _actor("x", plural_verbs=True)
        assert parse("@1v(is|are)", they) == "are"

    def test_each_actor_uses_their_own_agreement(self):
        """Multi-actor string: @1v(...) and @2v(...) read independent
        plural_verbs flags. Important for strings mixing he/she and
        they/them subjects."""
        she = _actor("Caels", plural_verbs=False, uses_article=False)
        they = _actor(
            "Ezra",
            subjective="they", objective="them", possessive="theirs",
            adjective="their", reflexive="themself",
            plural_verbs=True, uses_article=False,
        )
        s = "@1s @1v(greets|greet) @2, and @2s @2v(nods|nod) back."
        assert parse(s, she, they) == "she greets Ezra, and they nod back."

    def test_capitalization_via_literal_in_verb_content(self):
        """Casing on verb tokens isn't supported as a form letter;
        capitalize inside the choices when you need it."""
        she = _actor("Caels", uses_article=False)
        assert parse("@1v(Attacks|Attack) first!", she) == "Attacks first!"


class TestVerbAgreementMalformed:
    """Malformed verb tokens log warnings and render best-effort
    (or pass through literally when the regex doesn't even match)."""

    def test_missing_pipe_uses_single_form(self, caplog):
        she = _actor("x", plural_verbs=False)
        with caplog.at_level(logging.WARNING, logger="caldanai.lib.rpg.helpers.parser"):
            result = parse("@1v(attacks)", she)
        assert result == "attacks"
        assert any("missing a '|'" in r.message for r in caplog.records)

    def test_extra_pipe_uses_first_two_forms(self, caplog):
        she = _actor("x", plural_verbs=False)
        with caplog.at_level(logging.WARNING, logger="caldanai.lib.rpg.helpers.parser"):
            result = parse("@1v(a|b|c)", she)
        # singular_a plural_b → she picks singular → "a"
        assert result == "a"
        assert any("extra '|'" in r.message for r in caplog.records)

    def test_unbalanced_paren_renders_name_plus_leftover(self, caplog):
        # Regex requires a closing paren; unbalanced strings don't
        # match the verb regex at all, so the actor regex picks up
        # @1v as "actor 1 with unknown form letter v". Output is the
        # name followed by the literal paren leftover, and the
        # unknown-form warning fires — author sees it's broken and fixes.
        she = _actor("x")
        with caplog.at_level(logging.WARNING, logger="caldanai.lib.rpg.helpers.parser"):
            result = parse("@1v(attacks|attack", she)
        # "x" (name) + "(attacks|attack" (literal leftover)
        assert result == "x(attacks|attack"
        assert any("Unknown form letter 'v'" in r.message for r in caplog.records)

    def test_out_of_range_actor_falls_back(self, caplog):
        she = _actor("x")
        with caplog.at_level(logging.WARNING, logger="caldanai.lib.rpg.helpers.parser"):
            result = parse("@5v(a|b)", she)
        # Falls back to actor 0, which is singular → "a".
        assert result == "a"
        assert any("only 1 actor" in r.message for r in caplog.records)


class TestPluralVerbsPropertyDerivation:
    """The ``Creature.plural_verbs`` property derives from the
    subjective pronoun. Known plural-agreeing values match; unknown /
    neopronoun values fall back to singular."""

    def test_they_subjective_is_plural(self):
        from caldanai.lib.rpg.creatures import Creature
        c = Creature(name="t", atk="1d4", defense=1, dodge=1, health_max=10, pronouns="they,them,theirs,their")
        assert c.plural_verbs is True

    def test_she_subjective_is_singular(self):
        from caldanai.lib.rpg.creatures import Creature
        c = Creature(name="t", atk="1d4", defense=1, dodge=1, health_max=10, pronouns="she,her,hers,her")
        assert c.plural_verbs is False

    def test_he_subjective_is_singular(self):
        from caldanai.lib.rpg.creatures import Creature
        c = Creature(name="t", atk="1d4", defense=1, dodge=1, health_max=10, pronouns="he,him,his,his")
        assert c.plural_verbs is False

    def test_neopronoun_xe_defaults_to_singular(self):
        """Neopronouns aren't in the plural-agreeing set; fall back to
        singular per the convention for English neopronouns."""
        from caldanai.lib.rpg.creatures import Creature
        c = Creature(name="t", atk="1d4", defense=1, dodge=1, health_max=10, pronouns="xe,xem,xyr,xyr")
        assert c.plural_verbs is False


class TestNoActors:
    """Defensive: calling ``parse`` with no actors must not crash; it
    returns the original token untouched and logs an error."""

    def test_returns_original_when_no_actors(self):
        # No actors supplied → _process bails out and returns the raw
        # match text.
        assert parse("@1d", ) == "@1d"


# ---------------------------------------------------------------------------
# Case-sensitive form letters — uppercase anywhere in the form string
# implies ``c`` (capitalize). Ergonomic shortcut: ``@1A`` ≡ ``@1ac``.
# ---------------------------------------------------------------------------


class TestCaseSensitiveForms:
    def test_uppercase_possessive_adjective(self):
        caels = _actor("Caels", uses_article=False, adjective="his")
        # @1A ≡ @1ac → "His"
        assert parse("@1A", caels) == "His"

    def test_lowercase_possessive_adjective_stays_lowercase(self):
        # Default behavior unchanged.
        caels = _actor("Caels", uses_article=False, adjective="his")
        assert parse("@1a", caels) == "his"

    def test_uppercase_definite_article_on_monster(self):
        # @1D ≡ @1dc → "The cyclops"
        assert parse("@1D roars.", _actor("cyclops")) == "The cyclops roars."

    def test_uppercase_subjective_pronoun(self):
        # @1S ≡ @1sc → "She"
        assert parse("@1S swings.", _actor("cyclops")) == "She swings."

    def test_uppercase_noun_possessive_on_monster(self):
        # @1Np ≡ @1npc → "The werewolf's"
        assert parse("@1Np fangs", _actor("werewolf")) == "The werewolf's fangs"

    def test_uppercase_on_any_letter_implies_capitalize(self):
        # Whichever letter is cased upper, the output is capitalized.
        # @1nP and @1Np should both equal @1npc.
        beast = _actor("werewolf")
        assert parse("@1nP", beast) == "The werewolf's"
        assert parse("@1Np", beast) == "The werewolf's"

    def test_explicit_c_still_works_and_is_idempotent_with_uppercase(self):
        # Explicit ``c`` and uppercase letter both set implicit
        # capitalize; appending ``c`` to an already-uppercase-flagged
        # token is redundant but not harmful.
        caels = _actor("Caels", uses_article=False, adjective="his")
        assert parse("@1Ac", caels) == "His"

    def test_explicit_casing_overrides_uppercase_hint(self):
        # ``l`` (force lowercase) beats an uppercase form letter's
        # implicit ``c`` because explicit casing was written first in
        # the casing_forms list and applies deterministically.
        # Practically: authors choose explicit casing when they want
        # deviant behavior; don't second-guess them.
        caels = _actor("Caels", uses_article=False, adjective="his")
        # @1Al → "His" via uppercase A, then ``l`` lowercases → "his".
        assert parse("@1Al", caels) == "his"


# ---------------------------------------------------------------------------
# Mention form (``m``) — renders Discord-mention tag for players,
# falls back to normal rendering for non-player actors.
# ---------------------------------------------------------------------------


class TestMentionForm:
    def _player(self, name="alice", user_id=111111111111111111):
        """Actor stub with a Discord-``member`` carrying a ``.mention``
        attribute — mirrors the shape the parser's mention form
        reads: ``actor.member.mention`` (discord.py's canonical
        format, so this module doesn't hardcode ``<@!id>``)."""
        return SimpleNamespace(
            name=name,
            pronouns={
                Pronouns.SUBJECTIVE: "he",
                Pronouns.OBJECTIVE:  "him",
                Pronouns.POSSESSIVE: "his",
                Pronouns.ADJECTIVE:  "his",
                Pronouns.REFLEXIVE:  "himself",
            },
            uses_article=False,
            indefinite_article=None,
            plural_verbs=False,
            member=SimpleNamespace(mention=f"<@!{user_id}>"),
        )

    def test_mention_form_emits_discord_mention_tag_for_player(self):
        caels = self._player(user_id=12345)
        assert parse("@1m swings.", caels) == "<@!12345> swings."

    def test_mention_form_falls_back_to_name_for_monster(self):
        # Monster has no ``user_id`` attribute → fall through to normal
        # processing. Bare ``@1m`` with no other form letters → bare
        # name (equivalent to ``@1``).
        bandit = _actor("bandit")
        assert parse("@1m lunges.", bandit) == "bandit lunges."

    def test_mention_form_fallthrough_respects_other_form_letters(self):
        # If mention isn't available (no user_id), the rest of the
        # form string processes normally. So ``@1md`` on a monster
        # behaves like ``@1d`` → "the bandit".
        bandit = _actor("bandit")
        assert parse("@1md lunges.", bandit) == "the bandit lunges."

    def test_mention_dominates_non_possessive_forms(self):
        # Non-possessive form letters (subject, object, reflexive,
        # article) on the same token as ``m`` are ignored — a
        # mention tag doesn't have pronoun/article variants.
        caels = self._player(user_id=12345)
        assert parse("@1ms swings.", caels) == "<@!12345> swings."
        assert parse("@1mD swings.", caels) == "<@!12345> swings."
        assert parse("@1mo targeted.", caels) == "<@!12345> targeted."
        assert parse("@1mr bleeds.", caels) == "<@!12345> bleeds."

    def test_mention_composes_with_possessive_pronoun(self):
        # ``@1mp`` — mention + possessive pronoun → mention's
        # possessive form: ``<@!id>'s``. Reads naturally in
        # "@1mp dagger slides between @2p ribs" constructions where
        # the mention is the owner of something.
        caels = self._player(user_id=12345)
        assert parse("@1mp dagger slides.", caels) == "<@!12345>'s dagger slides."

    def test_mention_composes_with_possessive_adjective(self):
        # ``@1ma`` — mention + possessive adjective → same
        # possessive mention form.
        caels = self._player(user_id=12345)
        assert parse("@1ma blade.", caels) == "<@!12345>'s blade."

    def test_mention_composes_with_noun_possessive(self):
        # ``@1mnp`` — mention + noun-possessive → ``<@!id>'s``.
        # Semantically equivalent to ``@1mp`` for mention context;
        # both express "the mentioned player's ...".
        caels = self._player(user_id=12345)
        assert parse("@1mnp shadow falls.", caels) == "<@!12345>'s shadow falls."

    def test_mention_possessive_fallthrough_still_works_for_monster(self):
        # Monster has no user_id → fall through; ``@1mnp`` for a
        # monster behaves like ``@1np`` → "the bandit's".
        bandit = _actor("bandit")
        assert parse("@1mnp fangs glisten.", bandit) == "the bandit's fangs glisten."

    def test_uppercase_M_implicit_capitalize_is_harmless_on_mention(self):
        # ``@1M`` sets the implicit-capitalize flag, but the mention
        # short-circuit skips casing entirely, so the output is the
        # raw mention tag unchanged.
        caels = self._player(user_id=12345)
        assert parse("@1M swings.", caels) == "<@!12345> swings."

    def test_no_member_attribute_at_all_falls_back_cleanly(self):
        # Actor object that doesn't declare ``member`` —
        # ``getattr(actor, "member", None)`` returns None and the
        # fallthrough path emits the bare name.
        barebones = SimpleNamespace(
            name="ghost",
            pronouns={
                Pronouns.SUBJECTIVE: "they",
                Pronouns.OBJECTIVE:  "them",
                Pronouns.POSSESSIVE: "theirs",
                Pronouns.ADJECTIVE:  "their",
                Pronouns.REFLEXIVE:  "themself",
            },
            uses_article=True,
            indefinite_article=None,
            plural_verbs=True,
        )
        assert parse("@1m drifts past.", barebones) == "ghost drifts past."
