"""Tests for the narrator-output lint logic in
``caldanai.lib.rpg.helpers.parser`` (search for "Narrator-output
lint" in that module).

The lint catches the specific mechanical patterns the API narrator
(Sonnet, Haiku, or similar) repeatedly produced during prompt
validation (2026-04-19 sessions A–C, rounds 1–4). Fixtures use real
observed strings so regressions against those patterns are caught.

CLI tests for the operator-facing wrapper live in
``tests/test_tools_postprocess_narrator_output.py``.
"""

from caldanai.lib.rpg.helpers import parser as pp


# ---------------------------------------------------------------------------
# _strip_invalid_noun_mode
# ---------------------------------------------------------------------------


class TestStripInvalidNounMode:
    def test_strips_n_before_objective_pronoun(self):
        out, n = pp._strip_invalid_noun_mode("@2no upright")
        assert out == "@2o upright"
        assert n == 1

    def test_strips_n_before_subjective_pronoun(self):
        out, n = pp._strip_invalid_noun_mode("@1ns swings")
        assert out == "@1s swings"
        assert n == 1

    def test_strips_n_before_adjective_pronoun(self):
        out, n = pp._strip_invalid_noun_mode("@2na arm")
        assert out == "@2a arm"
        assert n == 1

    def test_strips_n_before_reflexive(self):
        out, n = pp._strip_invalid_noun_mode("catches @1nr off guard")
        assert out == "catches @1r off guard"
        assert n == 1

    def test_valid_noun_possessive_unchanged(self):
        out, n = pp._strip_invalid_noun_mode("@2np torso")
        assert out == "@2np torso"
        assert n == 0

    def test_uppercase_np_unchanged(self):
        out, n = pp._strip_invalid_noun_mode("@2Np blade")
        assert out == "@2Np blade"
        assert n == 0

    def test_uppercase_n_before_non_p_also_stripped(self):
        out, n = pp._strip_invalid_noun_mode("@1No attack")
        assert out == "@1o attack"
        assert n == 1

    def test_multiple_invalid_combos_in_one_string(self):
        out, n = pp._strip_invalid_noun_mode("@1ns swings at @2no")
        assert out == "@1s swings at @2o"
        assert n == 2

    def test_iterates_to_fixed_point(self):
        # @1nno → strip first n → @1no → strip second n → @1o
        out, n = pp._strip_invalid_noun_mode("@1nno")
        assert out == "@1o"
        assert n == 2

    def test_two_digit_actor_number(self):
        out, n = pp._strip_invalid_noun_mode("@12no")
        assert out == "@12o"
        assert n == 1


# ---------------------------------------------------------------------------
# _dedupe_mentions
# ---------------------------------------------------------------------------


class TestDedupeMentions:
    def test_first_mention_kept(self):
        out, n = pp._dedupe_mentions("@2m lunges.")
        assert out == "@2m lunges."
        assert n == 0

    def test_second_mention_same_actor_stripped(self):
        out, n = pp._dedupe_mentions("@2m catches. @2mp left leg")
        assert out == "@2m catches. @2p left leg"
        assert n == 1

    def test_different_actors_each_get_one_mention(self):
        out, n = pp._dedupe_mentions("@2m hits @3m hard")
        assert out == "@2m hits @3m hard"
        assert n == 0

    def test_third_mention_same_actor_also_stripped(self):
        out, n = pp._dedupe_mentions("@2m catches. @2mp left leg. @2mp teeth")
        assert out == "@2m catches. @2p left leg. @2p teeth"
        assert n == 2

    def test_possessive_mention_preserved_on_first_use(self):
        out, n = pp._dedupe_mentions("toward @2mp skull")
        assert out == "toward @2mp skull"
        assert n == 0

    def test_verb_tokens_untouched(self):
        out, n = pp._dedupe_mentions("@1s @1v(maims|maim) @2m")
        assert out == "@1s @1v(maims|maim) @2m"
        assert n == 0


# ---------------------------------------------------------------------------
# _fix_capitalization
# ---------------------------------------------------------------------------


class TestFixCapitalization:
    def test_sentence_start_possessive_uppercased(self):
        out, n = pp._fix_capitalization("@2a skull offers no resistance.")
        assert out == "@2A skull offers no resistance."
        assert n == 1

    def test_sentence_start_after_period_uppercased(self):
        out, n = pp._fix_capitalization("Caels lands. @1a shortsword bites.")
        assert out == "Caels lands. @1A shortsword bites."
        assert n == 1

    def test_mid_sentence_token_left_lowercase(self):
        out, n = pp._fix_capitalization("driving @2a torso, @1a knuckles")
        assert out == "driving @2a torso, @1a knuckles"
        assert n == 0

    def test_mid_sentence_uppercase_lowered(self):
        out, n = pp._fix_capitalization("driving toward @2A crown while")
        assert out == "driving toward @2a crown while"
        assert n == 1

    def test_mid_sentence_Nnp_lowered(self):
        out, n = pp._fix_capitalization("through @1Np jaws")
        assert out == "through @1np jaws"
        assert n == 1

    def test_sentence_start_after_punctuation_followed_by_newline(self):
        out, n = pp._fix_capitalization("first sentence.\n\n@1a arm rises.")
        assert out == "first sentence.\n\n@1A arm rises."
        assert n == 1

    def test_verb_agreement_token_not_uppercased(self):
        out, n = pp._fix_capitalization("@1v(strikes|strike) first")
        assert out == "@1v(strikes|strike) first"
        assert n == 0

    def test_bare_token_no_form_letters_untouched(self):
        out, n = pp._fix_capitalization("@1 swings")
        assert out == "@1 swings"
        assert n == 0

    def test_explicit_case_letters_preserved_mid_sentence(self):
        # Mid-sentence `@1C` is downcased to `@1c`. Linter favors
        # "mid-sentence should be lowercase" uniformly.
        out, _ = pp._fix_capitalization("and @1C stands tall")
        assert out == "and @1c stands tall"


# ---------------------------------------------------------------------------
# _scan_literal_pronouns
# ---------------------------------------------------------------------------


class TestScanLiteralPronouns:
    def test_catches_literal_his(self):
        warnings = pp._scan_literal_pronouns("drops his shoulder")
        assert any("his" in w for w in warnings)

    def test_catches_literal_her(self):
        warnings = pp._scan_literal_pronouns("crosses her arms")
        assert any("her" in w for w in warnings)

    def test_catches_literal_they(self):
        warnings = pp._scan_literal_pronouns("they stumble back")
        assert any("they" in w for w in warnings)

    def test_case_insensitive(self):
        warnings = pp._scan_literal_pronouns("His strike lands.")
        assert any("his" in w.lower() for w in warnings)

    def test_tokenized_forms_not_flagged(self):
        warnings = pp._scan_literal_pronouns("drops @1a shoulder")
        assert warnings == []

    def test_verb_agreement_token_contents_not_scanned(self):
        warnings = pp._scan_literal_pronouns("@1s @1v(hits him|hit them)")
        assert warnings == []

    def test_deduped_within_string(self):
        warnings = pp._scan_literal_pronouns("her eyes and her hands")
        her_warnings = [
            w for w in warnings
            if "her" in w and "their" not in w and "hers" not in w
        ]
        assert len(her_warnings) == 1

    def test_word_boundaries_respected(self):
        warnings = pp._scan_literal_pronouns("standing here now")
        assert warnings == []

    def test_its_followed_by_innocent_noun_fully_suppressed(self):
        # "its wearer" reads as object-owner (armor), not an actor.
        warnings = pp._scan_literal_pronouns(
            "the armor's magic doesn't care whose body its wearer inhabits"
        )
        its_warns = [w for w in warnings if "'its'" in w]
        assert len(its_warns) == 0

    def test_its_innocent_noun_coverage(self):
        for innocent_phrase in [
            "its wearer falls",
            "its blade glints",
            "its edge finds cloth",
            "its hilt turns in the palm",
            "its surface ripples",
            "its weight settles",
            "its magic flares",
            "its corner collapses",
        ]:
            warnings = pp._scan_literal_pronouns(innocent_phrase)
            its_warns = [w for w in warnings if "'its'" in w]
            assert its_warns == [], (
                f"expected no 'its' warning for {innocent_phrase!r}, got {its_warns}"
            )

    def test_its_with_non_whitelisted_noun_still_warned(self):
        warnings = pp._scan_literal_pronouns("its fangs sink into the meat")
        its_warns = [w for w in warnings if "'its'" in w]
        assert len(its_warns) == 1
        assert "verify reference" in its_warns[0]

    def test_itself_also_softened(self):
        warnings = pp._scan_literal_pronouns(
            "the blade unsheathes itself from the stone"
        )
        itself_warns = [w for w in warnings if "'itself'" in w]
        assert len(itself_warns) == 1
        assert "verify reference" in itself_warns[0]

    def test_gendered_pronouns_keep_stronger_wording(self):
        warnings = pp._scan_literal_pronouns("her eyes narrow")
        her_warns = [w for w in warnings if "'her'" in w]
        assert len(her_warns) == 1
        assert "should be tokenized" in her_warns[0]


# ---------------------------------------------------------------------------
# lint_narrative integration
# ---------------------------------------------------------------------------


class TestLintNarrativeIntegration:
    def test_all_passes_compose(self):
        s = "@1m strikes. @1mp dagger finds her throat. @2no stumbles."
        out, warnings = pp.lint_narrative(s)
        assert "@1M strikes." in out
        assert "@1P dagger" in out
        assert "her throat" in out
        assert "@2O stumbles." in out
        joined = " | ".join(warnings)
        assert "dropped" in joined and "mention" in joined
        assert "invalid" in joined
        assert "literal pronoun" in joined

    def test_sonnet_scenario_A_round2_bug(self):
        s = "The bandit staggers, @2a legs barely keeping @2no upright."
        out, warnings = pp.lint_narrative(s)
        assert "@2no" not in out
        assert "@2o upright" in out
        assert any("invalid" in w for w in warnings)

    def test_sonnet_scenario_B_round2_bug(self):
        s = "<@!12345> never sees it coming. @1np first head takes them."
        out, warnings = pp.lint_narrative(s)
        assert "@1Np first head" in out
        assert any("case" in w.lower() or "adjusted" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# lint_output (dict-level)
# ---------------------------------------------------------------------------


class TestLintOutput:
    def test_all_known_keys_processed(self):
        obj = {
            "narrate_attempt": "@1a shortsword",
            "narrate_results": "@2no lunges",
            "narrate_target_death": "@1a body falls",
            "narrate_attacker_death": "@1a death is sudden",
        }
        cleaned, warnings = pp.lint_output(obj)
        assert cleaned["narrate_attempt"] == "@1A shortsword"
        assert cleaned["narrate_results"] == "@2O lunges"
        assert cleaned["narrate_target_death"] == "@1A body falls"
        assert cleaned["narrate_attacker_death"] == "@1A death is sudden"
        assert any(w.startswith("narrate_results:") for w in warnings)

    def test_null_keys_skipped(self):
        obj = {
            "narrate_attempt": "@1a punch",
            "narrate_results": None,
            "narrate_target_death": None,
            "narrate_attacker_death": None,
        }
        cleaned, _ = pp.lint_output(obj)
        assert cleaned["narrate_attempt"] == "@1A punch"
        assert cleaned["narrate_results"] is None
        assert cleaned["narrate_target_death"] is None
        assert cleaned["narrate_attacker_death"] is None

    def test_missing_keys_skipped(self):
        obj = {"narrate_attempt": "@1a hit", "narrate_results": "lands"}
        cleaned, _ = pp.lint_output(obj)
        assert "narrate_target_death" not in cleaned
