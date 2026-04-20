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
- **Mention** form (``m``): for actors with a Discord ``user_id``
  (Players), emits ``<@!user_id>`` so the message produces a
  clickable @-ping in channel. Monsters / NPCs fall through to the
  other form letters transparently. When a mention fires, non-
  possessive form letters (articles, subject/object/reflexive
  pronouns, casing) are ignored — mention tags are opaque and
  don't meaningfully compose with those. Possessive form letters
  (``p``, ``a``, or noun-mode ``np``) ARE respected and upgrade
  the emit to ``<@!user_id>'s`` so constructions like ``@1mp
  dagger slides between @2p ribs`` render cleanly.
- **Casing** forms (presentation, applied last): ``c`` capitalize,
  ``l`` lower, ``t`` title, ``u`` upper.

Order within content forms is preserved (left-to-right). Casing forms
are deferred and applied at the end regardless of where they appear,
so ``@1cs`` and ``@1sc`` both produce the capitalized pronoun. Unknown
form letters are logged and skipped.

**Case-sensitive form letters (ergonomic shortcut)**: if any form
letter is written in UPPERCASE, the output is implicitly capitalized
(equivalent to appending ``c``). So ``@1A`` ≡ ``@1ac`` → ``"His"``,
``@1D`` ≡ ``@1dc`` → ``"The bandit"``, ``@1Np`` ≡ ``@1npc`` →
``"The bandit's"``. Lowercase form letters render lowercase as
always. The explicit casing letters (``c``/``l``/``t``/``u``) remain
useful for bare-name casing (``@1c`` = ``"Cyclops"``), title case
over multi-word names (``@1dt`` = ``"The Dread Cyclops"``), and full
upper (``@1u`` = ``"CYCLOPS"``). Explicit casing always wins over
the implicit uppercase-letter capitalization.

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

# Mention form — for actors carrying a Discord ``user_id`` (Players),
# renders the Discord-mention tag ``<@!user_id>`` so the message
# produces a clickable @-ping in channel. For actors without a
# ``user_id`` (monsters, NPCs), falls back to normal form-letter
# processing. Dominant when present + available — mention tags are
# opaque and don't compose meaningfully with articles / pronouns /
# casing.
FORM_MENTION = "m"             # @1m → "<@!111111111111111111>"

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


def article(word: str) -> str:
    """Return ``'an'`` if *word* starts with a vowel, otherwise ``'a'``.

    Orthographic-only check (first-letter vowel match); doesn't handle
    phonetic edge cases like ``"a unicorn"`` or ``"an hour"``. Callers
    with known exceptions should override at their layer. Empty or
    falsy *word* yields ``'a'``."""
    return "an" if word and word[0].lower() in "aeiou" else "a"

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
    form = m["form"] if m["form"] else ""

    # Pre-parse form letters into buckets:
    # - ``content_forms`` are articles / pronouns / noun-mode ops, each
    #   tagged with whether the preceding ``n`` flipped them into
    #   noun-morphology interpretation.
    # - ``casing_forms`` are deferred to after content processing so
    #   casing letters can appear anywhere in the token.
    # ``noun_pending`` tracks an active ``n`` prefix that applies to
    # the very next content letter only, then resets.
    #
    # **Case-sensitive form letters**: form dispatch uses the
    # lowercased letter, but the ORIGINAL case is also consulted —
    # any uppercase form letter flags an implicit ``c`` (capitalize)
    # that's applied after content processing. This lets authors
    # write ``@1A`` as shorthand for ``@1ac`` (``"His"`` vs
    # ``"his"``), ``@1D`` for ``@1dc`` (``"The bandit"`` vs
    # ``"the bandit"``), ``@1Np`` for ``@1npc`` (``"The bandit's"``),
    # etc. The explicit casing letters ``c`` / ``l`` / ``t`` / ``u``
    # keep working as edge-case overrides (bare-name capitalization
    # via ``@1c``, title case via ``@1dt``, full upper via ``@1u``).
    content_forms: List[Tuple[str, bool]] = []
    casing_forms: List[str] = []
    noun_pending = False
    implicit_capitalize = False
    mention_pending = False

    for raw_f in form:
        f = raw_f.lower()
        if raw_f.isupper():
            implicit_capitalize = True
        if f == FORM_NOUN_MODE:
            noun_pending = True
            continue
        if f == FORM_MENTION:
            mention_pending = True
            # ``m`` doesn't participate in noun-mode; if one was
            # pending it resets without effect.
            noun_pending = False
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

    # An uppercase letter anywhere in the form string implies ``c``
    # (capitalize). Explicit casing letters (``c``/``l``/``t``/``u``)
    # always win — if ANY explicit casing was written, the implicit
    # flag is suppressed. Authors who write ``@1Al`` clearly want
    # lowercase output despite the capital ``A``, and ``@1Ac`` /
    # ``@1Au`` should behave as if the explicit letter were written
    # alone.
    if implicit_capitalize and not casing_forms:
        casing_forms.append(FORM_CAPITALIZE)

    # Mention-form short-circuit: if ``m`` was in the form and the
    # actor carries a Discord ``member`` (Players), emit the mention
    # string via ``discord.Member.mention`` (the library's canonical
    # format — avoids this module hardcoding ``<@!user_id>`` against
    # discord.py's own versioning). Most form letters don't compose
    # meaningfully with the opaque mention tag (it's already a name-
    # substitute; articles and pronouns don't apply). Possessive
    # forms are the exception — ``@1mp dagger`` / ``@1ma dagger`` /
    # ``@1mnp dagger`` all read naturally as
    # ``<mention>'s dagger``, so a possessive content-form letter
    # (``p`` or ``a``, including noun-mode ``np``) in the same token
    # upgrades the emit to the possessive mention. Other form
    # letters and casing are ignored when mention fires. Fall-
    # through (no ``member``) lets the normal processing path handle
    # monsters / NPCs transparently.
    if mention_pending:
        member = getattr(actor, "member", None)
        mention = getattr(member, "mention", None) if member is not None else None
        if mention:
            is_possessive = any(
                f in _PRONOUN_FORMS
                and _PRONOUN_FORMS[f]
                in (Pronouns.POSSESSIVE, Pronouns.ADJECTIVE)
                for f, _ in content_forms
            )
            return f"{mention}'s" if is_possessive else mention

    result = actor.name

    for f, is_noun in content_forms:
        if is_noun:
            # Noun-mode: only possessive has a meaningful distinct
            # morphology on names. Other pronoun forms reduce to the
            # bare name (already in ``result``) — no-op.
            if f in _PRONOUN_FORMS and _PRONOUN_FORMS[f] == Pronouns.POSSESSIVE:
                # Article-using creatures get the article prepended
                # automatically — ``@Nnp`` should produce "the
                # werewolf's", not a bare "werewolf's" that reads as
                # a grammar error (confirms the docstring's intent at
                # the top of the file). An explicit ``@Ndnp`` still
                # works by the article path already setting
                # ``result = "the werewolf"`` before this branch
                # fires; the startswith guard keeps it from doubling
                # up to "the the werewolf's".
                if (
                    getattr(actor, "uses_article", True)
                    and not result.startswith("the ")
                ):
                    result = f"the {result}"
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
                chosen = override if override else article(result)
                result = f"{chosen} {result}"
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


# ===========================================================================
# Narrator-output lint
# ===========================================================================
#
# Grammar-level validation for LLM-generated narrative strings, before
# they're handed to :func:`parse`. The parser is the single source of
# truth for what a well-formed narration template looks like, so the
# lint rules that flag malformed templates live here alongside the
# rendering logic.
#
# Auto-fixes (deterministic):
#
# 1. Invalid noun-mode combos — ``@Nno`` / ``@Nns`` / ``@Nna`` /
#    ``@Nnr`` collapse to bare name in the parser because noun-mode
#    only pairs with ``p``. Strip the stray ``n``.
# 2. Duplicate ``@Nm*`` mentions per actor per narrative string —
#    keep the first, strip ``m`` from the rest.
# 3. Sentence-start lowercase — uppercase the first form letter.
# 4. Mid-sentence over-capitalization — lowercase the form.
#
# Warnings (semantic, not auto-fixed):
#
# 5. Literal English pronouns outside tokens — surface the pattern
#    for operator review. ``its`` / ``itself`` get a softened warning
#    because they legitimately reference inanimate objects (armor,
#    weapons, locations); a whitelist of ``its <innocent-noun>``
#    phrases fully suppresses the warning for common object-anchored
#    constructions (``its wearer``, ``its blade``, ``its corner``).
#
# Operator-facing wrapper lives at ``tools/postprocess_narrator_output``
# for CLI-based poking; the game's API-narrator integration calls
# :func:`lint_output` directly on Sonnet's JSON output before parse.

# ---------------------------------------------------------------------------
# Regex catalog — single source of truth for the lint patterns.
# ---------------------------------------------------------------------------

# Actor token (same shape as ``actorRegex`` but with a more permissive
# character class for the form letters so the lint pass can reason
# about them as a unit).
_LINT_ACTOR_TOKEN_RE = re.compile(r"@(?P<num>\d+)(?P<form>[a-zA-Z]*)")

# Verb-agreement token, for detection so the lint pass doesn't munge
# its ``(singular|plural)`` payload.
_LINT_VERB_TOKEN_RE = re.compile(r"@\d+v\([^)]*\)")

# Invalid noun-mode: ``@<digits>[nN]`` NOT followed by ``p`` / ``P``.
# Run to fixed-point so ``@1nno`` → ``@1no`` → ``@1o``.
_INVALID_NOUN_MODE_RE = re.compile(r"@(\d+)[nN](?![pP])")

# Sentence-ending punctuation preceding a new-sentence token.
_SENTENCE_END_RE = re.compile(r"[.!?]\s+$")

# English literal pronouns — both lowercase and uppercase forms caught
# via case-insensitive matching.
_LITERAL_PRONOUNS = frozenset({
    "he", "she", "they", "him", "her", "them",
    "his", "hers", "their", "theirs", "its",
    "himself", "herself", "themself", "themselves", "itself",
})

_LITERAL_PRONOUN_RE = re.compile(
    r"\b(" + "|".join(sorted(_LITERAL_PRONOUNS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Pronouns that often reference non-actor items (armor, weapons,
# corpses, buildings) — softer "verify reference" warning rather than
# hard "should be tokenized."
_AMBIGUOUS_PRONOUNS = frozenset({"its", "itself"})

# Nouns that, when following ``its``, almost certainly mean the
# ``its`` refers to an inanimate object. Suppresses the warning
# entirely for those cases. Starts small and grows as patterns
# surface — Sonnet suggested this whitelist during peer review.
_INNOCENT_ITS_NOUNS = frozenset({
    # Person-but-anchored-to-object
    "wearer", "owner", "bearer", "holder", "wielder",
    # Weapon parts
    "blade", "edge", "hilt", "tip", "point", "pommel", "grip",
    "haft", "shaft",
    # Armor / shield parts
    "surface", "face", "plating", "rim", "straps",
    # Physical properties of objects
    "weight", "length", "reach", "balance", "heft",
    # Magical / spell properties
    "magic", "power", "glow", "aura", "charge",
    # Structural / locational
    "corner", "end", "side", "depths", "mouth",
    # Generic object properties
    "core", "heart", "body",
})

_ITS_FOLLOWING_NOUN_RE = re.compile(r"\s+(\w+)")


# ---------------------------------------------------------------------------
# Individual fixers
# ---------------------------------------------------------------------------


def _strip_invalid_noun_mode(s: str) -> Tuple[str, int]:
    """``@Nno`` / ``@Nns`` / ``@Nna`` / ``@Nnr`` etc. (noun-mode
    followed by a non-``p`` letter) silently discards the ``n`` in
    the parser and renders the bare name — almost never what the
    narrator intended. Strip the stray ``n`` so the remaining form
    letter processes correctly. Iterates to fixed-point so
    ``@1nnno`` collapses cleanly to ``@1o``.
    """
    total = 0
    while True:
        fixed, count = _INVALID_NOUN_MODE_RE.subn(r"@\1", s)
        total += count
        if fixed == s:
            break
        s = fixed
    return s, total


def _dedupe_mentions(s: str) -> Tuple[str, int]:
    """``@Nm*`` is allowed once per actor per narrative string.
    Keeps the first mention per actor and strips ``m`` / ``M`` from
    any later mention tokens for the same actor in the same string.
    Non-mention and verb-agreement tokens are untouched.
    """
    seen: set = set()
    total = [0]

    def _sub(match: "re.Match") -> str:
        num = match.group("num")
        form = match.group("form") or ""
        # Skip verb-agreement token starts (``@Nv``).
        if "v" in form.lower():
            return match.group(0)
        has_m = "m" in form.lower()
        if not has_m:
            return match.group(0)
        if num in seen:
            new_form = "".join(c for c in form if c.lower() != "m")
            total[0] += 1
            return f"@{num}{new_form}"
        seen.add(num)
        return match.group(0)

    fixed = _LINT_ACTOR_TOKEN_RE.sub(_sub, s)
    return fixed, total[0]


def _fix_capitalization(s: str) -> Tuple[str, int]:
    """At sentence start: tokens whose form is all-lowercase get
    their first form letter uppercased. Mid-sentence: tokens whose
    form has any uppercase letter get fully lowercased. Skips
    verb-agreement tokens and tokens with no form letters (bare
    ``@N``).
    """
    total = 0
    out: List[str] = []
    last_end = 0

    for match in _LINT_ACTOR_TOKEN_RE.finditer(s):
        start = match.start()
        end = match.end()
        num = match.group("num")
        form = match.group("form") or ""

        # Skip verb-agreement tokens — their shape is @Nv(...) and
        # the ``(`` immediately following is the signal.
        if end < len(s) and s[end] == "(":
            out.append(s[last_end:end])
            last_end = end
            continue

        # Empty form — bare @N. Nothing to capitalize.
        if not form:
            out.append(s[last_end:end])
            last_end = end
            continue

        prefix = s[:start]
        is_sentence_start = (
            start == 0
            or bool(_SENTENCE_END_RE.search(prefix))
        )

        has_upper = any(c.isupper() for c in form)
        all_lower = all(c.islower() for c in form)

        new_form = form
        if is_sentence_start and all_lower:
            new_form = form[0].upper() + form[1:]
        elif (not is_sentence_start) and has_upper:
            new_form = form.lower()

        if new_form != form:
            total += 1

        out.append(s[last_end:start])
        out.append(f"@{num}{new_form}")
        last_end = end

    out.append(s[last_end:])
    return "".join(out), total


def _scan_literal_pronouns(s: str) -> List[str]:
    """Find English pronouns appearing as plain text (outside any
    actor or verb-agreement token). Returns a list of human-readable
    warnings. Can't auto-fix because disambiguating which actor a
    pronoun refers to needs semantic understanding. Neuter pronouns
    (``its``, ``itself``) get a softened wording because they
    legitimately reference inanimate objects; a ``its <innocent-noun>``
    whitelist fully suppresses the warning for common object-anchored
    phrases.
    """
    stripped = _LINT_VERB_TOKEN_RE.sub("", s)
    warnings: List[str] = []
    for match in _LITERAL_PRONOUN_RE.finditer(stripped):
        word = match.group(1).lower()
        # Per-occurrence whitelist: ``its <innocent-noun>`` is
        # suppressed entirely.
        if word == "its":
            tail = stripped[match.end():]
            follow_match = _ITS_FOLLOWING_NOUN_RE.match(tail)
            if follow_match and follow_match.group(1).lower() in _INNOCENT_ITS_NOUNS:
                continue
        if word in _AMBIGUOUS_PRONOUNS:
            msg = (
                f"literal pronoun {word!r} — verify reference "
                f"(may legitimately refer to a non-actor, e.g. armor / weapon / "
                f"location; or may be a leak for a neuter-pronoun actor like a hydra)"
            )
        else:
            msg = f"literal pronoun {word!r} in narrative — should be tokenized"
        # Deduplicate within a single string so "her ... her" only
        # warns once.
        if msg not in warnings:
            warnings.append(msg)
    return warnings


# ---------------------------------------------------------------------------
# Public lint API
# ---------------------------------------------------------------------------


def lint_narrative(s: str) -> Tuple[str, List[str]]:
    """Run all lint passes on a single narrative string. Returns the
    cleaned string plus a list of human-readable warnings (counts of
    auto-fixes applied and any non-auto-fixable patterns detected).
    """
    warnings: List[str] = []

    s, n = _strip_invalid_noun_mode(s)
    if n:
        warnings.append(f"stripped {n} invalid @Nn<letter> combo(s) (non-p after noun-mode)")

    s, n = _dedupe_mentions(s)
    if n:
        warnings.append(f"dropped {n} duplicate @Nm* mention(s)")

    s, n = _fix_capitalization(s)
    if n:
        warnings.append(f"adjusted case on {n} token(s)")

    for w in _scan_literal_pronouns(s):
        warnings.append(w)

    return s, warnings


def lint_output(obj: "dict") -> Tuple["dict", List[str]]:
    """Lint a narrator output dict. Mutates the dict in place (also
    returns it) and returns aggregated warnings keyed by narrative
    field. Keys processed: ``narrate_attempt``, ``narrate_results``,
    ``narrate_target_death``, ``narrate_attacker_death``. Missing or
    null keys are skipped.
    """
    aggregate: List[str] = []
    for key in (
        "narrate_attempt",
        "narrate_results",
        "narrate_target_death",
        "narrate_attacker_death",
    ):
        val = obj.get(key)
        if not val:
            continue
        new_val, warnings = lint_narrative(val)
        obj[key] = new_val
        for w in warnings:
            aggregate.append(f"{key}: {w}")
    return obj, aggregate


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
