"""Presence-verb cog — low-energy "occupying space" commands that
sit between the social cog (warmth-aware gestures projected outward)
and the world cog (object-targeted actions like $light / $touch).

Six verbs registered:

- ``$lean [target]`` — lean against something, or stand pensive
- ``$sit [target]`` — sit by/on something, or settle where you stand
- ``$rest [target]`` — pause and rest, near something or generally
- ``$ponder [target]`` — direct contemplative attention
- ``$tend [target]`` — small caretaking gesture
- ``$bite [target]`` — fidget / aggressive nip / surprised reaction;
  emotion-ambiguous by design (see
  ``project_verb_adverb_coloring.md``)

Why a separate cog
------------------

These verbs share a "being-here, low-energy" register that doesn't
belong with the social cog's projecting-outward gestures (hug /
glare / wave) or the world cog's object-targeted actions (light /
feed / touch). They also straddle the bare-self-directed and
target-something modes naturally — most read fine either way ($sit
on a stone, $sit where you stand). The world cog already collects
"verbs about your surroundings" but presence verbs are about *your
body in space*, not the surroundings; the cog distinction keeps the
voice register clean as either expands.

Existing self-directed verbs ($pose / $cheer / $cry / $bow / $wave)
stay in the social cog — they're expressive (projecting an
emotion outward) rather than presence-flavored (occupying space).

Each command body is a one-liner that delegates to
:func:`dispatch_expressive_verb` with a per-verb self-directed pool
(emotion-neutral; players steer tone via the not-yet-shipped
adverb argument) and a per-verb bad-token italic.

Reaction authoring lives elsewhere:

- Per-passerby ``SOCIAL_REACTIONS[verb]`` entries (where the verb
  fits the NPC's voice) — see the coverage matrix in the writer-
  agent prompt.
- Per-static-object ``on_verb`` branches (campfire's $bite =
  "fire is delighted", stone field's $lean = "stone is patient",
  etc.) — same coverage matrix.

$bite intentionally has NO passerby reactions in V1 (Caels
2026-05-04: "we'll figure out how to let players be jackasses
later in a way that makes sense").
"""

from typing import Dict, List

from discord.ext.commands import (
    BucketType, Cog, Context, command, cooldown, guild_only,
)

from caldanai.logger import get_logger
from caldanai.lib.rpg.helpers.verb_dispatch import dispatch_expressive_verb


_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Self-directed pools — bare-invocation flavor for each verb.
# ---------------------------------------------------------------------------
#
# Voice rule: emotion-neutral by design. The same player typing
# $bite twice in a minute should NOT read as "thoughtful" then
# "frustrated" — that swing makes the character look manic. Authors
# choose emotion-implying descriptions only when the verb's neutral
# read carries the emotion already (e.g. $cry is sad; $bite is not
# anything). When players want to color the action they'll supply
# an adverb (backlogged in
# ``project_verb_adverb_coloring.md``); until shipped, keep these
# pools to the action without the feeling.
#
# Authoring guide for future additions: stick to physical action +
# observable detail; let the player project the feeling onto the
# moment. Use parser tokens (``@1`` = the actor, with ``@1np`` for
# noun-possessive, ``@1a`` for possessive-adjective, etc. — see the
# cheat-sheet in CLAUDE.md). No dialogue (these are bare-action
# lines, not conversational beats). 6-10 lines per pool.

_LEAN_FLAVOR: List[str] = [
    "*@1 leans against the nearest upright surface, weight shifting onto one shoulder.*",
    "*@1 props @1r on a wagon-pole that isn't there, adjusts, and leans on @1a own arm instead.*",
    "*@1 lets @1a hip find a stone and stays there.*",
    "*@1 plants @1a forearm against a tree and leans on the bone of it.*",
    "*@1 lets @1r tip sideways until something catches the weight.*",
    "*@1 leans @1a shoulder into the cool of an upright stone.*",
    "*@1 takes the weight off one foot, then the other, leaning in between.*",
    "*@1 settles @1a back against the verge and lets @1a knees go a little soft.*",
]

_SIT_FLAVOR: List[str] = [
    "*@1 sits down where @1s stands.*",
    "*@1 lowers @1r onto a flat patch of moss and lets @1a knees stop arguing.*",
    "*@1 finds a stone the right shape for sitting and accepts the offer.*",
    "*@1 folds @1a legs under @1r and settles cross-legged on the dirt.*",
    "*@1 drops to a crouch first, then to a sit, the way tired people do.*",
    "*@1 plants @1r on the nearest sittable thing and breathes out.*",
    "*@1 sits with @1a back against a tree-trunk and watches the clearing for a beat.*",
    "*@1 settles down with the small grunt of a body that walked here.*",
]

_REST_FLAVOR: List[str] = [
    "*@1 rests for a moment, eyes half-closing.*",
    "*@1 lets @1a shoulders drop and stands very still.*",
    "*@1 closes @1a eyes a beat, opens them, hasn't moved.*",
    "*@1 lets @1a head tip back and breathes the clearing in.*",
    "*@1 rolls @1a neck once, slow, and goes still.*",
    "*@1 unstrings @1r the way you'd unstring a bow at the end of a day.*",
    "*@1 stays where @1s is and lets the weight go for a while.*",
    "*@1 plants @1a feet, lets @1a hands hang, and rests standing up.*",
]

_PONDER_FLAVOR: List[str] = [
    "*@1 ponders the middle distance.*",
    "*@1 narrows @1a eyes at a fixed point three paces past anything actually present.*",
    "*@1 turns something over in @1a head, lips moving once without sound.*",
    "*@1 stares at @1a own hand for a beat, then folds it shut.*",
    "*@1 watches a small movement of leaves and seems to file it.*",
    "*@1 stands quiet, weighing a thought that hasn't found its words yet.*",
    "*@1 tilts @1a head a fraction, like @1s heard something just past hearing.*",
    "*@1 holds still long enough that the wind notices and moves around @1o.*",
]

_TEND_FLAVOR: List[str] = [
    "*@1 tends to @1r a moment — adjusts a strap, settles a sleeve, brushes off a cuff.*",
    "*@1 thumbs a smudge of dirt off the back of @1a hand and wipes the thumb on @1a coat.*",
    "*@1 checks a buckle, then the next, then nods to @1r once.*",
    "*@1 retucks the hem of @1a tunic and squares @1a shoulders.*",
    "*@1 brushes leaf-mast off @1a knee with the side of @1a hand.*",
    "*@1 finger-combs @1a hair back and reties whatever's holding it.*",
    "*@1 inspects a small scrape, decides it'll keep, and rolls @1a sleeve back down.*",
    "*@1 brushes a smear off @1a cheek with the back of one wrist.*",
]

_BITE_FLAVOR: List[str] = [
    "*@1 worries at @1a lower lip.*",
    "*@1 catches the tip of @1a own thumb in @1a teeth and lets it go.*",
    "*@1 bites at the air absently.*",
    "*@1 chews the inside of @1a cheek for a beat.*",
    "*@1 tugs at a hangnail with @1a teeth, frowns at the result.*",
    "*@1 bites down on nothing in particular and lets @1a jaw unclench again.*",
    "*@1 catches a strand of @1a own hair between @1a teeth, then spits it out.*",
    "*@1 nips at the corner of @1a knuckle and inspects the mark.*",
]


# ---------------------------------------------------------------------------
# Bad-token templates — rendered when the player supplies a target
# token that no responder claimed (no passerby/monster/object/player
# matched, AND no responder claimed the verb after a token-chain
# walk). Python str.format with ``{name}``/``{verb}``/``{target}``.
# ---------------------------------------------------------------------------

_BAD_TOKEN_TEMPLATES = {
    "lean":   "*{name} leans toward `{target}` and finds nothing to lean on.*",
    "sit":    "*{name} looks for somewhere to sit on `{target}` and gives up.*",
    "rest":   "*{name} settles to rest by `{target}`, but `{target}` isn't here.*",
    "ponder": "*{name} ponders `{target}` — there's nothing here by that name to consider.*",
    "tend":   "*{name} reaches to tend `{target}` and finds only air.*",
    "bite":   "*{name} bites at `{target}` and gets nothing for it.*",
}


# ---------------------------------------------------------------------------
# With-target templates — historical fallback. As of 2026-05-06's V2
# scaffolding, presence verbs are registered in
# ``warmth.SOCIAL_COMMANDS`` and have full warmth-aware
# ``_NARRATION_POOLS`` entries in ``rpg_social_commands.py``, so
# ``Player.handle_verb`` returns a real warmth-resolved line for
# ``$lean @player`` and friends. The dispatcher's
# ``with_target_template`` path now only fires if a target's
# ``handle_verb`` returns ``None`` — which shouldn't happen for
# Player targets going forward.
#
# These templates are kept as a safety net for any future verb
# whose Player path isn't wired (e.g. a new presence verb shipped
# before its warmth pools are filled). Single emotion-neutral line
# per verb. ``@1`` = actor, ``@2`` = mentioned player. Don't delete
# without confirming every presence verb has narration pools in
# ``_NARRATION_POOLS``.
# ---------------------------------------------------------------------------

_WITH_TARGET_TEMPLATES: Dict[str, str] = {
    "lean":   "*@1 leans into a quiet beat near @2.*",
    "sit":    "*@1 sits down beside @2.*",
    "rest":   "*@1 rests near @2 a moment, eyes half-closing.*",
    "ponder": "*@1 ponders the space near @2 for a long beat.*",
    "tend":   "*@1 tends to a strap, @2 within reach.*",
    "bite":   "*@1 nips at the air near @2.*",
}


class RpgPresenceCommands(Cog):
    """Cog for presence-verb dispatch. Each command delegates to
    :func:`dispatch_expressive_verb` with a per-verb self-directed
    pool and bad-token italic. Cog command bodies are intentionally
    thin — all routing logic lives in the unified dispatcher.

    Per-NPC and per-static-object reactions are registered in
    those entities' own ``handle_verb`` / ``on_verb`` methods (see
    coverage matrix). The cog doesn't enumerate them.
    """

    def __init__(self, bot):
        self.bot = bot

    async def _dispatch(
        self,
        ctx: Context,
        verb: str,
        target: str,
        self_directed_pool: List[str],
    ) -> None:
        """Per-verb dispatch wrapper — extracts ``@-mentions`` and
        forwards everything else to :func:`dispatch_expressive_verb`.

        The wrapper exists because presence-verb mention-handling
        differs from social-verb mention-handling: presence verbs
        aren't warmth-aware, so a `$lean @player` resolves through
        the dispatcher's mention path → ``Player.handle_verb`` →
        ``None`` (verb not in ``_NARRATION_POOLS``) → the dispatcher
        falls through to the per-verb ``with_target_template``.
        BotResponder and doppelganger-disguise mention paths still
        work since they're handled inside the dispatcher.
        """
        mentions = ctx.message.mentions or []
        mention = mentions[0] if mentions else None
        target_token = None if mention else target
        await dispatch_expressive_verb(
            ctx, verb,
            target_token=target_token,
            mention=mention,
            self_directed_pool=self_directed_pool,
            bad_token_template=_BAD_TOKEN_TEMPLATES[verb],
            with_target_template=_WITH_TARGET_TEMPLATES.get(verb),
        )

    @command(name="lean", brief="Lean against something — or just stand pensive.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def lean(self, ctx: Context, *, target: str = None):
        """
        Lean against an object (campfire stones, the herbalist's
        tree-trunk corner, the stone field) or — bare — stand
        pensive in place.

        (5-second cool-down)

        :param target: The thing to lean against. Omit for a self-
            directed beat.
        """
        await self._dispatch(ctx, "lean", target, _LEAN_FLAVOR)

    @command(name="sit", brief="Sit on / by something — or just settle where you stand.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def sit(self, ctx: Context, *, target: str = None):
        """
        Sit by or on something (a stone, the campfire's ring) or —
        bare — settle where you are.

        (5-second cool-down)

        :param target: The thing to sit on or by. Omit for a self-
            directed beat.
        """
        await self._dispatch(ctx, "sit", target, _SIT_FLAVOR)

    @command(name="rest", brief="Rest near something — or just close your eyes a moment.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def rest(self, ctx: Context, *, target: str = None):
        """
        Pause and rest, near a feature of the clearing or just
        wherever you are.

        (5-second cool-down)

        :param target: The thing to rest near. Omit for a self-
            directed beat.
        """
        await self._dispatch(ctx, "rest", target, _REST_FLAVOR)

    @command(name="ponder", aliases=["contemplate", "consider"],
             brief="Direct your contemplation at something — or at nothing.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def ponder(self, ctx: Context, *, target: str = None):
        """
        Ponder a feature of the clearing, an NPC, or — bare — the
        middle distance.

        (5-second cool-down)

        :param target: The thing to ponder. Omit for a self-
            directed beat.
        """
        await self._dispatch(ctx, "ponder", target, _PONDER_FLAVOR)

    @command(name="tend", brief="Tend to something — small caretaking gesture.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def tend(self, ctx: Context, *, target: str = None):
        """
        Offer a small caretaking gesture — adjust the campfire's
        embers, brush dirt off the stones, check on an NPC. Bare
        ``$tend`` tends to yourself a moment.

        (5-second cool-down)

        :param target: The thing to tend to. Omit for a self-
            directed beat.
        """
        await self._dispatch(ctx, "tend", target, _TEND_FLAVOR)

    @command(name="bite", aliases=["nip"],
             brief="Bite at something — or fidget at the air.")
    @guild_only()
    @cooldown(1, 5, BucketType.member)
    async def bite(self, ctx: Context, *, target: str = None):
        """
        Bite at something physical (the campfire is delighted; most
        other things are not). Bare ``$bite`` is a fidget / mouth-
        thing — emotion-ambiguous by design (use an adverb later
        when that ships).

        (5-second cool-down)

        :param target: The thing to bite. Omit for a self-directed
            beat. NPCs do not have $bite reactions in V1.
        """
        await self._dispatch(ctx, "bite", target, _BITE_FLAVOR)

    @Cog.listener()
    async def on_ready(self):
        _log.info("RpgPresenceCommands ready.")


async def setup(bot):
    await bot.add_cog(RpgPresenceCommands(bot))
