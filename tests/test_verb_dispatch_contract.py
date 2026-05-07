"""Verb-dispatch contract tests — the dispatcher's three-state
return semantics and chain-walk behavior.

Filed 2026-05-07 per the verb-dispatch refactor retrospective
review (`feedback_subagent_review_pattern.md`). The reviewer
flagged that several contract behaviors lacked direct test coverage:

- ``handle_verb`` return-value semantics: ``None`` falls through,
  ``""`` silent-consumes (stops chain, no render), non-empty
  string renders.
- ``Creature.handle_verb`` collapses ``on_social``'s ``""`` return
  to ``None`` via ``return result or None``. Whether this is right
  or accidentally lossy is open (task #61), but the current
  behavior should at least be pinned.

These tests exercise the dispatcher contract directly via
``walk_token_chain`` and the ``handle_verb`` wrappers — no Discord,
no game setup beyond what the chain walk needs.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from caldanai.lib.rpg.helpers.verbs import walk_token_chain


# ---------------------------------------------------------------------------
# Three-state return semantics
# ---------------------------------------------------------------------------


class _StubResponder:
    """Minimal :class:`VerbResponder` for chain-walk testing.
    Configurable token-match + handle_verb return.
    """

    def __init__(self, token: str, return_value):
        self._token = token
        self._return = return_value
        self.handle_verb_called = False

    def matches_token(self, token):
        return token == self._token

    def handle_verb(self, verb, game, actor, *, invocation="", **kwargs):
        self.handle_verb_called = True
        return self._return


class TestThreeStateReturn:
    """The Protocol contract: ``None`` = fall through, ``""`` =
    silent consume (stop chain), non-empty = render. The
    dispatcher (``dispatch_expressive_verb`` in
    ``helpers/verb_dispatch.py``) is what acts on these returns;
    these tests pin the chain walker yields what the dispatcher
    will see.
    """

    def _make_game_with_passerby_token_match(self, responder):
        """Mount a stub responder onto ``game.passerby`` so
        ``walk_token_chain`` finds it via the canonical priority
        order (passerby → silhouette → monster → static_object →
        player_fuzzy)."""
        return SimpleNamespace(
            passerby=responder,
            pending_silhouette=None,
            monster=None,
            room0=None,
            player_manager=SimpleNamespace(players={}),
        )

    def test_chain_yields_first_token_matching_responder(self):
        """walk_token_chain finds the responder by token; whether
        the responder ultimately returns None / "" / str is the
        dispatcher's concern, not the walker's."""
        responder = _StubResponder("wagoneer", return_value="line")
        game = self._make_game_with_passerby_token_match(responder)
        candidates = list(walk_token_chain(game, "wagoneer"))
        assert candidates == [responder]

    def test_chain_yields_nothing_when_no_responder_matches(self):
        """No matching responder → chain is empty. Dispatcher will
        fall through to the bad-token miss path."""
        responder = _StubResponder("wagoneer", return_value="line")
        game = self._make_game_with_passerby_token_match(responder)
        candidates = list(walk_token_chain(game, "herbalist"))
        assert candidates == []


# ---------------------------------------------------------------------------
# Creature.handle_verb empty-string→None collapse
# ---------------------------------------------------------------------------


class TestCreatureHandleVerbCollapse:
    """``Creature.handle_verb`` is implemented as
    ``return self.on_social(verb, actor, invocation or verb) or None``
    — an empty string from ``on_social`` collapses to ``None``,
    making it indistinguishable from "verb not handled."

    Whether this is intentional (monsters never want silent-consume)
    or accidentally lossy is the open question on task #61. These
    tests pin CURRENT behavior so a future change to the collapse
    semantics is caught loudly.
    """

    def _make_creature(self, on_social_return):
        """Build a minimal creature-shape object whose handle_verb
        we can call directly. Avoids the full Creature constructor
        (which expects channel/game state)."""
        from caldanai.lib.rpg.creatures import Creature
        creature = Creature.__new__(Creature)
        # Stub on_social; that's the only thing handle_verb reads.
        creature.on_social = MagicMock(return_value=on_social_return)
        return creature

    def test_empty_string_from_on_social_collapses_to_none(self):
        """Documented current behavior: on_social returns "",
        handle_verb returns None. This means a monster claiming
        "consumed silent" is indistinguishable from "verb not
        handled" at the dispatcher level. Open: task #61.
        """
        creature = self._make_creature(on_social_return="")
        result = creature.handle_verb(
            "glare", game=MagicMock(), actor=MagicMock(),
            invocation="glare",
        )
        assert result is None

    def test_none_from_on_social_returns_none(self):
        """on_social returns None → handle_verb returns None.
        Standard 'verb not handled' fall-through."""
        creature = self._make_creature(on_social_return=None)
        result = creature.handle_verb(
            "glare", game=MagicMock(), actor=MagicMock(),
            invocation="glare",
        )
        assert result is None

    def test_nonempty_string_passes_through(self):
        """on_social returns a real line → handle_verb returns it
        unchanged. Standard 'render this' path."""
        creature = self._make_creature(
            on_social_return="The bandit grins lopsidedly.",
        )
        result = creature.handle_verb(
            "glare", game=MagicMock(), actor=MagicMock(),
            invocation="glare",
        )
        assert result == "The bandit grins lopsidedly."


# ---------------------------------------------------------------------------
# Creature.on_social bland-line fallback (#61 fix)
# ---------------------------------------------------------------------------


class TestCreatureBlandLineFallback:
    """Per #61 fix 2026-05-07: when a warmth-aware social verb hits
    a creature that doesn't have a SOCIAL_REACTIONS entry for it
    AND the verb isn't ``$hug`` (which goes to ``on_hugged``),
    ``Creature.on_social`` returns a bland *"the bandit does not
    react"* line instead of ``""``. This restores the pre-refactor
    behavior where the social cog's deleted dispatcher rendered
    the line directly.

    Caels' direction (2026-05-07): the bland line is the LAST check
    inside ``on_social`` — runs only after SOCIAL_REACTIONS lookup
    and the hug delegation, so creature-specific reactions still
    win. Subclass overrides ``return super().on_social(...)`` to
    pick up the fallback (Bandit's high-five branch demonstrates
    the pattern).
    """

    def _make_bare_creature(self):
        """Build a Creature shape that has no SOCIAL_REACTIONS dict
        and no on_hugged customization. Bypasses the full Creature
        constructor (which expects channel + game state)."""
        from caldanai.lib.rpg.creatures import Creature
        creature = Creature.__new__(Creature)
        # name is needed for the parser's @1 rendering of "the X"
        # via @1Dc form. Mark it article-using ("the bandit").
        creature.name = "bandit"
        creature.uses_article = True
        # Pronouns dict for parser fallback (the bland line uses
        # @1Dc + @2np; pronouns aren't directly hit but parser
        # needs the dict to exist).
        from collections import defaultdict
        creature.pronouns = defaultdict(lambda: "they")
        return creature

    def _make_actor(self, name="Caels"):
        actor = MagicMock()
        actor.name = name
        actor.uses_article = False
        from collections import defaultdict
        actor.pronouns = defaultdict(lambda: "they")
        return actor

    def test_known_warmth_verb_renders_bland_line(self):
        """``$glare`` against a bandit with no SOCIAL_REACTIONS
        entry returns the bland line — pre-refactor behavior."""
        creature = self._make_bare_creature()
        result = creature.on_social("glare", self._make_actor(), "glare")
        assert "does not react" in result
        # The line includes both the creature ("the bandit") and
        # the actor ("Caels's"); confirm both render.
        assert "bandit" in result.lower()
        assert "caels" in result.lower()
        assert "glare" in result.lower()

    def test_unknown_verb_returns_empty(self):
        """A verb not in ``warmth.SOCIAL_COMMANDS`` (e.g. a typo
        or non-warmth verb) returns ``""`` — chain falls through.
        The bland-line is gated to known warmth-aware verbs only."""
        creature = self._make_bare_creature()
        result = creature.on_social("flarble", self._make_actor(), "flarble")
        assert result == ""

    def test_handle_verb_passes_bland_line_through(self):
        """The wrapper's ``return result or None`` collapse
        preserves the non-empty bland line; chain stops at the
        creature, line renders."""
        creature = self._make_bare_creature()
        result = creature.handle_verb(
            "salute", game=MagicMock(), actor=self._make_actor(),
            invocation="salute",
        )
        assert result is not None
        assert "does not react" in result

    def test_social_reactions_entry_wins_over_bland_line(self):
        """If a creature has a SOCIAL_REACTIONS entry for the verb,
        that entry wins — bland-line is the LAST fallback, not a
        replacement."""
        creature = self._make_bare_creature()
        creature.SOCIAL_REACTIONS = {
            "glare": "@1Dc bares teeth at @2.",
        }
        result = creature.on_social("glare", self._make_actor(), "glare")
        assert "does not react" not in result
        assert "bares teeth" in result


# ---------------------------------------------------------------------------
# StaticObjectPlugin.handle_verb gates on SUPPORTED_VERBS
# ---------------------------------------------------------------------------


class TestStaticObjectHandleVerbGate:
    """``StaticObjectPlugin.handle_verb`` returns ``None`` for verbs
    not in ``SUPPORTED_VERBS``, allowing the chain to fall through
    to the next responder. This is the canonical "consumed silent
    vs fall through" distinction in action: a static object that
    doesn't support a verb shouldn't claim it.
    """

    def test_unsupported_verb_returns_none(self):
        """A campfire shouldn't claim ``$fistbump`` — it's not in
        its SUPPORTED_VERBS, so handle_verb returns None and the
        chain continues past it."""
        from caldanai.lib.rpg.world.objects.campfire import Campfire
        cf = Campfire()
        result = cf.handle_verb(
            "fistbump", game=MagicMock(), actor=MagicMock(),
        )
        assert result is None

    def test_supported_verb_routes_through(self):
        """A supported verb routes through to ``on_verb`` (which
        may itself return None / "" / str — that's the on_verb's
        contract, not handle_verb's gate)."""
        from caldanai.lib.rpg.world.objects.campfire import Campfire
        cf = Campfire()
        # ``$gaze`` is in Campfire's SUPPORTED_VERBS; handle_verb
        # gates pass and on_verb fires. We don't assert on the
        # return content here — just that it isn't None (i.e. the
        # gate let it through).
        actor = MagicMock()
        actor.name = "Caels"
        actor.uses_article = False
        from collections import defaultdict
        actor.pronouns = defaultdict(lambda: "they")
        game = MagicMock()
        game.game_clock = MagicMock()
        game.game_clock.get_time_of_day.return_value = "morning"
        result = cf.handle_verb("gaze", game=game, actor=actor)
        assert result is not None


# ---------------------------------------------------------------------------
# kwargs forwarding through handle_verb → on_verb (regression for #63)
# ---------------------------------------------------------------------------


class TestHandleVerbKwargsForwarding:
    """Per #63 fix 2026-05-07: ``StaticObjectPlugin.handle_verb``
    forwards kwargs by name to ``on_verb``, not as positional args.
    The earlier shape unpacked ``kwargs.values()`` which was
    insertion-order-dependent. Pins the new contract.
    """

    def test_kwarg_lands_by_name(self):
        """``fuel_arg=<token>`` arrives at on_verb as a kwarg, not
        a positional arg. Future-proofing for additional verb
        kwargs whose names matter, not their order."""
        from caldanai.lib.rpg.world.objects.campfire import Campfire
        cf = Campfire()
        cf.on_verb = MagicMock(return_value="fed")
        cf.handle_verb(
            "feed", game=MagicMock(), actor=MagicMock(),
            fuel_arg="stick",
        )
        cf.on_verb.assert_called_once()
        # Verb is positional (always), fuel_arg is kwarg-by-name.
        assert cf.on_verb.call_args.args[0] == "feed"
        assert cf.on_verb.call_args.kwargs.get("fuel_arg") == "stick"
