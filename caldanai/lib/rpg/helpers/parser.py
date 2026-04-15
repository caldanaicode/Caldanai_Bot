"""Narration token parser.

Narration strings embed tokens that get resolved against a tuple of
actors passed to :func:`parse`. Actor indices are 1-based.

Token types
-----------

**Actor tokens** — ``@<actor>[form...]``. Form letters concatenate
after the actor number and modify the substitution:

- **Article** forms (prepend): ``d`` (definite), ``i`` (indefinite).
- **Pronoun** forms (replace name with pronoun): ``s`` subjective,
  ``o`` objective, ``p`` possessive, ``a`` adjective, ``r`` reflexive.
- **Noun-mode** prefix (``n``): the *next* letter is interpreted as a
  morphology on the actor's *name* rather than a pronoun form. Only
  ``np`` (noun-possessive, e.g. ``"Caels's"``, ``"the werewolf's"``)
  is distinct from the bare name; other combinations collapse to the
  name and are effectively no-ops.
- **Casing** forms (presentation, applied last): ``c`` capitalize,
  ``l`` lower, ``t`` title, ``u`` upper.

Order within content forms is preserved (left-to-right). Casing forms
are deferred and applied at the end regardless of where they appear,
so ``@1cs`` and ``@1sc`` both produce the capitalized pronoun. Unknown
form letters are logged and skipped.

**Verb-agreement tokens** — ``@<actor>v(<singular>|<plural>)``. Picks
the singular or plural form based on ``actor.plural_verbs`` (``True``
for they/them pronoun sets; ``False`` otherwise). Use after a pronoun
subject: ``@1s @1v(attacks|attack)`` → ``"she attacks"`` or ``"they
attack"``. With a *name* subject, write the singular verb literally —
English singular-name subjects always take singular-verb agreement
regardless of the person's pronouns ("Ezra attacks" even if Ezra uses
they/them).
"""

import re
from re import Match
from typing import Tuple, List

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.enums import Pronouns


_log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Form-letter constants — single source of truth for every letter the
# parser recognizes. Narration authors and readers can grep for these
# names instead of memorizing a dict layout. Pronoun forms are derived
# from ``Pronouns.form`` so adding a new pronoun automatically extends
# the parser without touching this file.
# ---------------------------------------------------------------------------

# Articles — prepend to the actor's name.
FORM_DEFINITE_ARTICLE = "d"    # @1d  → "the cyclops"
FORM_INDEFINITE_ARTICLE = "i"  # @1i  → "a cyclops" / "an ogre"

# Noun-mode prefix — the next letter is interpreted as a morphology
# on the actor's name rather than a pronoun form.
FORM_NOUN_MODE = "n"           # @1np → "Caels's" / "the werewolf's"

# Casing — applied last regardless of position in the token.
FORM_CAPITALIZE = "c"          # first letter up, rest unchanged lower
FORM_LOWER = "l"
FORM_TITLE = "t"
FORM_UPPER = "u"

_ARTICLE_FORMS = frozenset({FORM_DEFINITE_ARTICLE, FORM_INDEFINITE_ARTICLE})

# Pronoun lookup derived from the Pronouns enum itself — the form
# letter is defined on ``Pronouns.form`` (first char of the name by
# default), so this dict is just the inverse mapping.
_PRONOUN_FORMS = {p.form: p for p in Pronouns}

_CASING_FORMS = {
    FORM_CAPITALIZE: "capitalize",
    FORM_LOWER:      "lower",
    FORM_TITLE:      "title",
    FORM_UPPER:      "upper",
}

# Subjective-pronoun values that imply plural verb agreement. Looked
# up case-insensitively by ``Creature.plural_verbs``; unknown values
# (neopronouns, non-English sets) fall back to singular agreement,
# which is the conventional default for English neopronouns.
PLURAL_VERB_SUBJECTIVES = frozenset({"they"})


def _noun_possessive(name: str) -> str:
    """Return the possessive form of a noun (actor name or article +
    name). Modern AP style: always append ``'s``, regardless of
    whether the name ends in 's'. ``"Caels"`` → ``"Caels's"``,
    ``"the werewolf"`` → ``"the werewolf's"``."""
    return f"{name}'s"

# ---------------------------------------------------------------------------
# Regexes
# ---------------------------------------------------------------------------

# Verb-agreement token: @<actor>v(<singular>|<plural>). Non-greedy
# content capture that stops at the first close paren — so nested
# parens aren't supported (none needed in narration flavor).
verbRegex = re.compile(r"@(?P<actor>\d+)v\((?P<content>[^)]*)\)")

# Actor token: @<actor><form letters>.
actorRegex = re.compile(r"@(?P<actor>\d+)(?P<form>\w*)")


# ---------------------------------------------------------------------------
# Verb-agreement handler
# ---------------------------------------------------------------------------


def _process_verb(match: Match, actors: Tuple) -> str:
    m = match.groupdict()
    num = int(m["actor"]) - 1
    original = match.group(0)
    content = m["content"]

    # Parse and validate the singular|plural content. Malformed tokens
    # still render *something* (best effort) and log a warning.
    parts = content.split("|")
    if len(parts) == 1:
        _log.warning(
            f"Verb token {original!r} is missing a '|' separator; "
            f"using {parts[0]!r} for both singular and plural."
        )
        singular = plural = parts[0]
    elif len(parts) > 2:
        _log.warning(
            f"Verb token {original!r} has extra '|' separators; "
            f"using the first two forms ({parts[0]!r}, {parts[1]!r})."
        )
        singular, plural = parts[0], parts[1]
    else:
        singular, plural = parts[0], parts[1]

    # Resolve the actor for plural_verbs lookup. Fall back to actor 0
    # if the index is out of range — matches _process's tolerance.
    if not actors:
        _log.error(
            f"Verb token {original!r} parsed with no actors supplied."
        )
        return original
    if 0 <= num < len(actors):
        actor = actors[num]
    else:
        _log.warning(
            f"Verb token {original!r} references actor {num + 1} but "
            f"only {len(actors)} actor(s) were supplied; "
            f"using actor 1 for agreement."
        )
        actor = actors[0]

    is_plural = bool(getattr(actor, "plural_verbs", False))
    return plural if is_plural else singular


# ---------------------------------------------------------------------------
# Actor-token handler
# ---------------------------------------------------------------------------


def _process(match: Match, actors: Tuple) -> str:
    if match is None:
        return ""

    if len(actors) == 0:
        _log.error(
            "Error parsing message for actors. No actors were supplied. "
            f"{match.groupdict()}"
        )
        return match.group(0)

    m = match.groupdict()
    if m["actor"] and m["actor"].isnumeric() and 0 <= (num := int(m["actor"]) - 1) < len(actors):
        actor = actors[num]
    else:
        actor = actors[0]
    form = m["form"].lower() if m["form"] else ""

    # Pre-parse form letters into buckets:
    # - ``content_forms`` are articles / pronouns / noun-mode ops, each
    #   tagged with whether the preceding ``n`` flipped them into
    #   noun-morphology interpretation.
    # - ``casing_forms`` are deferred to after content processing so
    #   casing letters can appear anywhere in the token.
    # ``noun_pending`` tracks an active ``n`` prefix that applies to
    # the very next content letter only, then resets.
    content_forms: List[Tuple[str, bool]] = []
    casing_forms: List[str] = []
    noun_pending = False

    for f in form:
        if f == FORM_NOUN_MODE:
            noun_pending = True
            continue
        if f in _CASING_FORMS:
            casing_forms.append(f)
            # Casing letters don't participate in noun-mode; if an
            # ``n`` was pending it resets without effect.
            noun_pending = False
            continue
        if f in _ARTICLE_FORMS or f in _PRONOUN_FORMS:
            content_forms.append((f, noun_pending))
            noun_pending = False
            continue
        _log.warning(
            f"Unknown form letter {f!r} in narration token "
            f"@{num + 1}{form}; ignoring."
        )
        noun_pending = False

    result = actor.name

    for f, is_noun in content_forms:
        if is_noun:
            # Noun-mode: only possessive has a meaningful distinct
            # morphology on names. Other pronoun forms reduce to the
            # bare name (already in ``result``) — no-op.
            if f in _PRONOUN_FORMS and _PRONOUN_FORMS[f] == Pronouns.POSSESSIVE:
                result = _noun_possessive(result)
            # All other is_noun + letter combinations (including
            # articles under ``n``, which don't make sense) leave
            # ``result`` alone.
            continue

        if f == FORM_DEFINITE_ARTICLE:
            # Named entities (players, uniquely-named creatures) opt out
            # of articles via ``uses_article = False``.
            if getattr(actor, "uses_article", True):
                result = f"the {result}"
        elif f == FORM_INDEFINITE_ARTICLE:
            # Creatures can override with ``indefinite_article`` for
            # phonetic exceptions (e.g., "a unicorn" despite the vowel).
            if getattr(actor, "uses_article", True):
                override = getattr(actor, "indefinite_article", None)
                if override:
                    article = override
                else:
                    article = "an" if result and result[0].lower() in "aeiou" else "a"
                result = f"{article} {result}"
        else:
            # Pronoun form. Replaces the entire running value — so a
            # preceding article (``@1ds``) is intentionally clobbered;
            # "the she" reads wrong.
            result = actor.pronouns[_PRONOUN_FORMS[f]]

    for f in casing_forms:
        result = getattr(result, _CASING_FORMS[f])()

    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse(msg: str, *actors) -> str:
    """
    Returns a string where placeholders have been replaced with the proper nouns/pronouns/etc.

    :param msg: The string to parse
    :param actors: A tuple containing the actors in the message, ordered by their @ position in the message
    :return: The original string with all @ flags replaced appropriately
    """

    # Verb-agreement tokens first, so their ``@<n>v(...)`` shape is
    # consumed before the actor regex (whose ``\w*`` form-letter class
    # would otherwise greedily eat the ``v`` and leave ``(...)`` as
    # literal text).
    msg = verbRegex.sub(lambda m: _process_verb(m, actors), msg)
    return actorRegex.sub(lambda m: _process(m, actors), msg)


def item_list_to_string(items: List) -> str:
    """
    Takes a list of items and returns a comma-separated, English-appropriate string.

    :param items: The list of items to stringify.
    :return: The text representation.
    """

    names = [i.get_full_name() for i in items if i is not None]
    if len(names) > 1:
        return ", ".join(names[:-1]) + " and " + names[-1]
    return ", ".join(names)
