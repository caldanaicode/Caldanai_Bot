"""Tests for ``tools/parse_template.py``.

The tool runs an arbitrary ``@``-tokened template through
``caldanai.lib.rpg.helpers.parser.parse`` with stubbed actors.
Cover: actor-spec parsing, actor attribute shape, CLI plumbing
(inline / file / stdin), and end-to-end parse correctness across
the full matrix of supported ``KIND`` / ``GENDER`` combinations.
"""

import io
from contextlib import redirect_stdout

import pytest

from caldanai.lib.rpg.helpers.enums import Pronouns
from tools import parse_template


# ---------------------------------------------------------------------------
# _make_actor — the spec parser
# ---------------------------------------------------------------------------


class TestMakeActor:
    def test_player_male(self):
        actor = parse_template._make_actor("Caels:player:male")
        assert actor.name == "Caels"
        assert actor.uses_article is False
        assert actor.gender == "male"
        assert actor.pronouns[Pronouns.SUBJECTIVE] == "he"
        assert actor.pronouns[Pronouns.OBJECTIVE] == "him"
        assert actor.pronouns[Pronouns.POSSESSIVE] == "his"
        assert actor.pronouns[Pronouns.ADJECTIVE] == "his"
        assert actor.pronouns[Pronouns.REFLEXIVE] == "himself"
        assert actor.plural_verbs is False

    def test_monster_female(self):
        actor = parse_template._make_actor("bandit:monster:female")
        assert actor.name == "bandit"
        assert actor.uses_article is True
        assert actor.pronouns[Pronouns.SUBJECTIVE] == "she"
        assert actor.pronouns[Pronouns.ADJECTIVE] == "her"
        assert actor.pronouns[Pronouns.POSSESSIVE] == "hers"
        assert actor.plural_verbs is False

    def test_nonbinary_sets_plural_verbs(self):
        """They/them actors flip the ``plural_verbs`` flag so
        ``@Nv(singular|plural)`` picks the plural form."""
        actor = parse_template._make_actor("Serena:player:nonbinary")
        assert actor.pronouns[Pronouns.SUBJECTIVE] == "they"
        assert actor.pronouns[Pronouns.ADJECTIVE] == "their"
        assert actor.pronouns[Pronouns.REFLEXIVE] == "themself"
        assert actor.plural_verbs is True

    def test_neuter(self):
        actor = parse_template._make_actor("hydra:monster:neuter")
        assert actor.name == "hydra"
        assert actor.uses_article is True
        assert actor.pronouns[Pronouns.SUBJECTIVE] == "it"
        assert actor.pronouns[Pronouns.ADJECTIVE] == "its"
        assert actor.pronouns[Pronouns.REFLEXIVE] == "itself"
        assert actor.plural_verbs is False

    def test_case_insensitive_kind_and_gender(self):
        actor = parse_template._make_actor("Caels:Player:MALE")
        assert actor.uses_article is False
        assert actor.pronouns[Pronouns.SUBJECTIVE] == "he"

    def test_malformed_spec_too_few_parts(self):
        with pytest.raises(SystemExit, match="NAME:KIND:GENDER"):
            parse_template._make_actor("Caels:player")

    def test_malformed_spec_too_many_parts(self):
        # 4 parts is valid (NAME:KIND:GENDER:MENTION). 5+ is malformed.
        with pytest.raises(SystemExit, match="NAME:KIND:GENDER"):
            parse_template._make_actor("Caels:player:male:<@!1>:extra")

    def test_optional_mention_field_populates_member(self):
        """4th spec field becomes ``actor.member.mention`` so the
        parser's ``@Nm`` form resolves against this stub."""
        actor = parse_template._make_actor(
            "Caels:player:male:<@!111111111111111111>"
        )
        assert hasattr(actor, "member")
        assert actor.member.mention == "<@!111111111111111111>"

    def test_omitting_mention_leaves_no_member(self):
        """3-field spec produces an actor without ``member``, so
        ``@Nm`` falls through to normal form processing."""
        actor = parse_template._make_actor("Caels:player:male")
        assert not hasattr(actor, "member")

    def test_invalid_kind(self):
        with pytest.raises(SystemExit, match="kind"):
            parse_template._make_actor("Caels:npc:male")

    def test_invalid_gender(self):
        with pytest.raises(SystemExit, match="gender"):
            parse_template._make_actor("Caels:player:agender")


# ---------------------------------------------------------------------------
# End-to-end parse correctness — actor-stub rendering
# ---------------------------------------------------------------------------


class TestEndToEndRendering:
    """Verify the stubbed actors produce the same rendering the real
    ``Creature`` / ``Player`` classes would for a handful of common
    token forms. Guards against drift between the tool's
    ``_PRONOUN_SETS`` and ``Creature._populate_pronouns``."""

    def _render(self, template: str, *specs: str) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            parse_template.main(
                ["--template", template]
                + [arg for spec in specs for arg in ("--actor", spec)]
            )
        # Trim trailing newline from the print.
        return buf.getvalue().rstrip("\n")

    def test_player_bare_name_and_possessive(self):
        out = self._render(
            "@1 swings @1a sword at @1r.",
            "Caels:player:male",
        )
        assert out == "Caels swings his sword at himself."

    def test_monster_definite_article_and_name_possessive(self):
        out = self._render(
            "@1dc roars. @1np jaws snap.",
            "werewolf:monster:male",
        )
        assert out == "The werewolf roars. the werewolf's jaws snap."

    def test_pronoun_verb_agreement_singular(self):
        out = self._render(
            "@1sc @1v(strikes|strike) first.",
            "Caels:player:male",
        )
        assert out == "He strikes first."

    def test_pronoun_verb_agreement_plural_for_they_them(self):
        out = self._render(
            "@1sc @1v(strikes|strike) first.",
            "Serena:player:nonbinary",
        )
        assert out == "They strike first."

    def test_two_actor_scene_cross_references(self):
        out = self._render(
            "@1 swings at @2d; @2a arm blocks @1a fist.",
            "Caels:player:male",
            "bandit:monster:female",
        )
        assert out == "Caels swings at the bandit; her arm blocks his fist."

    def test_neuter_hydra_pronouns(self):
        out = self._render(
            "@1dc rears @1a heads. @1sc hisses.",
            "hydra:monster:neuter",
        )
        assert out == "The hydra rears its heads. It hisses."


# ---------------------------------------------------------------------------
# CLI plumbing — template source, stdin, errors
# ---------------------------------------------------------------------------


class TestCLI:
    def test_inline_template(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = parse_template.main([
                "--actor", "Caels:player:male",
                "--template", "@1 waves.",
            ])
        assert exit_code == 0
        assert buf.getvalue().rstrip("\n") == "Caels waves."

    def test_template_file(self, tmp_path):
        f = tmp_path / "tpl.txt"
        f.write_text("@1 waves.", encoding="utf-8")
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = parse_template.main([
                "--actor", "Caels:player:male",
                "--template-file", str(f),
            ])
        assert exit_code == 0
        assert buf.getvalue().rstrip("\n") == "Caels waves."

    def test_stdin_template(self, monkeypatch):
        monkeypatch.setattr("sys.stdin", io.StringIO("@1 waves."))
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = parse_template.main([
                "--actor", "Caels:player:male",
            ])
        assert exit_code == 0
        assert buf.getvalue().rstrip("\n") == "Caels waves."

    def test_multiple_actors_indexed_by_position(self):
        """The first ``--actor`` becomes ``@1``, the second ``@2``, etc."""
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = parse_template.main([
                "--actor", "Caels:player:male",
                "--actor", "Serena:player:nonbinary",
                "--actor", "bandit:monster:female",
                "--template", "@1, @2, and @2sc see @3d.",
            ])
        assert exit_code == 0
        assert buf.getvalue().rstrip("\n") == (
            "Caels, Serena, and They see the bandit."
        )

    def test_no_actors_is_rejected_by_argparse(self):
        """``--actor`` is required."""
        with pytest.raises(SystemExit):
            parse_template.main(["--template", "@1 waves."])

    def test_template_and_file_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            parse_template.main([
                "--actor", "Caels:player:male",
                "--template", "@1 waves.",
                "--template-file", "nope.txt",
            ])
